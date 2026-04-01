"""
Production Agent — v6.1 (ERP-UI-UX Live Integration)
======================================================
BUG FIX: Output now matches ProductionOutput schema exactly.
Required fields: daily_capacity, current_stock, packaging_stock,
daily_demand_forecast, days_of_stock, days_of_packaging,
capacity_gap, can_meet_demand, reorder_needed, lead_time_days
"""

import logging
from core.state import UniversalState

logger = logging.getLogger(__name__)

DAILY_CAPACITY   = 150   # units/day — configurable per product
PACKAGING_STOCK  = 5000  # default packaging units
LEAD_TIME_DAYS   = 5


async def run_production_agent(state: UniversalState) -> UniversalState:
    product_id = state["input_data"].get("product_id", "DEFAULT")

    # Get demand forecast from sales_agent if available
    sales = state["agent_outputs"].get("sales_agent", {})
    daily_demand = sales.get("avg_daily", 30.0) or 30.0

    try:
        # ── Try live ERP ────────────────────────────────────────────────────
        from core.erpuiux_connector import get_erp_connector
        connector = get_erp_connector()

        stock  = await connector.get_stock(product_id)
        orders = await connector.get_pending_orders(product_id)

        actual_qty     = float(stock.get("actual_qty", 0))
        days_of_stock  = round(actual_qty / daily_demand, 1) if daily_demand else 0
        days_packaging = round(PACKAGING_STOCK / daily_demand, 1) if daily_demand else 0
        capacity_gap   = round(DAILY_CAPACITY - daily_demand, 1)

        output = {
            # Required by ProductionOutput schema
            "daily_capacity":        DAILY_CAPACITY,
            "current_stock":         int(actual_qty),
            "packaging_stock":       PACKAGING_STOCK,
            "daily_demand_forecast": round(daily_demand, 2),
            "days_of_stock":         days_of_stock,
            "days_of_packaging":     days_packaging,
            "capacity_gap":          capacity_gap,
            "can_meet_demand":       DAILY_CAPACITY >= daily_demand,
            "reorder_needed":        days_packaging < LEAD_TIME_DAYS,
            "lead_time_days":        LEAD_TIME_DAYS,
            "fallback":              False,
            # Extra ERP fields (not in schema but useful for decision_agent)
            "item_code":      product_id,
            "item_name":      stock.get("item_name", product_id),
            "projected_qty":  float(stock.get("projected_qty", actual_qty)),
            "pending_orders": orders.get("pending_qty", 0),
            "next_delivery":  orders.get("next_delivery"),
            "warehouse":      stock.get("warehouse", ""),
            "erp_status":     stock.get("status", "UNKNOWN"),
            "source":         "erp_live",
        }

        logger.info(
            "[PRODUCTION] Live ERP | item=%s stock=%d days=%.1f",
            product_id, int(actual_qty), days_of_stock
        )

    except Exception as e:
        logger.warning("[PRODUCTION] ERP unreachable (%s) — using fallback", str(e))

        current_stock  = 1200
        days_of_stock  = round(current_stock / daily_demand, 1) if daily_demand else 8.0
        days_packaging = round(PACKAGING_STOCK / daily_demand, 1) if daily_demand else 33.0
        capacity_gap   = round(DAILY_CAPACITY - daily_demand, 1)

        output = {
            "daily_capacity":        DAILY_CAPACITY,
            "current_stock":         current_stock,
            "packaging_stock":       PACKAGING_STOCK,
            "daily_demand_forecast": round(daily_demand, 2),
            "days_of_stock":         days_of_stock,
            "days_of_packaging":     days_packaging,
            "capacity_gap":          capacity_gap,
            "can_meet_demand":       DAILY_CAPACITY >= daily_demand,
            "reorder_needed":        days_packaging < LEAD_TIME_DAYS,
            "lead_time_days":        LEAD_TIME_DAYS,
            "fallback":              True,
            "source":                "fallback",
            "error":                 str(e),
        }

    state["agent_outputs"]["production_agent"] = output
    return state
