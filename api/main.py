"""FastAPI Main — V5: All CRITICAL + HIGH + MEDIUM fixes applied"""

import os
import json
import hmac
import logging
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, field_validator
from typing import Optional
import redis.asyncio as redis

from sectors.registry import list_available_sectors
from api.deps import get_tenant
from api.hitl_routes import router as hitl_router
from api.observability_routes import router as obs_router
from core.jobs import create_job, get_job, list_jobs, JobStatus
from core.rate_limiting import check_rate_limit, get_rate_limit_status
from core.idempotency import check_idempotency, store_idempotency
from core.queue_control import check_backpressure, increment_queue, get_queue_stats, get_queue_for_sector
from core.rbac import audit_log, require_permission, has_permission, get_audit_logs
from core.kpis import get_business_kpis
from worker import process_analysis_job

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Multi-Agent Platform V5",
    description="Production-ready multi-agent SaaS platform",
    version="5.0.0",
)

# CORS: allow frontend served from localhost (dev) or file:// (direct HTML open)
_DEFAULT_ORIGINS = "http://localhost:3000,http://localhost:5500,http://127.0.0.1:5500,http://localhost:8080,null"
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"http://localhost(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(hitl_router)
app.include_router(obs_router)

redis_client   = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
# MEDIUM FIX: allowed internal/private IP prefixes for SSRF protection
_BLOCKED_PREFIXES = ("10.", "172.", "192.168.", "127.", "169.254.", "::1", "fc", "fd")


def _validate_webhook_url(url: str) -> str:
    """Raises ValueError if the URL targets a private/internal address."""
    try:
        parsed = urlparse(url)
    except Exception:
        raise ValueError("Invalid webhook_url")
    if parsed.scheme not in ("http", "https"):
        raise ValueError("webhook_url must use http or https")
    host = (parsed.hostname or "").lower()
    if any(host.startswith(p) for p in _BLOCKED_PREFIXES):
        raise ValueError("webhook_url targets a private/internal address")
    return url


class AnalysisRequest(BaseModel):
    input_data:  dict
    date_range:  Optional[str] = "next_30_days"
    webhook_url: Optional[str] = None

    @field_validator("webhook_url", mode="before")
    @classmethod
    def validate_webhook(cls, v):
        if v:
            _validate_webhook_url(v)
        return v


# CRIT-3 FIX: secret value in request body, not query param
class SecretRequest(BaseModel):
    value: str


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    queue_stats = await get_queue_stats()
    return {
        "status": "ok", "version": "5.0.0",
        "available_sectors": list_available_sectors(),
        "queue": queue_stats,
    }


# ─── Analyze ──────────────────────────────────────────────────────────────────

@app.post("/analyze", status_code=202)
async def analyze(
    request: AnalysisRequest,
    req: Request,
    tenant: dict = Depends(get_tenant),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    tenant_id = tenant["tenant_id"]
    sector    = tenant["sector"]
    plan      = tenant.get("plan", "starter")

    if idempotency_key:
        cached = await check_idempotency(idempotency_key, tenant_id)
        if cached:
            return cached

    rate_info = await check_rate_limit(tenant_id, plan)

    bp = await check_backpressure(tenant_id)
    if not bp["allowed"]:
        raise HTTPException(status_code=503, detail=bp)

    input_data = dict(request.input_data)
    if request.webhook_url:
        input_data["webhook_url"] = request.webhook_url

    # Inject ERP connector config from tenant record into state
    tenant_config = tenant.get("config", {})
    input_data["tenant_config"] = tenant_config

    job_id = await create_job(tenant_id, sector, input_data)
    await increment_queue(tenant_id)

    queue = get_queue_for_sector(sector)
    process_analysis_job.apply_async(
        args=[job_id, tenant_id, sector, input_data],
        queue=queue,
    )

    response = {
        "job_id": job_id, "status": JobStatus.QUEUED,
        "poll_url": f"/jobs/{job_id}",
        "queue": queue, "rate_limit": rate_info,
    }

    if idempotency_key:
        await store_idempotency(idempotency_key, tenant_id, response)

    await audit_log(
        tenant_id, tenant.get("user_id", "api"),
        "analyze", f"job:{job_id}",
        details={"sector": sector, "queue": queue},
        ip_address=req.client.host,
    )

    return response


# ─── Jobs ─────────────────────────────────────────────────────────────────────

@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str, tenant: dict = Depends(get_tenant)):
    job = await get_job(job_id)
    if not job or job["tenant_id"] != tenant["tenant_id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/jobs")
