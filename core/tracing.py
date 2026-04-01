"""
OBSERVABILITY — LangSmith Tracing
==================================
Traces every agent execution: cost, latency, inputs, outputs.
Set LANGCHAIN_TRACING_V2=true in .env to enable.
Falls back silently if LangSmith is not configured.
"""

import os
from functools import wraps
from typing import Callable
import time

# LangSmith auto-activates via env variables
# LANGCHAIN_TRACING_V2=true
# LANGCHAIN_API_KEY=ls-...
# LANGCHAIN_PROJECT=multiagent-platform

TRACING_ENABLED = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"


def trace_agent(agent_name: str, sector: str):
    """
    Decorator that adds tracing to any agent function.
    Records: latency, tenant_id, sector, errors, token usage.
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(state, *args, **kwargs):
            start = time.perf_counter()
            tenant_id = state.get("tenant_id", "unknown")

            try:
                result = await fn(state, *args, **kwargs)
                latency = round((time.perf_counter() - start) * 1000, 2)

                # Log to console (always)
                print(f"[TRACE] {sector}/{agent_name} | tenant={tenant_id} | {latency}ms | errors={result.get('errors', [])}")

                # LangSmith metadata (if enabled)
                if TRACING_ENABLED:
                    try:
                        from langsmith import Client
                        client = Client()
                        client.create_run(
                            name=f"{sector}/{agent_name}",
                            run_type="chain",
                            inputs={"tenant_id": tenant_id, "sector": sector},
                            outputs={"agent_output": result.get("agent_outputs", {}).get(agent_name)},
                            extra={"latency_ms": latency},
                        )
                    except Exception:
                        pass  # Never block execution for tracing

                return result

            except Exception as e:
                latency = round((time.perf_counter() - start) * 1000, 2)
                print(f"[TRACE ERROR] {sector}/{agent_name} | tenant={tenant_id} | {latency}ms | {str(e)}")
                raise

        return wrapper
    return decorator
