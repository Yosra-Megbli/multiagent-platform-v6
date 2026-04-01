"""
DYNAMIC ORCHESTRATOR — v6
==========================
v6 changes:
  - supply_chain pipeline redesigned for tool-calling architecture:
      Phase 1 (parallel): weather_agent + sales_agent + production_agent
      Phase 2:            aggregator_agent (rules-based alerts)
      Phase 3:            decision_agent (tool-calling + RAG)
  - Other sectors: generic pipeline (parallel → aggregator → decision)
  - asyncio.Lock() retained to prevent concurrent build race conditions.
"""

import asyncio
import importlib
import logging
from copy import deepcopy
from typing import Callable
from langgraph.graph import StateGraph, END

from core.state import UniversalState
from sectors.registry import get_sector_agents

logger      = logging.getLogger(__name__)
_cache_lock = asyncio.Lock()


def load_agent_fn(sector: str, agent_name: str) -> Callable:
    module_path = f"sectors.{sector}.{agent_name}"
    fn_name     = f"run_{agent_name}"
    try:
        module = importlib.import_module(module_path)
        fn     = getattr(module, fn_name)
        return fn
    except ModuleNotFoundError:
        raise ImportError(f"Agent module not found: {module_path}")
    except AttributeError:
        raise ImportError(f"Function '{fn_name}' not found in {module_path}")


def make_parallel_node(sector: str, agent_names: list[str]) -> Callable:
    """Runs weather + sales + production in parallel (before aggregator)."""
    DATA_AGENTS = ["weather_agent", "sales_agent", "production_agent"]
    parallel_agents = [a for a in agent_names if a in DATA_AGENTS]

    # If no data agents listed explicitly, run all except aggregator/decision
    if not parallel_agents:
        parallel_agents = [
            a for a in agent_names
            if a not in ("aggregator_agent", "decision_agent")
        ]

    if not parallel_agents:
        # No parallel agents needed — return identity node
        async def noop(state: UniversalState) -> UniversalState:
            return state
        return noop

    agent_fns = {name: load_agent_fn(sector, name) for name in parallel_agents}

    async def run_parallel(state: UniversalState) -> UniversalState:
        tasks   = [fn(deepcopy(dict(state))) for fn in agent_fns.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for name, result in zip(agent_fns.keys(), results):
            if isinstance(result, Exception):
                state["errors"].append(f"{name} failed: {str(result)}")
            elif isinstance(result, dict):
                state["agent_outputs"].update(result.get("agent_outputs", {}))
                state["errors"].extend(result.get("errors", []))

        return state

    return run_parallel


def make_aggregator(sector: str) -> Callable:
    try:
        module = importlib.import_module(f"sectors.{sector}.aggregator_agent")
        return getattr(module, "aggregate")
    except (ModuleNotFoundError, AttributeError):
        def generic_aggregate(state: UniversalState) -> UniversalState:
            state["aggregated_insights"] = {
                "sector":     sector,
                "agents_ran": list(state["agent_outputs"].keys()),
                "errors":     state["errors"],
            }
            return state
        return generic_aggregate


_orchestrator_cache: dict = {}


async def build_orchestrator(sector: str):
    """
    Builds the LangGraph workflow for a sector.
    supply_chain: parallel(weather+sales+production) → aggregator → decision
    other sectors: parallel(all except decision) → aggregator → decision
    Protected by asyncio.Lock() to prevent concurrent builds.
    """
    if sector in _orchestrator_cache:
        return _orchestrator_cache[sector]

    async with _cache_lock:
        if sector in _orchestrator_cache:
            return _orchestrator_cache[sector]

        agent_names = get_sector_agents(sector)
        workflow    = StateGraph(UniversalState)

        # For supply_chain: data agents run in parallel first
        # (decision_agent will also call them via tool-calling if needed)
        DATA_AGENTS = ["weather_agent", "sales_agent", "production_agent"]
        supply_data = DATA_AGENTS.copy()  # BUG FIX #9: was [a for a in DATA_AGENTS if True]

        if sector == "supply_chain":
            # Phase 1: parallel data collection
            parallel_node = make_parallel_node(sector, supply_data)
            workflow.add_node("parallel_agents", parallel_node)

            # Phase 2: rules-based aggregation
            aggregator = make_aggregator(sector)
            workflow.add_node("aggregator_agent", aggregator)

            # Phase 3: tool-calling decision agent
            decision_fn = load_agent_fn(sector, "decision_agent")
            workflow.add_node("decision_agent", decision_fn)

            workflow.set_entry_point("parallel_agents")
            workflow.add_edge("parallel_agents", "aggregator_agent")
            workflow.add_edge("aggregator_agent", "decision_agent")
            workflow.add_edge("decision_agent", END)

        else:
            # Generic pipeline for other sectors
            parallel_node = make_parallel_node(sector, agent_names)
            workflow.add_node("parallel_agents", parallel_node)

            aggregator = make_aggregator(sector)
            workflow.add_node("aggregator", aggregator)

            if "decision_agent" in agent_names:
                decision_fn = load_agent_fn(sector, "decision_agent")
                workflow.add_node("decision_agent", decision_fn)
                workflow.set_entry_point("parallel_agents")
                workflow.add_edge("parallel_agents", "aggregator")
                workflow.add_edge("aggregator", "decision_agent")
                workflow.add_edge("decision_agent", END)
            else:
                workflow.set_entry_point("parallel_agents")
                workflow.add_edge("parallel_agents", "aggregator")
                workflow.add_edge("aggregator", END)

        compiled = workflow.compile()
        _orchestrator_cache[sector] = compiled
        logger.info("[ORCHESTRATOR] Built graph for sector=%s agents=%s", sector, agent_names)
        return compiled


async def run_analysis(tenant_id: str, sector: str, input_data: dict) -> dict:
    orchestrator = await build_orchestrator(sector)

    initial_state: UniversalState = {
        "tenant_id":           tenant_id,
        "sector":              sector,
        "input_data":          input_data,
        "agent_outputs":       {},
        "aggregated_insights": None,
        "final_decision":      None,
        "errors":              [],
        "status":              "running",
    }

    return await orchestrator.ainvoke(initial_state)
