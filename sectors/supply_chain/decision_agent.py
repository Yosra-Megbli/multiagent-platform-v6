"""
Decision Agent — v6 (Tool-Calling + RAG)
==========================================
Améliorations v6 :
  TOOL-CALLING : le decision_agent analyse la situation et choisit
                 dynamiquement quels tools appeler (weather, sales,
                 production, rag) au lieu d'un pipeline fixe.
  RAG          : récupère les décisions passées similaires via
                 sentence-transformers + pgvector (100% gratuit).

Flux :
  1. Premier appel LLM → décide quels tools sont nécessaires
  2. Exécution parallèle des tools choisis
  3. Deuxième appel LLM → génère la décision finale enrichie du contexte RAG
"""

import json
import logging

from core.state import UniversalState
from core.llm import call_llm, LLMTier
from core.hitl import hitl_checkpoint
from core.memory import get_memory_summary, save_decision_memory
from core.tracing import trace_agent
from core.tools import (
    get_tools_description,
    run_tools_parallel,
    SUPPLY_CHAIN_TOOLS,
)

logger = logging.getLogger(__name__)

AVAILABLE_TOOL_NAMES = [t["name"] for t in SUPPLY_CHAIN_TOOLS]


async def _select_tools(state: UniversalState) -> list[str]:
    """
    Premier appel LLM : analyse la situation et retourne la liste
    des tools à appeler. Répond en JSON uniquement.
    """
    location   = state["input_data"].get("location", "Unknown")
    product_id = state["input_data"].get("product_id", "Unknown")

    # Contexte déjà disponible depuis les agents parallèles (si présents)
    existing = state.get("agent_outputs", {})
    existing_summary = ""
    if existing:
        existing_summary = f"Already available data: {json.dumps({k: v for k, v in existing.items() if k not in ['decision_cost', 'decision_text', 'hitl']}, default=str)[:400]}"

    prompt = f"""You are an AI orchestrator for supply chain analysis.

Situation:
- Location: {location}
- Product: {product_id}
- {existing_summary}

{get_tools_description()}

Your task: decide which tools to call to make the best supply chain decision.
- Always call rag_tool to check historical context.
- Call weather_tool if location-based demand matters.
- Call sales_tool if demand forecasting is needed.
- Call production_tool if stock/capacity evaluation is needed.
- Skip tools if their data is already available above.

Respond ONLY with a valid JSON object, no explanation:
{{"tools_to_call": ["tool1", "tool2", ...]}}

Available tool names: {AVAILABLE_TOOL_NAMES}"""

    try:
        response, _ = await call_llm(prompt=prompt, tier=LLMTier.MINI, max_tokens=100, temperature=0.0)
        # Parse JSON response
        response = response.strip()
        # BUG FIX #10: robust JSON extraction — handles markdown fences and extra text
        import re as _re
        json_match = _re.search(r'\{[^{}]*\}', response, _re.DOTALL)
        if json_match:
            response = json_match.group()
        elif "```" in response:
            response = response.split("```")[1].replace("json", "").strip()
        data = json.loads(response)
        tools = data.get("tools_to_call", AVAILABLE_TOOL_NAMES)
        # Validate tool names
        valid_tools = [t for t in tools if t in AVAILABLE_TOOL_NAMES]
        if not valid_tools:
            valid_tools = AVAILABLE_TOOL_NAMES
        logger.info("[DECISION] Tools selected: %s", valid_tools)
        return valid_tools
    except Exception as e:
        logger.warning("[DECISION] Tool selection failed (%s), using all tools.", str(e))
        return AVAILABLE_TOOL_NAMES


