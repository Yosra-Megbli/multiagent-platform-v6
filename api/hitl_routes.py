"""
HITL API Routes
================
Endpoints for human reviewers to approve or reject AI decisions.
"""

import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import redis.asyncio as redis
import os

router = APIRouter(prefix="/hitl", tags=["Human-in-the-Loop"])
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))


class ValidationResponse(BaseModel):
    reviewer: str
    comment: Optional[str] = None


@router.post("/approve/{request_id}")
async def approve_decision(request_id: str, body: ValidationResponse):
    """Human reviewer approves the AI decision."""
    key = f"hitl:approval:{request_id}"
    existing = await redis_client.get(key)

    if not existing:
        raise HTTPException(status_code=404, detail="Request not found or expired")
    if existing != b"pending":
        raise HTTPException(status_code=409, detail="Already processed")

    payload = json.dumps({
        "approved": True,
        "reviewer": body.reviewer,
        "comment": body.comment or "Approved",
    })
    await redis_client.setex(key, 3600, payload)
    return {"status": "approved", "request_id": request_id}


@router.post("/reject/{request_id}")
async def reject_decision(request_id: str, body: ValidationResponse):
    """Human reviewer rejects the AI decision."""
    key = f"hitl:approval:{request_id}"
    existing = await redis_client.get(key)

    if not existing:
        raise HTTPException(status_code=404, detail="Request not found or expired")
    if existing != b"pending":
        raise HTTPException(status_code=409, detail="Already processed")

    payload = json.dumps({
        "approved": False,
        "reviewer": body.reviewer,
        "comment": body.comment or "Rejected",
    })
    await redis_client.setex(key, 3600, payload)
    return {"status": "rejected", "request_id": request_id}


@router.get("/pending/{request_id}")
async def get_pending(request_id: str):
    """Check status of a pending HITL request."""
    key = f"hitl:approval:{request_id}"
    result = await redis_client.get(key)

    if not result:
        return {"status": "expired_or_not_found"}
    if result == b"pending":
        return {"status": "pending"}

    return {"status": "processed", **json.loads(result)}


class RespondBody(BaseModel):
    action: str          # "approve" | "reject"
    reason: Optional[str] = None


@router.post("/respond/{job_id}")
async def respond_by_job(job_id: str, body: RespondBody):
    """
    Unified HITL respond endpoint called from the dashboard.
    Looks up the request_id stored under hitl:job:{job_id} then
    writes the approval/rejection to hitl:approval:{request_id}.
    Falls back gracefully when Redis key is absent (mock/dev mode).
    """
    # Resolve request_id from job_id
    request_id_raw = await redis_client.get(f"hitl:job:{job_id}")
    request_id = request_id_raw.decode() if request_id_raw else job_id  # fallback

    key = f"hitl:approval:{request_id}"
    approved = body.action.lower() == "approve"

    payload = json.dumps({
        "approved": approved,
        "reviewer": "dashboard",
        "comment": body.reason or ("Approved via dashboard" if approved else "Rejected via dashboard"),
    })
    await redis_client.setex(key, 3600, payload)

    return {
        "status": "approved" if approved else "rejected",
        "job_id": job_id,
        "request_id": request_id,
    }
