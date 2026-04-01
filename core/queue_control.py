"""
QUEUE CONTROL & BACKPRESSURE
==============================
Prevents worker explosion when request volume spikes.

Problems solved:
  1. 10k requests arrive → worker RAM explodes
  2. Heavy jobs (Legal doc processing) starve light jobs (weather check)
  3. No visibility on queue depth

Solutions:
  - Max queue size per tenant (backpressure)
  - Separate queues: light vs heavy jobs
  - Queue depth monitoring
"""

import os
import redis.asyncio as redis

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))

MAX_QUEUE_SIZE    = int(os.getenv("MAX_QUEUE_SIZE",    "100"))  # global
MAX_TENANT_QUEUE  = int(os.getenv("MAX_TENANT_QUEUE",  "10"))   # per tenant
HEAVY_JOB_TIMEOUT = int(os.getenv("HEAVY_JOB_TIMEOUT", "600"))  # 10 min
LIGHT_JOB_TIMEOUT = int(os.getenv("LIGHT_JOB_TIMEOUT", "300"))  # 5 min

# Sectors classified by job weight
HEAVY_SECTORS = {"legal", "real_estate"}
LIGHT_SECTORS = {"supply_chain", "hr"}


def get_queue_for_sector(sector: str) -> str:
    """Routes jobs to appropriate queue based on expected processing time."""
    return "heavy" if sector in HEAVY_SECTORS else "light"


async def check_backpressure(tenant_id: str) -> dict:
    """
    Checks if system can accept a new job.
    Returns: {"allowed": bool, "reason": str}
    """
    # Global queue depth
    global_depth = await _get_global_queue_depth()
    if global_depth >= MAX_QUEUE_SIZE:
        return {
            "allowed": False,
            "reason": f"System at capacity ({global_depth}/{MAX_QUEUE_SIZE} jobs queued). Try again in a few minutes.",
            "global_depth": global_depth,
            "retry_after": 60,
        }

    # Per-tenant queue depth
    tenant_depth = await _get_tenant_queue_depth(tenant_id)
    if tenant_depth >= MAX_TENANT_QUEUE:
        return {
            "allowed": False,
            "reason": f"Your queue is full ({tenant_depth}/{MAX_TENANT_QUEUE} jobs). Wait for current jobs to complete.",
            "tenant_depth": tenant_depth,
            "retry_after": 30,
        }

    return {
        "allowed": True,
        "global_depth": global_depth,
        "tenant_depth": tenant_depth,
    }


async def increment_queue(tenant_id: str):
    """Increments queue counters when job is added."""
    await redis_client.incr("queue:global:depth")
    await redis_client.incr(f"queue:tenant:{tenant_id}:depth")
    await redis_client.expire(f"queue:tenant:{tenant_id}:depth", 3600)


async def decrement_queue(tenant_id: str):
    """Decrements queue counters when job completes."""
    global_val = int(await redis_client.get("queue:global:depth") or 0)
    if global_val > 0:
        await redis_client.decr("queue:global:depth")

    tenant_val = int(await redis_client.get(f"queue:tenant:{tenant_id}:depth") or 0)
    if tenant_val > 0:
        await redis_client.decr(f"queue:tenant:{tenant_id}:depth")


async def get_queue_stats() -> dict:
    """Returns current queue statistics for monitoring."""
    global_depth = await _get_global_queue_depth()
    return {
        "global_depth": global_depth,
        "global_capacity": MAX_QUEUE_SIZE,
        "global_utilization": round(global_depth / MAX_QUEUE_SIZE * 100, 1),
        "status": "healthy" if global_depth < MAX_QUEUE_SIZE * 0.8 else "under_pressure",
    }


async def _get_global_queue_depth() -> int:
    return int(await redis_client.get("queue:global:depth") or 0)


async def _get_tenant_queue_depth(tenant_id: str) -> int:
    return int(await redis_client.get(f"queue:tenant:{tenant_id}:depth") or 0)