async def get_all_jobs(tenant: dict = Depends(get_tenant)):
    return await list_jobs(tenant["tenant_id"])


@app.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, req: Request, tenant: dict = Depends(get_tenant)):
    if not has_permission(tenant, "retry_jobs"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    job = await get_job(job_id)
    if not job or job["tenant_id"] != tenant["tenant_id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "error":
        raise HTTPException(status_code=400, detail=f"Cannot retry status: {job['status']}")

    from core.jobs import update_job
    await update_job(job_id, JobStatus.QUEUED)
    process_analysis_job.delay(job_id, tenant["tenant_id"], tenant["sector"], job["input_data"])

    await audit_log(tenant["tenant_id"], tenant.get("user_id", "api"),
                    "retry_job", f"job:{job_id}", ip_address=req.client.host)
    return {"job_id": job_id, "status": "requeued"}


# ─── KPIs ─────────────────────────────────────────────────────────────────────

@app.get("/kpis")
async def business_kpis(days: int = 30, tenant: dict = Depends(get_tenant)):
    return await get_business_kpis(tenant["tenant_id"], days)


# ─── Audit Logs ───────────────────────────────────────────────────────────────

@app.get("/audit-logs")
async def audit_logs(tenant: dict = Depends(get_tenant)):
    if not has_permission(tenant, "view_audit_logs"):
        raise HTTPException(status_code=403, detail="Admin only")
    return await get_audit_logs(tenant["tenant_id"])


# ─── Queue stats ──────────────────────────────────────────────────────────────

@app.get("/queue-stats")
async def queue_stats(tenant: dict = Depends(get_tenant)):
    return await get_queue_stats()


# ─── DLQ ──────────────────────────────────────────────────────────────────────

@app.get("/dlq")
async def get_dlq(tenant: dict = Depends(get_tenant)):
    raw = await redis_client.lrange("dlq:failed_jobs", 0, 49)
    return [e for e in [json.loads(r) for r in raw] if e.get("tenant_id") == tenant["tenant_id"]]


# ─── Circuit breakers ─────────────────────────────────────────────────────────

@app.get("/circuit-breakers")
async def circuit_breakers(tenant: dict = Depends(get_tenant)):
    from core.circuit_breaker import _breakers
    return {name: await b.get_state() for name, b in _breakers.items()}


# ─── Rate limit ───────────────────────────────────────────────────────────────

@app.get("/rate-limit")
async def rate_limit(tenant: dict = Depends(get_tenant)):
    return await get_rate_limit_status(tenant["tenant_id"], tenant.get("plan", "starter"))


# ─── Outcomes ─────────────────────────────────────────────────────────────────

class OutcomeRequest(BaseModel):
    actual_demand: float
    action_taken:  bool = True
    notes:         Optional[str] = None


@app.post("/outcomes/{job_id}")
async def record_outcome(
    job_id: str,
    body: OutcomeRequest,
    req: Request,
    tenant: dict = Depends(get_tenant),
):
    """
    Client soumet le résultat réel après avoir agi sur une recommandation.
    - Calcule la précision vs prédiction Prophet
    - Met à jour accuracy dans decision_memory (RAG)
    - Enrichit le job Redis avec le résultat réel
    """
    tenant_id = tenant["tenant_id"]
    sector    = tenant["sector"]

    # 1. Récupérer le job
    job = await get_job(job_id)
    if not job or job["tenant_id"] != tenant_id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] not in ("done", "rejected"):
        raise HTTPException(status_code=400, detail="Job must be completed before recording outcome")

    product_id = job.get("input_data", {}).get("product_id", "DEFAULT")

    # 2. Calculer la précision vs prédiction Prophet (via memory_safety)
    from core.memory_safety import save_actual_outcome_safe
    result = await save_actual_outcome_safe(tenant_id, sector, product_id, body.actual_demand)

    # 3. Mettre à jour accuracy dans decision_memory (pgvector RAG)
    accuracy = result.get("accuracy")
    if accuracy is not None:
        try:
            from db.database import get_pool, DEMO_MODE
            if not DEMO_MODE:
                pool = await get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE decision_memory
                        SET accuracy = $1
                        WHERE tenant_id = $2 AND product_id = $3 AND sector = $4
                          AND id = (
                              SELECT id FROM decision_memory
                              WHERE tenant_id = $2 AND product_id = $3 AND sector = $4
                              ORDER BY created_at DESC LIMIT 1
                          )
                        """,
                        accuracy, tenant_id, product_id, sector,
                    )
        except Exception as e:
            logger.warning("[OUTCOMES] RAG accuracy update failed: %s", str(e))

    # 4. Enrichir le job Redis avec le résultat réel
    import datetime as _dt
    outcome_data = {
        "actual_demand": body.actual_demand,
        "action_taken":  body.action_taken,
        "notes":         body.notes,
        "accuracy":      accuracy,
        "recorded_at":   _dt.datetime.utcnow().isoformat(),
    }
    job["outcome"] = outcome_data
    await redis_client.setex(
        f"job:{job_id}",
        7 * 24 * 3600,
        json.dumps(job),
    )

    # 5. Audit log
    await audit_log(
        tenant_id, tenant.get("user_id", "api"),
        "record_outcome", f"job:{job_id}",
        details={"accuracy": accuracy, "actual_demand": body.actual_demand},
        ip_address=req.client.host,
    )

    return {
        "job_id":        job_id,
        "product_id":    product_id,
        "actual_demand": body.actual_demand,
        "accuracy":      accuracy,
        "action_taken":  body.action_taken,
        "saved":         result.get("saved", False),
        "message":       result.get("reason", "Outcome recorded successfully"),
    }


# ─── Secrets — CRIT-3 FIX: value in body, not query param ────────────────────

@app.post("/secrets/{secret_name}")
async def store_secret(
    secret_name: str,
    body: SecretRequest,
    req: Request,
    tenant: dict = Depends(get_tenant),
):
    if not has_permission(tenant, "manage_secrets"):
        raise HTTPException(status_code=403, detail="Admin only")
    from core.secrets import store_secret as _store
    await _store(tenant["tenant_id"], secret_name, body.value)
    await audit_log(tenant["tenant_id"], tenant.get("user_id", "api"),
                    "store_secret", secret_name, ip_address=req.client.host)
    return {"stored": True, "secret_name": secret_name}


@app.get("/secrets")
async def list_secrets(tenant: dict = Depends(get_tenant)):
    from core.secrets import list_secrets as _list
    return {"secrets": await _list(tenant["tenant_id"])}


@app.get("/sectors")
async def sectors():
    return {"available_sectors": list_available_sectors()}


# ─── ERP Proxy ────────────────────────────────────────────────────────────────

@app.get("/erp/items")
async def erp_items(tenant: dict = Depends(get_tenant)):
    """Proxy to ERP — avoids CORS issues from browser."""
    import httpx
    erp_url    = os.getenv("ERPUIUX_URL", "http://localhost:8080")
    api_key    = os.getenv("ERPUIUX_API_KEY", "")
    api_secret = os.getenv("ERPUIUX_SECRET", "")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"{erp_url}/api/resource/Item",
                params={"fields": '["item_code","item_name"]', "limit": 100},
                headers={"Authorization": f"token {api_key}:{api_secret}"},
            )
            r.raise_for_status()
            items = r.json().get("data", [])
            return {"connected": True, "items": items, "count": len(items)}
    except Exception as e:
        logger.warning("[ERP PROXY] %s", str(e))
        return {"connected": False, "items": [], "count": 0}
