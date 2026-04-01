"""
ASYNC JOB SYSTEM — v5
======================
HIGH FIX: list_jobs() now uses a Redis Set per tenant instead of
keys("job:*") which was an O(N) full keyspace scan that freezes Redis.

Per-tenant Set: tenant:jobs:{tenant_id}
  - SADD on create
  - SREM on delete (optional, jobs expire via TTL anyway)
"""

import json
import uuid
import logging
from datetime import datetime, timezone
from enum import Enum
import redis.asyncio as redis
import os

logger = logging.getLogger(__name__)
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))

JOB_TTL = 60 * 60 * 24 * 7  # 7 days


class JobStatus(str, Enum):
    QUEUED        = "queued"
    RUNNING       = "running"
    PENDING_HUMAN = "pending_human"
    DONE          = "done"
    REJECTED      = "rejected"
    ERROR         = "error"


async def create_job(tenant_id: str, sector: str, input_data: dict) -> str:
    job_id = str(uuid.uuid4())
    job = {
        "job_id":     job_id,
        "tenant_id":  tenant_id,
        "sector":     sector,
        "input_data": input_data,
        "status":     JobStatus.QUEUED,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "result":     None,
        "error":      None,
    }
    pipe = redis_client.pipeline()
    pipe.setex(f"job:{job_id}", JOB_TTL, json.dumps(job))
    # HIGH FIX: track job IDs per tenant in a Set — O(1) lookup
    pipe.sadd(f"tenant:jobs:{tenant_id}", job_id)
    pipe.expire(f"tenant:jobs:{tenant_id}", JOB_TTL)
    await pipe.execute()
    return job_id


async def update_job(job_id: str, status: JobStatus, result: dict = None, error: str = None):
    raw = await redis_client.get(f"job:{job_id}")
    if not raw:
        return
    job = json.loads(raw)
    job["status"]     = status
    job["updated_at"] = datetime.now(timezone.utc).isoformat()
    if result is not None:
        job["result"] = result
    if error is not None:
        job["error"] = error
    await redis_client.setex(f"job:{job_id}", JOB_TTL, json.dumps(job, default=str))


async def get_job(job_id: str) -> dict | None:
    raw = await redis_client.get(f"job:{job_id}")
    return json.loads(raw) if raw else None


async def list_jobs(tenant_id: str, limit: int = 20) -> list[dict]:
    """
    HIGH FIX: uses per-tenant Set (SMEMBERS) — O(jobs_for_tenant),
    no full keyspace scan.
    """
    job_ids = await redis_client.smembers(f"tenant:jobs:{tenant_id}")
    jobs = []
    for jid in job_ids:
        raw = await redis_client.get(f"job:{jid.decode() if isinstance(jid, bytes) else jid}")
        if raw:
            jobs.append(json.loads(raw))
    jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jobs[:limit]
