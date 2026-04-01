"""
TOOL-CALLING SYSTEM — v6
=========================
Transforme chaque agent en "tool" que le decision_agent peut appeler dynamiquement.

Au lieu d'un pipeline fixe :
    weather → sales → production → decision

Le decision_agent analyse la situation et CHOISIT quels tools appeler :
    - Si chaleur extrême → appelle weather_tool + sales_tool
    - Si stock critique  → appelle production_tool directement
    - Si situation normale → appelle tous les tools

C'est la différence entre un pipeline statique et un agent autonome réel.

Architecture :
    SupplyChainToolkit   → registre de tous les tools disponibles
    run_tool()           → exécute un tool par son nom
    ToolResult           → résultat standardisé
"""

import logging
import asyncio
from typing import Any
from copy import deepcopy

from core.state import UniversalState

logger = logging.getLogger(__name__)


# ─── Tool Registry ────────────────────────────────────────────────────────────

SUPPLY_CHAIN_TOOLS = [
    {
        "name": "weather_tool",
        "description": (
            "Fetches real-time weather forecast for a given location. "
            "Returns: avg_temp, max_temp, rain_days, heat_wave (bool). "
            "Use when: weather conditions might affect demand or logistics."
        ),
        "required_input": ["location"],
    },
    {
        "name": "sales_tool",
        "description": (
            "Forecasts sales demand for the next 30 days using historical data + weather multiplier. "
            "Returns: adjusted_30_days, weather_multiplier, base_forecast. "
            "Use when: demand forecast is needed for planning."
        ),
        "required_input": ["product_id", "tenant_id"],
    },
    {
        "name": "production_tool",
        "description": (
            "Checks current stock levels, production capacity, and packaging inventory. "
            "Returns: days_of_stock, daily_capacity, can_meet_demand, reorder_needed. "
            "Use when: supply-side constraints need to be evaluated."
        ),
        "required_input": ["product_id", "tenant_id"],
    },
    {
        "name": "rag_tool",
        "description": (
            "Retrieves similar past decisions from memory using vector similarity. "
            "Returns: historical context with past decisions and their outcomes. "
            "Use when: a similar situation occurred before and historical context is valuable."
        ),
        "required_input": ["query", "tenant_id", "sector"],
    },
]


def get_tools_description() -> str:
    """Génère la description des tools pour le prompt LLM."""
    lines = ["Available tools you can call:"]
    for tool in SUPPLY_CHAIN_TOOLS:
        lines.append(f"\n- {tool['name']}: {tool['description']}")
    return "\n".join(lines)


# ─── Tool Execution ───────────────────────────────────────────────────────────

async def run_tool(tool_name: str, state: UniversalState) -> dict[str, Any]:
    """
    Exécute un tool par son nom et retourne son résultat.
    Chaque tool est l'agent correspondant, appelé de façon isolée.
    """
    logger.info("[TOOL-CALL] Executing: %s", tool_name)

    # On crée une copie isolée du state pour chaque tool
    tool_state = deepcopy(dict(state))
    tool_state["agent_outputs"] = {}
    tool_state["errors"] = []

    try:
        if tool_name == "weather_tool":
            from sectors.supply_chain.weather_agent import run_weather_agent
            result_state = await run_weather_agent(tool_state)
            return {
                "tool": tool_name,
                "status": "success",
                "output": result_state["agent_outputs"].get("weather_agent", {}),
            }

        elif tool_name == "sales_tool":
            from sectors.supply_chain.sales_agent import run_sales_agent
            result_state = await run_sales_agent(tool_state)
            return {
                "tool": tool_name,
                "status": "success",
                "output": result_state["agent_outputs"].get("sales_agent", {}),
            }

        elif tool_name == "production_tool":
            from sectors.supply_chain.production_agent import run_production_agent
            result_state = await run_production_agent(tool_state)
            return {
                "tool": tool_name,
                "status": "success",
                "output": result_state["agent_outputs"].get("production_agent", {}),
            }

        elif tool_name == "rag_tool":
            from core.rag_memory import build_rag_context
            product_id = state["input_data"].get("product_id", "")
            location   = state["input_data"].get("location", "")
            query = f"{location} {product_id} supply chain decision"
            context = await build_rag_context(
                tenant_id=state["tenant_id"],
                sector=state["sector"],
                current_situation=query,
                product_id=product_id,
            )
            return {
                "tool": tool_name,
                "status": "success",
                "output": {"rag_context": context},
            }

        else:
            return {"tool": tool_name, "status": "error", "output": {}, "error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        logger.warning("[TOOL-CALL] %s failed: %s", tool_name, str(e))
        return {"tool": tool_name, "status": "error", "output": {}, "error": str(e)}


async def run_tools_parallel(tool_names: list[str], state: UniversalState) -> list[dict]:
    """Exécute plusieurs tools en parallèle."""
    tasks = [run_tool(name, state) for name in tool_names]
    return await asyncio.gather(*tasks)
