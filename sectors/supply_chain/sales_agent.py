"""
Sales Agent — v6.1 (ERP-UI-UX Live Integration)
=================================================
BUG FIX: Output now matches SalesOutput schema exactly.
Required fields: baseline_daily, total_30_days, adjusted_30_days,
weather_multiplier, memory_adjustment, final_multiplier,
peak_day, data_source, fallback
"""

import logging
from core.state import UniversalState

logger = logging.getLogger(__name__)

WEATHER_MULTIPLIERS = {
    "heat_wave": 1.4,
    "rainy":     0.85,
    "normal":    1.0,
}


async def run_sales_agent(state: UniversalState) -> UniversalState:
    product_id = state["input_data"].get("product_id", "DEFAULT")
    weather    = state["agent_outputs"].get("weather_agent", {})

    # Weather multiplier
    multiplier = 1.0
    if weather.get("heat_wave"):
        multiplier = WEATHER_MULTIPLIERS["heat_wave"]
    elif weather.get("rain_days", 0) > 10:
        multiplier = WEATHER_MULTIPLIERS["rainy"]

    try:
        # ── Try live ERP ────────────────────────────────────────────────────
        from core.erpuiux_connector import get_erp_connector
        connector = get_erp_connector()

        sales = await connector.get_sales_last_30_days(product_id)

        base_30d     = float(sales.get("qty_sold_30d", 0))
        baseline_d   = round(base_30d / 30, 2) if base_30d else 0.0
        adjusted     = round(base_30d * multiplier)

        output = {
            # Required by SalesOutput schema
            "baseline_daily":     baseline_d,
            "total_30_days":      base_30d,
            "adjusted_30_days":   float(adjusted),
            "weather_multiplier": multiplier,
            "memory_adjustment":  1.0,
            "final_multiplier":   multiplier,
            "peak_day":           None,
            "data_source":        "erp_live",
            "fallback":           False,
            # Extra fields for decision_agent
            "avg_daily":          baseline_d,
            "delivery_count":     sales.get("delivery_count", 0),
            "source":             "erp_live",
        }

        logger.info(
            "[SALES] Live ERP | item=%s sold_30d=%.0f adjusted=%.0f multiplier=%.2f",
            product_id, base_30d, adjusted, multiplier
        )

    except Exception as e:
        logger.warning("[SALES] ERP unreachable (%s) — using fallback", str(e))

        base_30d   = 900.0
        baseline_d = round(base_30d / 30, 2)
        adjusted   = round(base_30d * multiplier)

        output = {
            "baseline_daily":     baseline_d,
            "total_30_days":      base_30d,
            "adjusted_30_days":   float(adjusted),
            "weather_multiplier": multiplier,
            "memory_adjustment":  1.0,
            "final_multiplier":   multiplier,
            "peak_day":           None,
            "data_source":        "fallback",
            "fallback":           True,
            "avg_daily":          baseline_d,
            "delivery_count":     0,
            "source":             "fallback",
            "error":              str(e),
        }

    state["agent_outputs"]["sales_agent"] = output
    return state
