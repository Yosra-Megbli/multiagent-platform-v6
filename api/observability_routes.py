"""
OBSERVABILITY ROUTES — v3.1
Added: rate limit status in dashboard
"""

from fastapi import APIRouter, Depends, HTTPException
from api.deps import get_tenant
from core.cost_alerting import get_cost_summary
from core.memory import get_memory_summary
from core.memory_safety import get_reset_log
from core.jobs import list_jobs, get_job
from core.rate_limiting import get_rate_limit_status
import redis.asyncio as redis
import os
import json

router = APIRouter(prefix="/observability", tags=["Observability"])
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))


@router.get("/dashboard")
async def get_dashboard(tenant: dict = Depends(get_tenant)):
    tenant_id = tenant["tenant_id"]
    sector    = tenant["sector"]
    plan      = tenant.get("plan", "starter")

    costs      = await get_cost_summary(tenant_id)
    jobs       = await list_jobs(tenant_id, limit=10)
    rate_limit = await get_rate_limit_status(tenant_id, plan)

    status_counts = {}
    for job in jobs:
        s = job["status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    hitl_pending = [j for j in jobs if j["status"] == "pending_human"]

    return {
        "tenant_id": tenant_id,
        "sector": sector,
        "costs": costs,
        "rate_limit": rate_limit,
        "jobs": {
            "total": len(jobs),
            "by_status": status_counts,
            "recent": jobs[:5],
        },
        "hitl": {
            "pending_count": len(hitl_pending),
            "pending_jobs": hitl_pending,
        },
        "monitoring": {
            "flower_url": "http://localhost:5555",
            "note": "Celery worker monitoring dashboard",
        },
    }


@router.get("/costs")
async def get_costs(tenant: dict = Depends(get_tenant)):
    return await get_cost_summary(tenant["tenant_id"])


@router.get("/jobs")
async def get_jobs(tenant: dict = Depends(get_tenant)):
    return await list_jobs(tenant["tenant_id"])


@router.get("/jobs/{job_id}")
async def get_job_detail(job_id: str, tenant: dict = Depends(get_tenant)):
    job = await get_job(job_id)
    if not job or job["tenant_id"] != tenant["tenant_id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/rate-limit")
async def get_rate(tenant: dict = Depends(get_tenant)):
    return await get_rate_limit_status(tenant["tenant_id"], tenant.get("plan", "starter"))


@router.get("/memory/{product_id}")
async def get_memory(product_id: str, tenant: dict = Depends(get_tenant)):
    summary   = await get_memory_summary(tenant["tenant_id"], tenant["sector"], product_id)
    reset_log = await get_reset_log(tenant["tenant_id"], tenant["sector"], product_id)
    return {"memory": summary, "reset_history": reset_log}


@router.delete("/memory/{product_id}")
async def reset_memory_endpoint(product_id: str, tenant: dict = Depends(get_tenant)):
    from core.memory_safety import reset_memory
    return await reset_memory(tenant["tenant_id"], tenant["sector"], product_id, reason="manual_api")
