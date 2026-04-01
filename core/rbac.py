"""
RBAC — v5
==========
MEDIUM FIX: require_permission() checker now correctly declares
`tenant: dict = Depends(get_tenant)` so FastAPI injects it automatically.
The previous version had `tenant: dict` as a plain positional arg,
which FastAPI does not inject — causing a runtime TypeError.
"""

import os
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from fastapi import HTTPException, Depends
import redis.asyncio as redis

logger = logging.getLogger(__name__)
redis_client  = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
AUDIT_LOG_TTL = 60 * 60 * 24 * 90  # 90 days


class Role(str, Enum):
    ADMIN   = "admin"
    ANALYST = "analyst"
    VIEWER  = "viewer"


PERMISSIONS = {
    Role.ADMIN: {
        "analyze", "view_jobs", "view_costs", "view_dashboard",
        "manage_secrets", "reset_memory", "view_dlq", "retry_jobs",
        "manage_users", "approve_hitl", "view_audit_logs",
    },
    Role.ANALYST: {
        "analyze", "view_jobs", "view_costs", "view_dashboard",
        "approve_hitl", "retry_jobs",
    },
    Role.VIEWER: {
        "view_jobs", "view_costs", "view_dashboard",
    },
}


def require_permission(permission: str):
    """
    FastAPI dependency factory.
    MEDIUM FIX: checker now uses Depends(get_tenant) for proper injection.
    """
    # Import here to avoid circular import
    from db.database import get_tenant_by_api_key
    from fastapi.security import APIKeyHeader
    from fastapi import Request

    async def checker(request: Request):
        # Re-use the same header extraction logic
        api_key = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
        if not api_key:
            raise HTTPException(status_code=401, detail="Missing API key")
        tenant = await get_tenant_by_api_key(api_key)
        if not tenant:
            raise HTTPException(status_code=401, detail="Invalid API key")
        role    = Role(tenant.get("role", Role.VIEWER))
        allowed = PERMISSIONS.get(role, set())
        if permission not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied. Required: '{permission}'. Your role: '{role}'.",
            )
        return tenant

    return checker


def has_permission(tenant: dict, permission: str) -> bool:
    role = Role(tenant.get("role", Role.VIEWER))
    return permission in PERMISSIONS.get(role, set())


async def audit_log(
    tenant_id: str, user_id: str, action: str, resource: str,
    details: dict = None, ip_address: str = None, success: bool = True,
):
    entry = {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "tenant_id":  tenant_id,
        "user_id":    user_id,
        "action":     action,
        "resource":   resource,
        "details":    details or {},
        "ip_address": ip_address,
        "success":    success,
    }
    key = f"audit:{tenant_id}"
    await redis_client.lpush(key, json.dumps(entry))
    await redis_client.expire(key, AUDIT_LOG_TTL)
    await redis_client.ltrim(key, 0, 9999)
    logger.info("[AUDIT] %s/%s → %s on %s | success=%s",
                tenant_id, user_id, action, resource, success)


async def get_audit_logs(tenant_id: str, limit: int = 100) -> list[dict]:
    entries = await redis_client.lrange(f"audit:{tenant_id}", 0, limit - 1)
    return [json.loads(e) for e in entries]
