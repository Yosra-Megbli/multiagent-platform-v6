"""
BUSINESS KPIs — v5
===================
MEDIUM FIX: _get_hitl_events() and _get_agent_errors() previously
decoded each Redis entry 2-3 times (json.loads inside list comprehension
AND inside filter). For 10k decisions that's 30k redundant decode calls.
Now decoded once into a plain list, then filtered in-memory.

MEDIUM FIX: _get_cost_history() now uses a pipeline to batch all
daily-cost GET calls instead of N sequential awaits.
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone, date
from typing import Optional
import redis.asyncio as redis

logger       = logging.getLogger(__name__)
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))


async def get_business_kpis(tenant_id: str, days: int = 30) -> dict:
    decisions    = await _get_decisions(tenant_id, days)
    costs        = await _get_cost_history(tenant_id, days)
    hitl_events  = await _get_hitl_events(tenant_id, days, decisions)   # pass decoded list
    agent_errors = await _get_agent_errors(tenant_id, days, decisions)  # pass decoded list

    total = len(decisions)
    if total == 0:
        return {"message": "No data yet", "period_days": days}

    accuracy_scores  = [d["forecast_accuracy"] for d in decisions if d.get("forecast_accuracy")]
    avg_accuracy     = round(sum(accuracy_scores) / len(accuracy_scores) * 100, 1) if accuracy_scores else None

    hitl_count  = len(hitl_events)
    hitl_rate   = round(hitl_count / total * 100, 1)

    total_cost        = sum(costs)
    cost_per_decision = round(total_cost / total, 4) if total > 0 else 0

    SAVINGS_PER_DECISION = float(os.getenv("ROI_SAVINGS_PER_DECISION", "500"))
    accurate_decisions   = len([d for d in decisions if d.get("forecast_accuracy", 0) > 0.85])
    estimated_roi        = round(accurate_decisions * SAVINGS_PER_DECISION - total_cost, 2)

    total_agent_calls = total * 3
    error_rate        = round(len(agent_errors) / max(total_agent_calls, 1) * 100, 1)
    reliability       = round(100 - error_rate, 1)

    urgency_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for d in decisions:
        u = d.get("urgency", "LOW")
        urgency_counts[u] = urgency_counts.get(u, 0) + 1

    # Compute success rate from job statuses (jobs stored in decisions list)
    done_count = len([d for d in decisions if d.get("status") != "error"])
    success_rate = round(done_count / total, 3) if total > 0 else 0

    # Avg latency: estimate from stored latency field or default
    latency_vals = [d.get("latency_seconds") for d in decisions if d.get("latency_seconds")]
    avg_latency = round(sum(latency_vals) / len(latency_vals), 1) if latency_vals else None

    return {
        "period_days":     days,
        "total_decisions": total,
        "total_analyses":  total,          # FIX 6: alias for frontend compatibility
        "success_rate":    success_rate,   # FIX 7: field expected by frontend
        "avg_latency_seconds": avg_latency, # FIX 7: field expected by frontend
        "summary": {
            "decision_accuracy":  f"{avg_accuracy}%" if avg_accuracy else "N/A",
            "hitl_rate":          f"{hitl_rate}%",
            "estimated_roi_usd":  f"${estimated_roi:,.2f}",
            "cost_per_decision":  f"${cost_per_decision:.4f}",
            "agent_reliability":  f"{reliability}%",
        },
        "details": {
            "accurate_decisions":   accurate_decisions,
            "hitl_interventions":   hitl_count,
            "total_cost_usd":       round(total_cost, 4),
            "agent_errors":         len(agent_errors),
            "urgency_distribution": urgency_counts,
        },
        "health":       _compute_health(avg_accuracy, hitl_rate, reliability),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _compute_health(accuracy, hitl_rate, reliability) -> dict:
    score  = 100.0
    issues = []
    if accuracy and accuracy < 70:
        score -= 20
        issues.append(f"Low forecast accuracy ({accuracy}%). Check data quality.")
    if hitl_rate > 30:
        score -= 15
        issues.append(f"High HITL rate ({hitl_rate}%). Consider lowering confidence threshold.")
    if reliability < 95:
        score -= 15
        issues.append(f"Agent reliability below 95% ({reliability}%). Check external APIs.")
    status = "excellent" if score >= 90 else "good" if score >= 75 else "needs_attention"
    return {"score": round(score, 1), "status": status, "issues": issues}


async def record_decision_outcome(tenant_id: str, job_id: str, outcome: dict):
    key   = f"kpi:decisions:{tenant_id}"
    entry = {"job_id": job_id, "timestamp": datetime.now(timezone.utc).isoformat(), **outcome}
    await redis_client.lpush(key, json.dumps(entry))
    await redis_client.expire(key, 86400 * 90)
    await redis_client.ltrim(key, 0, 9999)


async def _get_decisions(tenant_id: str, days: int) -> list[dict]:
    """Decode once, filter once."""
    entries = await redis_client.lrange(f"kpi:decisions:{tenant_id}", 0, -1)
    cutoff  = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    # MEDIUM FIX: single decode pass
    decoded = [json.loads(e) for e in entries]
    return [d for d in decoded if d.get("timestamp", "") >= cutoff]


async def _get_cost_history(tenant_id: str, days: int) -> list[float]:
    """MEDIUM FIX: batch all Redis GETs in a single pipeline."""
    today  = date.today()
    keys   = [f"cost:{tenant_id}:daily:{(today - timedelta(days=i)).isoformat()}" for i in range(days)]
    pipe   = redis_client.pipeline()
    for k in keys:
        pipe.get(k)
    results = await pipe.execute()
    return [float(v) for v in results if v is not None]


async def _get_hitl_events(tenant_id: str, days: int, decisions: list[dict] | None = None) -> list:
    """MEDIUM FIX: reuse already-decoded list to avoid triple json.loads."""
    if decisions is None:
        decisions = await _get_decisions(tenant_id, days)
    return [d for d in decisions if d.get("requires_human")]


async def _get_agent_errors(tenant_id: str, days: int, decisions: list[dict] | None = None) -> list:
    """MEDIUM FIX: reuse already-decoded list."""
    if decisions is None:
        decisions = await _get_decisions(tenant_id, days)
    return [d for d in decisions if d.get("errors")]
