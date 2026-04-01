"""
WORKER DEDUPLICATION & JOB LOCKING
=====================================
Prevents a job from being executed twice after a worker crash.

Problem:
  Worker crashes mid-job → Celery retries → job runs twice
  = double billing, duplicate decisions, corrupted state

Solution:
  Before executing: acquire distributed lock (Redis)
  After completion: release lock
  On retry: lock already held → skip execution

Uses Redis SET NX (atomic) for guaranteed single execution.
"""

import os
import asyncio
import redis.asyncio as aioredis
import redis as sync_redis

LOCK_TTL = int(os.getenv("JOB_LOCK_TTL", "400"))  # slightly > max job timeout

_async_redis  = aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
_sync_redis   = sync_redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))


class JobAlreadyRunningError(Exception):
    """Raised when a job lock cannot be acquired (job already running)."""
    pass


async def acquire_job_lock(job_id: str) -> bool:
    """
    Acquires exclusive lock for a job (async version).
    Returns True if lock acquired, False if job already running.
    """
    key = f"job_lock:{job_id}"
    result = await _async_redis.set(key, "locked", nx=True, ex=LOCK_TTL)
    return result is not None


async def release_job_lock(job_id: str):
    """Releases job lock (async version)."""
    await _async_redis.delete(f"job_lock:{job_id}")


def acquire_job_lock_sync(job_id: str) -> bool:
    """Sync version for Celery workers."""
    key = f"job_lock:{job_id}"
    result = _sync_redis.set(key, "locked", nx=True, ex=LOCK_TTL)
    return result is not None


def release_job_lock_sync(job_id: str):
    """Sync release for Celery workers."""
    _sync_redis.delete(f"job_lock:{job_id}")


def is_job_locked_sync(job_id: str) -> bool:
    """Checks if a job lock exists."""
    return bool(_sync_redis.exists(f"job_lock:{job_id}"))
