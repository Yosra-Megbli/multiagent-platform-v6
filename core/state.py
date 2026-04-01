from typing import TypedDict, Optional, Any


class UniversalState(TypedDict):
    # Identity
    tenant_id: str
    sector: str

    # Input (flexible per sector)
    input_data: dict          # sector-specific inputs

    # Agent outputs (each agent writes to its own key)
    agent_outputs: dict       # {"weather_agent": {...}, "sales_agent": {...}}

    # Aggregated insights
    aggregated_insights: Optional[dict]

    # Final recommendation
    final_decision: Optional[str]

    # Meta
    errors: list[str]
    status: str               # "running" | "done" | "error"
