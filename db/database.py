"""
DATABASE — v5
==============
HIGH FIX: connection pool creation was not protected by a lock.
Two concurrent coroutines could both see _pool is None and both
call create_pool(), leaking connections.
Now guarded by asyncio.Lock().
"""

import os
import asyncio
import logging
import asyncpg
from typing import Optional

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/platform")
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

_pool:      Optional[asyncpg.Pool] = None
_pool_lock: asyncio.Lock           = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    global _pool
    # HIGH FIX: lock prevents double-create under concurrent startup
    async with _pool_lock:
        if _pool is None:
            _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
            logger.info("[DB] Connection pool created (min=2, max=10)")
    return _pool


# ─── Tenant ───────────────────────────────────────────────────────────────────

async def get_tenant_by_api_key(api_key: str) -> Optional[dict]:
    if DEMO_MODE:
        from core.fake_db import get_fake_tenant
        return get_fake_tenant(api_key)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM tenants WHERE api_key = $1 AND active = TRUE",
            api_key
        )
    if not row:
        return None
    tenant = dict(row)
    # asyncpg retourne JSONB comme string — parser en dict
    import json
    if isinstance(tenant.get("config"), str):
        try:
            tenant["config"] = json.loads(tenant["config"])
        except Exception:
            tenant["config"] = {}
    elif tenant.get("config") is None:
        tenant["config"] = {}
    return tenant


# ─── Supply Chain ─────────────────────────────────────────────────────────────

async def get_sales_history(tenant_id: str, product_id: str) -> list:
    if DEMO_MODE:
        from core.fake_db import generate_sales_history
        return generate_sales_history(product_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT sale_date as ds, SUM(quantity) as y
            FROM sales
            WHERE tenant_id = $1 AND product_id = $2
              AND sale_date >= NOW() - INTERVAL '365 days'
            GROUP BY sale_date
            ORDER BY sale_date ASC
            """,
            tenant_id, product_id
        )
    return [{"ds": str(r["ds"]), "y": float(r["y"])} for r in rows]


async def get_production_data(tenant_id: str, product_id: str) -> dict:
    if DEMO_MODE:
        from core.fake_db import generate_production_config
        return generate_production_config(product_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT daily_capacity, current_stock, packaging_stock, supplier_lead_time
            FROM production_config
            WHERE tenant_id = $1 AND product_id = $2
            """,
            tenant_id, product_id
        )
    if not row:
        raise ValueError(f"No production data for tenant={tenant_id}, product={product_id}")
    return dict(row)


async def save_decision(tenant_id: str, sector: str, decision: str, insights: dict):
    if DEMO_MODE:
        logger.info("[DEMO] save_decision skipped (in-memory mode)")
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO decisions (tenant_id, sector, decision_text, insights, created_at)
            VALUES ($1, $2, $3, $4, NOW())
            """,
            tenant_id, sector, decision, str(insights)
        )
