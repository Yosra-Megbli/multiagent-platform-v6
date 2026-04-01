"""Aggregator — v3.2: Pydantic Schema validation"""

from core.state import UniversalState
from core.schemas import validate_aggregated_insights


def aggregate(state: UniversalState) -> UniversalState:
    weather    = state["agent_outputs"].get("weather_agent", {})
    sales      = state["agent_outputs"].get("sales_agent", {})
    production = state["agent_outputs"].get("production_agent", {})

    alerts  = []
    urgency = "LOW"

    if production.get("days_of_stock", 99) < 5:
        alerts.append("STOCK_CRITICAL"); urgency = "HIGH"
    elif production.get("days_of_stock", 99) < 10:
        alerts.append("STOCK_LOW"); urgency = "MEDIUM"

    if production.get("reorder_needed"):
        alerts.append("REORDER_PACKAGING_NOW"); urgency = "HIGH"

    if not production.get("can_meet_demand", True):
        alerts.append("CAPACITY_INSUFFICIENT"); urgency = "HIGH"

    if weather.get("heat_wave"):
        alerts.append("HEAT_WAVE_DEMAND_SURGE")

    has_fallback = any([
        weather.get("fallback"), sales.get("fallback"), production.get("fallback")
    ])

    state["aggregated_insights"] = validate_aggregated_insights({
        "alerts":             alerts,
        "urgency":            urgency,
        "weather_summary":    f"{weather.get('max_temp')}°C max, {weather.get('rain_days')} rain days",
        "demand_summary":     f"{sales.get('adjusted_30_days')} units / 30 days",
        "stock_days":         production.get("days_of_stock"),
        "packaging_days":     production.get("days_of_packaging"),
        "capacity_gap":       production.get("capacity_gap"),
        "multiplier_applied": sales.get("weather_multiplier"),
        "has_fallback_data":  has_fallback,
    })

    return state
