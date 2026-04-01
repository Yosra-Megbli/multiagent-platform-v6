"""
RATE LIMITING — Per Tenant
===========================
Limits the number of analysis requests per tenant per time window.
Prevents abuse and ensures fair usage across all clients.

Limits (configurable):
  - Default: 10 requests per minute
  - Pro plan: 60 requests per minute
  - Enterprise: unlimited

Uses Redis sliding window counter.
"""

import os
import time
from fastapi import HTTPException
import redis.asyncio as redis

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))

# Requests per minute per plan
RATE_LIMITS = {
    "starter":    int(os.getenv("RATE_LIMIT_STARTER",    "10")),
    "pro":        int(os.getenv("RATE_LIMIT_PRO",        "60")),
    "enterprise": int(os.getenv("RATE_LIMIT_ENTERPRISE", "999999")) or 999999,
}

WINDOW_SECONDS = 60


async def check_rate_limit(tenant_id: str, plan: str = "starter"):
    """
    Checks and increments rate limit counter for a tenant.
    Raises HTTP 429 if limit exceeded.
    """
    limit = RATE_LIMITS.get(plan, RATE_LIMITS["starter"])

    if limit >= 999999:
        return  # Enterprise: no limit

    window = int(time.time() / WINDOW_SECONDS)
    key = f"ratelimit:{tenant_id}:{window}"

    current = await redis_client.incr(key)
    await redis_client.expire(key, WINDOW_SECONDS * 2)

    if current > limit:
        retry_after = WINDOW_SECONDS - (int(time.time()) % WINDOW_SECONDS)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit": limit,
                "window": f"{WINDOW_SECONDS}s",
                "retry_after": retry_after,
                "plan": plan,
                "upgrade": "Contact support to upgrade your plan",
            },
            headers={"Retry-After": str(retry_after)},
        )

    remaining = max(0, limit - current)
    print(f"[RATE] tenant={tenant_id} plan={plan} | {current}/{limit} | remaining={remaining}")
    return {"requests_used": current, "requests_limit": limit, "remaining": remaining}


async def get_rate_limit_status(tenant_id: str, plan: str = "starter") -> dict:
    """Returns current rate limit status without incrementing."""
    limit = RATE_LIMITS.get(plan, RATE_LIMITS["starter"])
    window = int(time.time() / WINDOW_SECONDS)
    key = f"ratelimit:{tenant_id}:{window}"

    current = int(await redis_client.get(key) or 0)
    retry_after = WINDOW_SECONDS - (int(time.time()) % WINDOW_SECONDS)

    return {
        "tenant_id": tenant_id,
        "plan": plan,
        "requests_used": current,
        "requests_limit": limit,
        "remaining": max(0, limit - current),
        "window_resets_in": retry_after,
    }
