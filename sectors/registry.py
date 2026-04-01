"""
SECTOR REGISTRY
===============
To add a new sector:
1. Add an entry below with the list of agent module names
2. Create the agent files in sectors/<sector>/
3. That's it — no changes needed anywhere else

Agent names must match the filename in sectors/<sector>/<agent_name>.py
Each agent file must expose an async function: run_<agent_name>(state) -> state
"""

SECTOR_AGENTS: dict[str, list[str]] = {

    # ✅ IMPLEMENTED — v6: Tool-Calling + RAG
    # Phase 1 (parallel): weather_agent + sales_agent + production_agent
    # Phase 2: aggregator_agent (rules-based alerts)
    # Phase 3: decision_agent (tool-calling + RAG)
    "supply_chain": [
        "weather_agent",        # BUG FIX #1: was missing — phase 1 parallel
        "sales_agent",          # BUG FIX #1: was missing — phase 1 parallel
        "production_agent",     # BUG FIX #1: was missing — phase 1 parallel
        "aggregator_agent",
        "decision_agent",
    ],

    # 🔲 READY — add agents when needed
    "legal": [
        # "document_extractor_agent",
        # "risk_agent",
        # "qa_agent",
        # "decision_agent",
    ],

    # 🔲 READY — add agents when needed
    "hr": [
        # "onboarding_agent",
        # "learning_agent",
        # "policy_agent",
        # "decision_agent",
    ],

    # 🔲 READY — add agents when needed
    "real_estate": [
        # "property_search_agent",
        # "price_analysis_agent",
        # "document_agent",
        # "decision_agent",
    ],
}


def get_sector_agents(sector: str) -> list[str]:
    if sector not in SECTOR_AGENTS:
        raise ValueError(f"Unknown sector: '{sector}'. Available: {list(SECTOR_AGENTS.keys())}")
    agents = SECTOR_AGENTS[sector]
    if not agents:
        raise NotImplementedError(f"Sector '{sector}' is registered but has no agents yet.")
    return agents


def list_available_sectors() -> list[str]:
    return [s for s, agents in SECTOR_AGENTS.items() if agents]
