"""
FAKE DB — Demo mode (no PostgreSQL, no Redis needed)
Generates realistic fake data for supply_chain testing.
"""

import random
from datetime import date, timedelta


FAKE_TENANTS = {
    "demo-key-001": {
        "tenant_id": "demo",
        "sector": "supply_chain",
        "plan": "enterprise",
        "active": True,
        "config": {"connector_type": "fake"},
        "permissions": ["analyze", "view_jobs", "retry_jobs", "view_audit_logs", "manage_secrets"],
    },
    "test-key-002": {
        "tenant_id": "test",
        "sector": "supply_chain",
        "plan": "starter",
        "active": True,
        "config": {"connector_type": "fake"},
        "permissions": ["analyze", "view_jobs"],
    },
}

_jobs: dict = {}
_job_counter = 0


def get_fake_tenant(api_key: str):
    return FAKE_TENANTS.get(api_key)


def generate_sales_history(product_id: str, days: int = 365) -> list[dict]:
    """Generates realistic seasonal sales data."""
    random.seed(hash(product_id) % 1000)
    base = {"PROD-001": 1200, "PROD-002": 800, "PROD-003": 2000}.get(product_id, 1000)
    rows = []
    for i in range(days):
        d = date.today() - timedelta(days=days - i)
        # seasonal pattern: higher in summer
        season = 1 + 0.3 * abs((d.month - 6) / 6 - 0.5)
        noise = random.uniform(0.85, 1.15)
        rows.append({"ds": str(d), "y": round(base * season * noise, 0)})
    return rows


def generate_production_config(product_id: str) -> dict:
    configs = {
        "PROD-001": {"daily_capacity": 1500, "current_stock": 18000, "packaging_stock": 12000, "supplier_lead_time": 5},
        "PROD-002": {"daily_capacity": 1000, "current_stock": 8000,  "packaging_stock": 6000,  "supplier_lead_time": 7},
        "PROD-003": {"daily_capacity": 2500, "current_stock": 35000, "packaging_stock": 28000, "supplier_lead_time": 3},
    }
    return configs.get(product_id, {
        "daily_capacity": 1200, "current_stock": 15000,
        "packaging_stock": 10000, "supplier_lead_time": 5,
    })


# ─── In-memory job store ──────────────────────────────────────────────────────

def create_fake_job(tenant_id: str, sector: str, input_data: dict) -> str:
    global _job_counter
    _job_counter += 1
    job_id = f"job-{_job_counter:04d}"
    _jobs[job_id] = {
        "job_id": job_id, "tenant_id": tenant_id,
        "sector": sector, "input_data": input_data,
        "status": "queued", "result": None, "error": None,
    }
    return job_id


def get_fake_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def update_fake_job(job_id: str, status: str, result=None, error=None):
    if job_id in _jobs:
        _jobs[job_id]["status"] = status
        if result is not None:
            _jobs[job_id]["result"] = result
        if error is not None:
            _jobs[job_id]["error"] = error


def list_fake_jobs(tenant_id: str) -> list:
    return [j for j in _jobs.values() if j["tenant_id"] == tenant_id]
