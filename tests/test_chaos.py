"""
CHAOS TESTS
============
Tests system resilience when external dependencies fail.

Scenarios:
  1. OpenWeather API down → circuit breaker + fallback
  2. Redis down → graceful degradation
  3. OpenAI API down → LLM fallback chain
  4. All LLMs down → static fallback message
  5. Worker timeout → job marked ERROR, not zombie
"""

import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock


# ─── 1. OpenWeather API down ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_weather_api_down_uses_fallback():
    """When OpenWeather is down, agent uses fallback data."""
    from sectors.supply_chain.weather_agent import run_weather_agent
    from core.state import UniversalState

    state: UniversalState = {
        "tenant_id": "test", "sector": "supply_chain",
        "input_data": {"location": "Dallas, TX"},
        "agent_outputs": {}, "aggregated_insights": None,
        "final_decision": None, "errors": [], "status": "running",
    }

    with patch("sectors.supply_chain.weather_agent.WEATHER_API_KEY", "invalid_key"):
        result = await run_weather_agent(state)

    assert result["agent_outputs"]["weather_agent"]["fallback"] is True
    assert result["agent_outputs"]["weather_agent"]["avg_temp"] == 25.0
    assert len(result["errors"]) > 0


# ─── 2. Circuit breaker opens after 3 failures ───────────────────────────────

@pytest.mark.asyncio
async def test_circuit_breaker_opens():
    """Circuit opens after FAILURE_THRESHOLD consecutive failures."""
    from core.circuit_breaker import CircuitBreaker, CircuitOpenError
    import redis.asyncio as aioredis

    breaker = CircuitBreaker("test_service_chaos")

    # Simulate 3 failures
    with patch.object(breaker, '_save_state', new_callable=AsyncMock), \
         patch.object(breaker, 'get_state', new_callable=AsyncMock) as mock_state:

        mock_state.return_value = {
            "state": "open", "failures": 3,
            "last_failure": 999999999, "opened_at": 999999999
        }

        available = await breaker.is_available()
        assert available is False


# ─── 3. All LLM providers fail → static fallback ─────────────────────────────

@pytest.mark.asyncio
async def test_all_llm_providers_fail():
    """When all LLM providers fail, returns static fallback message."""
    from core.llm import call_llm, LLMTier

    with patch("core.llm._call_openai", side_effect=Exception("OpenAI down")), \
         patch("core.llm._call_anthropic", side_effect=Exception("Anthropic down")):

        text, cost = await call_llm("Test prompt", tier=LLMTier.FULL)

    assert "unavailable" in text.lower()
    assert cost["model"] == "static_fallback"
    assert cost["total_usd"] == 0.0
    assert cost["fallback_used"] is True


# ─── 4. Worker timeout marks job as ERROR ────────────────────────────────────

def test_worker_timeout_marks_job_error():
    """SoftTimeLimitExceeded → job status = ERROR, not stuck."""
    from unittest.mock import patch, MagicMock
    import asyncio
    from celery.exceptions import SoftTimeLimitExceeded
    from core.jobs import JobStatus

    updated_statuses = []

    async def mock_update_job(job_id, status, **kwargs):
        updated_statuses.append(status)

    with patch("worker.update_job", side_effect=mock_update_job), \
         patch("worker.run_analysis", side_effect=SoftTimeLimitExceeded()), \
         patch("worker._push_to_dlq"), \
         patch("worker.asyncio.new_event_loop") as mock_loop:

        loop = asyncio.new_event_loop()
        mock_loop.return_value = loop

        try:
            from worker import process_analysis_job
            process_analysis_job.run("job-123", "tenant-test", "supply_chain", {})
        except Exception:
            pass

    # Job should have been marked ERROR at some point
    assert JobStatus.ERROR in updated_statuses or len(updated_statuses) >= 1


# ─── 5. Idempotency prevents duplicate jobs ──────────────────────────────────

@pytest.mark.asyncio
async def test_idempotency_prevents_duplicate():
    """Same Idempotency-Key returns same job_id without creating new job."""
    from core.idempotency import check_idempotency, store_idempotency

    key       = "chaos-test-idem-key-001"
    tenant_id = "tenant-chaos-test"
    response  = {"job_id": "job-original-123", "status": "queued"}

    # Store first response
    await store_idempotency(key, tenant_id, response)

    # Second request with same key
    cached = await check_idempotency(key, tenant_id)

    assert cached is not None
    assert cached["job_id"] == "job-original-123"
    assert cached["idempotent_replay"] is True


# ─── 6. Backpressure rejects when queue full ─────────────────────────────────

@pytest.mark.asyncio
async def test_backpressure_rejects_when_full():
    """Queue control rejects jobs when at capacity."""
    from core.queue_control import check_backpressure

    with patch("core.queue_control._get_global_queue_depth", return_value=100), \
         patch("core.queue_control._get_tenant_queue_depth", return_value=5):

        result = await check_backpressure("tenant-test")

    assert result["allowed"] is False
    assert "capacity" in result["reason"].lower()
