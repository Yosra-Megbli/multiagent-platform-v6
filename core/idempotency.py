"""
IDEMPOTENCY LAYER
==================
Prevents duplicate jobs from the same request.
Client sends Idempotency-Key header → same result returned on retry.

Flow:
  First request:  Idempotency-Key: "req-abc-123" → create job, cache key
  Second request: Idempotency-Key: "req-abc-123" → return cached job_id
  No duplicate billing, no duplicate processing.
"""

import os
import json
from datetime import datetime
import redis.asyncio as redis

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
IDEMPOTENCY_TTL = 60 * 60 * 24  # 24 hours


async def check_idempotency(idempotency_key: str, tenant_id: str) -> dict | None:
    """
    Returns cached response if key already exists for this tenant.
    Returns None if this is a new request.
    """
    if not idempotency_key:
        return None

    cache_key = f"idempotency:{tenant_id}:{idempotency_key}"
    cached = await redis_client.get(cache_key)

    if cached:
        data = json.loads(cached)
        data["idempotent_replay"] = True
        print(f"[IDEMPOTENCY] Replay: tenant={tenant_id} key={idempotency_key}")
        return data

    return None


async def store_idempotency(idempotency_key: str, tenant_id: str, response: dict):
    """
    Stores response for an idempotency key.
    Called after job is successfully created.
    """
    if not idempotency_key:
        return

    cache_key = f"idempotency:{tenant_id}:{idempotency_key}"
    await redis_client.setex(
        cache_key,
        IDEMPOTENCY_TTL,
        json.dumps(response, default=str)
    )
    print(f"[IDEMPOTENCY] Stored: tenant={tenant_id} key={idempotency_key}")
