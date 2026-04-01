"""
MEMORY MANAGEMENT — v5
========================
MEDIUM FIX: replaced deprecated datetime.utcnow() with
datetime.now(timezone.utc) throughout. The old naive datetimes
could cause comparison errors when mixed with timezone-aware values.
"""

import os
import json
import logging
from datetime import datetime, timezone
import redis.asyncio as redis

logger = logging.getLogger(__name__)
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
MEMORY_TTL   = 60 * 60 * 24 * 30  # 30 days


async def save_decision_memory(
    tenant_id: str, sector: str, product_id: str,
    recommendation: dict, confidence: float,
):
    key     = f"memory:{tenant_id}:{sector}:{product_id}:last_decision"
    payload = {
        "timestamp":      datetime.now(timezone.utc).isoformat(),   # MEDIUM FIX
        "recommendation": recommendation,
        "confidence":     confidence,
        "actual_outcome": None,
    }
    await redis_client.setex(key, MEMORY_TTL, json.dumps(payload))


async def save_actual_outcome(
    tenant_id: str, sector: str, product_id: str, actual_demand: float,
):
    key = f"memory:{tenant_id}:{sector}:{product_id}:last_decision"
    raw = await redis_client.get(key)
    if not raw:
        return

    memory = json.loads(raw)
    memory["actual_outcome"] = {
        "actual_demand": actual_demand,
        "recorded_at":   datetime.now(timezone.utc).isoformat(),   # MEDIUM FIX
    }

    predicted = memory["recommendation"].get("adjusted_30_days")
    if predicted and predicted > 0:
        accuracy = 1 - abs(actual_demand - predicted) / predicted
        memory["forecast_accuracy"] = round(accuracy, 3)

    await redis_client.setex(key, MEMORY_TTL, json.dumps(memory))


async def get_last_decision(tenant_id: str, sector: str, product_id: str) -> dict | None:
    key = f"memory:{tenant_id}:{sector}:{product_id}:last_decision"
    raw = await redis_client.get(key)
    return json.loads(raw) if raw else None


async def get_adjustment_factor(tenant_id: str, sector: str, product_id: str) -> float:
    memory = await get_last_decision(tenant_id, sector, product_id)
    if not memory or not memory.get("actual_outcome"):
        return 1.0

    accuracy = memory.get("forecast_accuracy")
    if accuracy is None:
        return 1.0
    if accuracy >= 0.90:
        return 1.0

    predicted = memory["recommendation"].get("adjusted_30_days", 0)
    actual    = memory["actual_outcome"].get("actual_demand", 0)

    if predicted > 0 and actual > 0:
        ratio      = actual / predicted
        adjustment = 1.0 + (ratio - 1.0) * 0.5
        return round(max(0.5, min(1.5, adjustment)), 3)

    return 1.0


async def get_memory_summary(tenant_id: str, sector: str, product_id: str) -> dict:
    memory = await get_last_decision(tenant_id, sector, product_id)
    if not memory:
        return {"has_history": False}

    accuracy   = memory.get("forecast_accuracy")
    adjustment = await get_adjustment_factor(tenant_id, sector, product_id)

    return {
        "has_history":       True,
        "last_decision_at":  memory.get("timestamp"),
        "last_confidence":   memory.get("confidence"),
        "forecast_accuracy": accuracy,
        "adjustment_factor": adjustment,
        "note":              _generate_memory_note(accuracy, adjustment),
    }


def _generate_memory_note(accuracy: float | None, adjustment: float) -> str:
    if accuracy is None:
        return "No outcome data yet."
    if accuracy >= 0.90:
        return f"Last forecast was accurate ({accuracy:.0%}). No adjustment needed."
    if adjustment < 1.0:
        return f"Last forecast was too optimistic ({accuracy:.0%} accuracy). Reducing estimate by {(1-adjustment):.0%}."
    if adjustment > 1.0:
        return f"Last forecast was too conservative ({accuracy:.0%} accuracy). Increasing estimate by {(adjustment-1):.0%}."
    return f"Forecast accuracy: {accuracy:.0%}."