@trace_agent(agent_name="decision_agent", sector="supply_chain")
async def run_decision_agent(state: UniversalState) -> UniversalState:
    tenant_id  = state["tenant_id"]
    product_id = state["input_data"].get("product_id", "DEFAULT")
    location   = state["input_data"].get("location", "Unknown")

    # ── STEP 1 : Tool selection (LLM decides which tools to call) ──────────────
    tools_to_call = await _select_tools(state)
    state["agent_outputs"]["tools_selected"] = tools_to_call

    # ── STEP 2 : Execute selected tools in parallel ────────────────────────────
    tool_results = await run_tools_parallel(tools_to_call, state)

    # Merge tool outputs into agent_outputs
    rag_context = "No historical context available."
    for result in tool_results:
        if result["status"] == "success":
            tool_name = result["tool"]
            output    = result["output"]
            if tool_name == "rag_tool":
                rag_context = output.get("rag_context", rag_context)
            elif tool_name == "weather_tool":
                state["agent_outputs"]["weather_agent"] = output
            elif tool_name == "sales_tool":
                state["agent_outputs"]["sales_agent"] = output
            elif tool_name == "production_tool":
                state["agent_outputs"]["production_agent"] = output
        else:
            state["errors"].append(f"Tool {result['tool']}: {result.get('error', 'unknown error')}")

    state["agent_outputs"]["rag_context"] = rag_context

    # ── STEP 3 : Retrieve existing memory summary ──────────────────────────────
    memory = await get_memory_summary(tenant_id, "supply_chain", product_id)

    # ── STEP 4 : Build enriched prompt with RAG + tool results ────────────────
    insights   = state.get("aggregated_insights", {}) or {}
    weather    = state["agent_outputs"].get("weather_agent", {})
    sales      = state["agent_outputs"].get("sales_agent", {})
    production = state["agent_outputs"].get("production_agent", {})

    prompt = f"""You are a supply chain optimization expert with access to real-time data and historical intelligence.

=== CURRENT SITUATION ===
Location  : {location}
Product   : {product_id}
Urgency   : {insights.get('urgency', 'UNKNOWN')}
Alerts    : {', '.join(insights.get('alerts', [])) or 'None'}

=== TOOLS CALLED : {tools_to_call} ===
WEATHER   : max {weather.get('max_temp', 'N/A')}°C, {weather.get('rain_days', 'N/A')} rain days, heat_wave={weather.get('heat_wave', False)}
DEMAND    : {sales.get('adjusted_30_days', 'N/A')} units/30 days (multiplier: {sales.get('weather_multiplier', 1.0)}x)
PRODUCTION: {production.get('days_of_stock', 'N/A')} days of stock, capacity {production.get('daily_capacity', 'N/A')}/day

=== RAG — HISTORICAL INTELLIGENCE ===
{rag_context}

=== SHORT-TERM MEMORY ===
{memory.get('note', 'No recent history.')}

Based on ALL available data (real-time + historical), provide:
1. Situation summary (2 sentences, mention if similar past decisions exist)
2. Immediate actions (numbered, specific quantities and dates)
3. Risk if no action (estimated revenue impact)
4. Confidence level: HIGH / MEDIUM / LOW
"""

    # ── STEP 5 : Generate final decision ──────────────────────────────────────
    try:
        decision_text, cost_info = await call_llm(
            prompt=prompt, tier=LLMTier.FULL, max_tokens=600, temperature=0.2,
        )
        state["agent_outputs"]["decision_cost"]    = cost_info
        state["agent_outputs"]["decision_text"]    = decision_text
        state["agent_outputs"]["tools_called"]     = tools_to_call

    except Exception as e:
        state["errors"].append(f"DecisionAgent LLM: {str(e)}")
        state["final_decision"] = "Error generating recommendation."
        state["status"] = "error"
        return state

    # ── STEP 6 : HITL checkpoint ───────────────────────────────────────────────
    hitl_result = await hitl_checkpoint(
        tenant_id=tenant_id, sector="supply_chain",
        decision=decision_text, insights=insights,
    )

    state["agent_outputs"]["hitl"] = hitl_result

    if hitl_result.get("pending"):
        state["status"]         = "pending_human"
        state["final_decision"] = None
    else:
        state["final_decision"] = hitl_result["final_decision"]
        state["status"]         = "done" if hitl_result["approved"] else "rejected"

        # ── STEP 7 : Store decision in RAG memory for future use ───────────────
        if hitl_result["approved"] and insights:
            try:
                from core.rag_memory import store_decision_vector
                await store_decision_vector(
                    tenant_id=tenant_id,
                    product_id=product_id,
                    sector="supply_chain",
                    decision_text=decision_text,
                    insights=insights,
                    accuracy=None,  # will be updated later via /outcomes endpoint
                )
                logger.info("[RAG] Decision stored for future retrieval.")
            except Exception as e:
                logger.warning("[RAG] Failed to store decision: %s", str(e))

        await save_decision_memory(
            tenant_id=tenant_id, sector="supply_chain",
            product_id=product_id, recommendation=sales,
            confidence=hitl_result["confidence"],
        )

    return state
