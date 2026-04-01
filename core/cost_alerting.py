"""
COST ALERTING
==============
Monitors LLM spending per tenant and sends alerts when thresholds are exceeded.
Prevents runaway costs from infinite loops or misconfigured agents.

Thresholds (configurable per tenant):
  - Per request:  alert if single request > $0.50
  - Per day:      alert if daily spend > $10.00
  - Per month:    alert if monthly spend > $100.00
"""

import os
import json
from datetime import datetime, date
import redis.asyncio as redis
import httpx

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
ALERT_WEBHOOK = os.getenv("COST_ALERT_WEBHOOK")

# Default thresholds (USD)
DEFAULT_REQUEST_LIMIT  = float(os.getenv("COST_REQUEST_LIMIT",  "0.50"))
DEFAULT_DAILY_LIMIT    = float(os.getenv("COST_DAILY_LIMIT",   "10.00"))
DEFAULT_MONTHLY_LIMIT  = float(os.getenv("COST_MONTHLY_LIMIT", "100.00"))


async def track_cost(tenant_id: str, sector: str, cost_usd: float, job_id: str = None):
    """
    Records cost and checks against thresholds.
    Sends alert if any threshold is exceeded.
    """
    today = date.today().isoformat()
    month = today[:7]  # "2026-03"

    # Increment counters
    daily_key   = f"cost:{tenant_id}:daily:{today}"
    monthly_key = f"cost:{tenant_id}:monthly:{month}"

    pipe = redis_client.pipeline()
    pipe.incrbyfloat(daily_key, cost_usd)
    pipe.expire(daily_key, 86400 * 2)     # 2 days
    pipe.incrbyfloat(monthly_key, cost_usd)
    pipe.expire(monthly_key, 86400 * 35)  # 35 days
    await pipe.execute()

    daily_total   = float(await redis_client.get(daily_key) or 0)
    monthly_total = float(await redis_client.get(monthly_key) or 0)

    print(f"[COST] tenant={tenant_id} | request=${cost_usd:.4f} | daily=${daily_total:.4f} | monthly=${monthly_total:.4f}")

    # Check thresholds
    alerts = []

    if cost_usd > DEFAULT_REQUEST_LIMIT:
        alerts.append({
            "type": "REQUEST_LIMIT_EXCEEDED",
            "value": cost_usd,
            "limit": DEFAULT_REQUEST_LIMIT,
            "message": f"Single request cost ${cost_usd:.4f} exceeded limit ${DEFAULT_REQUEST_LIMIT}",
        })

    if daily_total > DEFAULT_DAILY_LIMIT:
        alerts.append({
            "type": "DAILY_LIMIT_EXCEEDED",
            "value": daily_total,
            "limit": DEFAULT_DAILY_LIMIT,
            "message": f"Daily spend ${daily_total:.2f} exceeded limit ${DEFAULT_DAILY_LIMIT}",
        })

    if monthly_total > DEFAULT_MONTHLY_LIMIT:
        alerts.append({
            "type": "MONTHLY_LIMIT_EXCEEDED",
            "value": monthly_total,
            "limit": DEFAULT_MONTHLY_LIMIT,
            "message": f"Monthly spend ${monthly_total:.2f} exceeded limit ${DEFAULT_MONTHLY_LIMIT}",
        })

    # Send alerts
    for alert in alerts:
        await _send_cost_alert(tenant_id, sector, alert, job_id)

    return {
        "request_cost": cost_usd,
        "daily_total": daily_total,
        "monthly_total": monthly_total,
        "alerts": [a["type"] for a in alerts],
    }


async def get_cost_summary(tenant_id: str) -> dict:
    """Returns cost summary for a tenant."""
    today = date.today().isoformat()
    month = today[:7]

    daily_total   = float(await redis_client.get(f"cost:{tenant_id}:daily:{today}") or 0)
    monthly_total = float(await redis_client.get(f"cost:{tenant_id}:monthly:{month}") or 0)

    return {
        "tenant_id": tenant_id,
        "today": today,
        "daily_spend_usd": round(daily_total, 4),
        "monthly_spend_usd": round(monthly_total, 4),
        "daily_limit_usd": DEFAULT_DAILY_LIMIT,
        "monthly_limit_usd": DEFAULT_MONTHLY_LIMIT,
        "daily_remaining_usd": round(max(0, DEFAULT_DAILY_LIMIT - daily_total), 4),
        "monthly_remaining_usd": round(max(0, DEFAULT_MONTHLY_LIMIT - monthly_total), 4),
    }


async def _send_cost_alert(tenant_id: str, sector: str, alert: dict, job_id: str = None):
    """Sends cost alert via webhook."""
    print(f"[COST ALERT] {alert['type']}: {alert['message']}")

    if not ALERT_WEBHOOK:
        return

    payload = {
        "alert_type": alert["type"],
        "tenant_id": tenant_id,
        "sector": sector,
        "job_id": job_id,
        "message": alert["message"],
        "value_usd": alert["value"],
        "limit_usd": alert["limit"],
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        async with httpx.AsyncClient() as client:
            await client.post(ALERT_WEBHOOK, json=payload, timeout=5)
    except Exception as e:
        print(f"[COST ALERT] Webhook failed: {e}")
