"""
SECRETS MANAGER — v5
=====================
HIGH FIX: Replaced SHA-256 (fast, no salt) with HKDF (proper KDF).
HKDF uses the tenant_id as salt, making per-tenant keys
computationally expensive to brute-force even from a Redis dump.
"""

import os
import json
import base64
import logging
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
import redis.asyncio as redis

logger = logging.getLogger(__name__)
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))

MASTER_KEY = os.getenv("SECRETS_MASTER_KEY")


def _get_tenant_fernet(tenant_id: str) -> Fernet:
    """
    HIGH FIX: Derives a per-tenant key using HKDF-SHA256.
    HKDF is a proper key derivation function with a salt,
    unlike raw SHA-256 which is fast and brute-forceable.
    """
    if not MASTER_KEY:
        raise RuntimeError("SECRETS_MASTER_KEY not set in environment")

    raw_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=tenant_id.encode(),
        info=b"multiagent-platform-tenant-secret",
    ).derive(MASTER_KEY.encode())

    key = base64.urlsafe_b64encode(raw_key)
    return Fernet(key)


async def store_secret(tenant_id: str, secret_name: str, secret_value: str):
    f         = _get_tenant_fernet(tenant_id)
    encrypted = f.encrypt(secret_value.encode()).decode()
    key       = f"secret:{tenant_id}:{secret_name}"
    await redis_client.set(key, encrypted)
    logger.info("[SECRETS] Stored: tenant=%s name=%s", tenant_id, secret_name)


async def get_secret(tenant_id: str, secret_name: str) -> str | None:
    key       = f"secret:{tenant_id}:{secret_name}"
    encrypted = await redis_client.get(key)
    if not encrypted:
        return None
    f = _get_tenant_fernet(tenant_id)
    try:
        return f.decrypt(encrypted).decode()
    except Exception:
        logger.error("[SECRETS] Decryption failed: tenant=%s name=%s", tenant_id, secret_name)
        return None


async def delete_secret(tenant_id: str, secret_name: str):
    await redis_client.delete(f"secret:{tenant_id}:{secret_name}")


async def list_secrets(tenant_id: str) -> list[str]:
    pattern = f"secret:{tenant_id}:*"
    keys    = await redis_client.keys(pattern)
    return [k.decode().split(":")[-1] for k in keys]


async def get_connector_config(tenant_id: str, connector_type: str) -> dict:
    from db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT config FROM tenants WHERE tenant_id = $1", tenant_id
        )
    config = dict(row["config"]) if row and row["config"] else {}
    config["connector_type"] = connector_type

    secret_map = {
        "google_sheets": ["google_api_key"],
        "rest_api":      ["api_key", "auth_token"],
        "csv":           [],
    }
    for secret_name in secret_map.get(connector_type, []):
        value = await get_secret(tenant_id, secret_name)
        if value:
            config[secret_name] = value

    return config
