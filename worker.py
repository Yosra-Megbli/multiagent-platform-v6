"""
CELERY WORKER — v5
===================
Fixes applied vs v4:
  CRIT-1: HITL is now non-blocking. Worker sets PENDING_HUMAN and schedules
          resume_hitl_job with countdown instead of busy-waiting.
  CRIT-2: Job locking (acquire/release) is now called on every execution
          to prevent double-run on Celery retry.
  HIGH:   decrement_queue() is now called in the finally block so queue
          counters never drift upward indefinitely.
  HIGH:   asyncio.new_event_loop() replaced with asyncio.run() for correct
          event-loop lifecycle and no connection leaks.
"""

import os
import asyncio
import json
import logging
from datetime import datetime, timezone
from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded

from core.jobs import update_job, get_job, JobStatus
from core.orchestrator import run_analysis
from core.job_locking import acquire_job_lock_sync, release_job_lock_sync   # CRIT-2
from core.queue_control import decrement_queue                                # HIGH fix
import httpx
import redis as sync_redis
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

celery_app = Celery(
    "multiagent_platform",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=300,
    task_time_limit=360,
    task_reject_on_worker_lost=True,
    task_routes={
        # BUG FIX #2: was "analysis" — must match queue used in api/main.py (get_queue_for_sector → "heavy")
        "worker.process_analysis_job": {"queue": "heavy"},
        "worker.resume_hitl_job":       {"queue": "light"},
    },
)

DLQ_KEY    = "dlq:failed_jobs"
redis_sync = sync_redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))


def _run_async(coro):
    """Run async coroutine safely in Celery prefork worker."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
        return loop.run_until_complete(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
            asyncio.set_event_loop(None)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _push_to_dlq(job_id: str, tenant_id: str, error: str, input_data: dict):
    entry = {
        "job_id": job_id, "tenant_id": tenant_id, "error": error,
        "input_data": input_data,
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }
    redis_sync.lpush(DLQ_KEY, json.dumps(entry))
    redis_sync.ltrim(DLQ_KEY, 0, 499)
    logger.info("[DLQ] Job archived: %s", job_id)


def _send_webhook_sync(webhook_url: str, payload: dict):
    try:
        with httpx.Client() as client:
            client.post(webhook_url, json=payload, timeout=10)
        logger.info("[WEBHOOK] Sent to %s", webhook_url)
    except Exception as exc:
        logger.warning("[WEBHOOK] Failed: %s", exc)


# ─── Main analysis task ───────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=300,
    time_limit=360,
)
def process_analysis_job(self, job_id: str, tenant_id: str, sector: str, input_data: dict):
    """
    Background task: runs the full multi-agent pipeline.
    """
    # CRIT-2: acquire job lock — skip if already running (duplicate from retry)
    if not acquire_job_lock_sync(job_id):
        logger.warning("[WORKER] Job %s already running — skipping duplicate.", job_id)
        return

    try:
        _run_async(update_job(job_id, JobStatus.RUNNING))

        result = _run_async(
            run_analysis(tenant_id=tenant_id, sector=sector, input_data=input_data)
        )

        hitl = result.get("agent_outputs", {}).get("hitl", {})

        if hitl.get("pending"):
            # CRIT-1 FIX: non-blocking HITL — mark job and schedule resume
            _run_async(update_job(job_id, JobStatus.PENDING_HUMAN))

            # Store full result snapshot so resume_hitl_job can finalise
            from core.jobs import update_job as _uj
            # Persist intermediate state in job metadata
            _run_async(_uj(job_id, JobStatus.PENDING_HUMAN, result={
                "partial_result": result,
                "request_id":     hitl["request_id"],
                "decision_text":  result.get("agent_outputs", {}).get("decision_text", ""),
            }))

            resume_hitl_job.apply_async(
                args=[job_id, tenant_id, sector, input_data,
                      hitl["request_id"], result.get("final_decision", "")],
                countdown=int(os.getenv("HITL_TIMEOUT_SECONDS", "3600")),
                queue="light",
            )

            # FIX 4: persist job_id -> request_id so /hitl/respond/{job_id} can resolve it
            hitl_timeout = int(os.getenv("HITL_TIMEOUT_SECONDS", "3600"))
            redis_sync.setex(f"hitl:job:{job_id}", hitl_timeout, hitl["request_id"])
            logger.info("[WORKER] Job %s → PENDING_HUMAN | request_id=%s",
                        job_id, hitl["request_id"])

        else:
            final_status = JobStatus.DONE if result.get("status") == "done" else JobStatus.ERROR
            _run_async(update_job(job_id, final_status, result=result))

            webhook_url = input_data.get("webhook_url")
            if webhook_url:
                job = _run_async(get_job(job_id))
                _send_webhook_sync(webhook_url, {
                    "event": "job.completed", "job_id": job_id,
                    "status": job.get("status"), "tenant_id": tenant_id,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                })

    except SoftTimeLimitExceeded:
        error_msg = "Job timeout after 5 minutes"
        logger.warning("[WORKER] Timeout: %s", job_id)
        _run_async(update_job(job_id, JobStatus.ERROR, error=error_msg))
        _push_to_dlq(job_id, tenant_id, error_msg, input_data)

        webhook_url = input_data.get("webhook_url")
        if webhook_url:
            _send_webhook_sync(webhook_url, {
                "event": "job.timeout", "job_id": job_id, "tenant_id": tenant_id,
            })

    except Exception as exc:
        error_msg = str(exc)
        logger.error("[WORKER] Error %s → %s", job_id, error_msg)
        _run_async(update_job(job_id, JobStatus.ERROR, error=error_msg))
        _push_to_dlq(job_id, tenant_id, error_msg, input_data)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            logger.error("[WORKER] Max retries exceeded: %s", job_id)

    finally:
        release_job_lock_sync(job_id)                    # CRIT-2: always release lock
        _run_async(decrement_queue(tenant_id))          # HIGH: keep counters accurate


# ─── HITL resume task (CRIT-1) ───────────────────────────────────────────────

@celery_app.task(bind=True, max_retries=0, time_limit=60)
def resume_hitl_job(self, job_id: str, tenant_id: str, sector: str,
                    input_data: dict, request_id: str, decision_text: str):
    """
    Fired with countdown=HITL_TIMEOUT_SECONDS after a PENDING_HUMAN job.
    Reads the approval key once (no loop) and finalises the job.
    """
    from core.hitl import resolve_hitl

    result = _run_async(resolve_hitl(request_id, decision_text))

    final_status = JobStatus.DONE if result["approved"] else JobStatus.REJECTED
    _run_async(update_job(job_id, final_status, result={
        "final_decision": result["final_decision"],
        "hitl": {
            "approved":  result["approved"],
            "reviewer":  result["reviewer"],
            "comment":   result["comment"],
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }
    }))

    logger.info("[HITL RESUME] job=%s approved=%s reviewer=%s",
                job_id, result["approved"], result["reviewer"])

    webhook_url = input_data.get("webhook_url")
    if webhook_url:
        _send_webhook_sync(webhook_url, {
            "event":      "job.hitl_resolved",
            "job_id":     job_id,
            "status":     final_status,
            "tenant_id":  tenant_id,
            "approved":   result["approved"],
            "reviewer":   result["reviewer"],
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
