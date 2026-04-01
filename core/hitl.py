"""
HUMAN-IN-THE-LOOP (HITL) — v2 (non-blocking)
==============================================
CRIT-1 FIX: The previous version used a busy-wait polling loop that blocked
the Celery worker thread for up to HITL_TIMEOUT_SECONDS (1 hour).
This is now fully non-blocking:

  - hitl_checkpoint() sends the webhook and returns immediately
    with requires_human=True and a request_id.
  - The worker sets job status = PENDING_HUMAN and schedules
    resume_hitl_job (in worker.py) with a countdown.
  - resume_hitl_job() checks the Redis key once and finalises the job.
"""

import os
import uuid
import json
import httpx
import logging
import redis.asyncio as redis
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

HITL_WEBHOOK_URL          = os.getenv("HITL_WEBHOOK_URL")
HITL_CONFIDENCE_THRESHOLD = float(os.getenv("HITL_CONFIDENCE_THRESHOLD", "0.80"))
HITL_TIMEOUT_SECONDS      = int(os.getenv("HITL_TIMEOUT_SECONDS", "3600"))
HITL_FALLBACK_APPROVE     = os.getenv("HITL_FALLBACK_APPROVE", "true").lower() == "true"

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))


async def evaluate_confidence(insights: dict) -> float:
    score   = 1.0
    alerts  = insights.get("alerts", [])
    urgency = insights.get("urgency", "LOW")

    if "STOCK_CRITICAL" in alerts:          score -= 0.30
    if "CAPACITY_INSUFFICIENT" in alerts:   score -= 0.25
    if urgency == "HIGH" and len(alerts) >= 3: score -= 0.20
    if insights.get("has_fallback_data"):   score -= 0.25

    return round(max(0.0, min(1.0, score)), 3)


async def request_human_validation(
    tenant_id: str, sector: str, decision: str,
    insights: dict, confidence: float,
) -> dict:
    """
    Stores pending HITL in Redis, fires webhook, returns immediately.
    Does NOT poll or block the caller.
    """
    request_id   = str(uuid.uuid4())
    approval_key = f"hitl:approval:{request_id}"

    # FIX: expires_at is a FUTURE timestamp
    expires_iso = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + HITL_TIMEOUT_SECONDS,
        tz=timezone.utc
    ).isoformat()

    payload = {
        "request_id":      request_id,
        "tenant_id":       tenant_id,
        "sector":          sector,
        "confidence":      round(confidence * 100, 1),
        "urgency":         insights.get("urgency"),
        "alerts":          insights.get("alerts", []),
        "decision_preview": decision[:300] + "..." if len(decision) > 300 else decision,
        "approval_url":    f"{os.getenv('API_BASE_URL','http://localhost:8000')}/hitl/approve/{request_id}",
        "reject_url":      f"{os.getenv('API_BASE_URL','http://localhost:8000')}/hitl/reject/{request_id}",
        "expires_at":      expires_iso,
    }

    # Store BEFORE sending webhook to avoid race
    await redis_client.setex(approval_key, HITL_TIMEOUT_SECONDS, "pending")

    if HITL_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                await http.post(HITL_WEBHOOK_URL, json=payload)
            logger.info("[HITL] Webhook sent | request_id=%s | confidence=%.0f%%",
                        request_id, confidence * 100)
        except Exception as exc:
            logger.warning("[HITL] Webhook failed: %s", exc)

    return {"pending": True, "request_id": request_id}


async def resolve_hitl(request_id: str, decision_text: str) -> dict:
    """
    Called by resume_hitl_job (worker.py) after timeout elapses.
    Reads Redis once — no loop, no blocking.
    """
    approval_key = f"hitl:approval:{request_id}"
    result       = await redis_client.get(approval_key)

    if result and result not in (b"pending", b""):
        try:
            data = json.loads(result)
        except Exception:
            data = {}
        approved = data.get("approved", HITL_FALLBACK_APPROVE)
        reviewer = data.get("reviewer", "human")
        comment  = data.get("comment", "")
    else:
        approved = HITL_FALLBACK_APPROVE
        reviewer = "auto-timeout"
        comment  = ("Auto-approved after timeout" if HITL_FALLBACK_APPROVE
                    else "Rejected: no response within timeout")
        logger.info("[HITL] Timeout | request_id=%s | fallback=%s", request_id, HITL_FALLBACK_APPROVE)

    final_decision = (decision_text if approved
                      else f"[REJECTED by {reviewer}] {comment}")

    return {
        "approved": approved, "reviewer": reviewer,
        "comment": comment,   "final_decision": final_decision,
    }


async def hitl_checkpoint(
    tenant_id: str, sector: str, decision: str, insights: dict,
) -> dict:
    """
    Main entry point called by decision_agent.
    High confidence  → immediate approval, no I/O wait.
    Low confidence   → webhook sent, returns pending signal immediately.
    """
    confidence     = await evaluate_confidence(insights)
    requires_human = confidence < HITL_CONFIDENCE_THRESHOLD

    logger.info("[HITL] confidence=%.0f%% threshold=%.0f%% requires_human=%s",
                confidence * 100, HITL_CONFIDENCE_THRESHOLD * 100, requires_human)

    if not requires_human:
        return {
            "approved": True, "confidence": confidence,
            "requires_human": False, "reviewer": None,
            "final_decision": decision,
        }

    pending = await request_human_validation(
        tenant_id=tenant_id, sector=sector, decision=decision,
        insights=insights, confidence=confidence,
    )

    return {
        "approved": False, "confidence": confidence,
        "requires_human": True, "pending": True,
        "request_id": pending["request_id"],
        "final_decision": None,
    }
