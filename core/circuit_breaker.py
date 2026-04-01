"""
CIRCUIT BREAKER
================
Protects against cascade failures from external API outages.
When an external service fails repeatedly, the circuit opens
and requests fall back immediately instead of waiting to timeout.

States:
  CLOSED   → normal operation, requests pass through
  OPEN     → service is down, requests fail immediately with fallback
  HALF_OPEN → testing if service recovered (1 request allowed)

Usage:
  breaker = get_circuit_breaker("openweather")
  async with breaker:
      response = await fetch_weather(location)
"""

import os
import json
import time
import redis.asyncio as redis
from enum import Enum
from contextlib import asynccontextmanager

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))

FAILURE_THRESHOLD = int(os.getenv("CIRCUIT_FAILURE_THRESHOLD", "3"))
RECOVERY_TIMEOUT  = int(os.getenv("CIRCUIT_RECOVERY_TIMEOUT",  "120"))  # 2 minutes


class CircuitState(str, Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.key = f"circuit:{service_name}"

    async def get_state(self) -> dict:
        raw = await redis_client.get(self.key)
        if not raw:
            return {
                "state": CircuitState.CLOSED,
                "failures": 0,
                "last_failure": None,
                "opened_at": None,
            }
        return json.loads(raw)

    async def _save_state(self, state: dict):
        await redis_client.setex(self.key, 86400, json.dumps(state))

    async def record_success(self):
        data = await self.get_state()
        if data["state"] in (CircuitState.OPEN, CircuitState.HALF_OPEN):
            print(f"[CIRCUIT] {self.service_name} → CLOSED (recovered)")
        data["state"]    = CircuitState.CLOSED
        data["failures"] = 0
        await self._save_state(data)

    async def record_failure(self):
        data = await self.get_state()
        data["failures"]     += 1
        data["last_failure"]  = time.time()

        if data["failures"] >= FAILURE_THRESHOLD:
            data["state"]     = CircuitState.OPEN
            data["opened_at"] = time.time()
            print(f"[CIRCUIT] {self.service_name} → OPEN after {data['failures']} failures")
        await self._save_state(data)

    async def is_available(self) -> bool:
        data = await self.get_state()

        if data["state"] == CircuitState.CLOSED:
            return True

        if data["state"] == CircuitState.OPEN:
            # Check if recovery timeout has passed
            opened_at = data.get("opened_at", 0)
            if time.time() - opened_at > RECOVERY_TIMEOUT:
                data["state"] = CircuitState.HALF_OPEN
                await self._save_state(data)
                print(f"[CIRCUIT] {self.service_name} → HALF_OPEN (testing recovery)")
                return True
            return False

        if data["state"] == CircuitState.HALF_OPEN:
            return True  # Allow one request to test

        return True

    @asynccontextmanager
    async def protect(self):
        """
        Context manager that records success/failure automatically.

        Usage:
            async with breaker.protect():
                result = await external_api_call()
        """
        available = await self.is_available()
        if not available:
            raise CircuitOpenError(f"Circuit OPEN for {self.service_name}. Service unavailable.")

        try:
            yield
            await self.record_success()
        except Exception as e:
            await self.record_failure()
            raise


class CircuitOpenError(Exception):
    """Raised when circuit is open and request is blocked."""
    pass


# ─── Registry ─────────────────────────────────────────────────────────────────

_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(service_name: str) -> CircuitBreaker:
    """Returns or creates a circuit breaker for a service."""
    if service_name not in _breakers:
        _breakers[service_name] = CircuitBreaker(service_name)
    return _breakers[service_name]
