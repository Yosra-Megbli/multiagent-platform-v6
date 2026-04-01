"""
MEMORY RESET & SAFETY — v5
============================
MEDIUM FIX: datetime.utcnow() replaced with datetime.now(timezone.utc).
"""

import os
import json
import logging
from datetime import datetime, timezone
import redis.asyncio as redis

logger = logging.getLogger(__name__)
redis_client      = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
ACCURACY_FLOOR    = float(os.getenv("MEMORY_ACCURACY_FLOOR",    "0.40"))
ANOMALY_THRESHOLD = float(os.getenv("MEMORY_ANOMALY_THRESHOLD", "3.0"))
MEMORY_TTL        = 60 * 60 * 24 * 30


async def save_actual_outcome_safe(
    tenant_id: str, sector: str, product_id: str, actual_demand: float,
) -> dict:
    key = f"memory:{tenant_id}:{sector}:{product_id}:last_decision"
    raw = await redis_client.get(key)
    if not raw:
        return {"saved": False, "reason": "No prediction found to compare against"}

    memory    = json.loads(raw)
    predicted = memory.get("recommendation", {}).get("adjusted_30_days", 0)

    if predicted and predicted > 0:
        ratio = actual_demand / predicted
        if ratio > ANOMALY_THRESHOLD or ratio < (1 / ANOMALY_THRESHOLD):
            return {
                "saved": False,
                "reason": f"Anomaly detected: actual={actual_demand}, predicted={predicted}, ratio={ratio:.2f}.",
                "anomaly": True,
            }

    memory["actual_outcome"] = {
        "actual_demand": actual_demand,
        "recorded_at":   datetime.now(timezone.utc).isoformat(),   # MEDIUM FIX
    }

    if predicted and predicted > 0:
        accuracy = 1 - abs(actual_demand - predicted) / predicted
        memory["forecast_accuracy"] = round(accuracy, 3)
        if accuracy < ACCURACY_FLOOR:
            await reset_memory(tenant_id, sector, product_id, reason="auto_accuracy_floor")
            return {
                "saved": False,
                "reason": f"Memory auto-reset: accuracy {accuracy:.0%} below floor {ACCURACY_FLOOR:.0%}",
                "reset": True,
            }

    await redis_client.setex(key, MEMORY_TTL, json.dumps(memory))
    return {"saved": True, "accuracy": memory.get("forecast_accuracy")}


async def reset_memory(tenant_id: str, sector: str, product_id: str, reason: str = "manual") -> dict:
    key     = f"memory:{tenant_id}:{sector}:{product_id}:last_decision"
    existed = await redis_client.exists(key)
    await redis_client.delete(key)

    log_key = f"memory:{tenant_id}:{sector}:{product_id}:reset_log"
    log     = {
        "reset_at":   datetime.now(timezone.utc).isoformat(),   # MEDIUM FIX
        "reason":     reason,
        "tenant_id":  tenant_id,
        "product_id": product_id,
    }
    await redis_client.lpush(log_key, json.dumps(log))
    await redis_client.expire(log_key, MEMORY_TTL)

    logger.info("[MEMORY] Reset: tenant=%s product=%s reason=%s", tenant_id, product_id, reason)
    return {"reset": bool(existed), "reason": reason}


async def get_reset_log(tenant_id: str, sector: str, product_id: str) -> list[dict]:
    log_key = f"memory:{tenant_id}:{sector}:{product_id}:reset_log"
    entries = await redis_client.lrange(log_key, 0, 9)
    return [json.loads(e) for e in entries]
