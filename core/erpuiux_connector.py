"""
ERP-UI-UX CONNECTOR — MultiAgent Platform v6
=============================================
Connects the MultiAgent supply chain agents to the real ERP-UI-UX
(Frappe/ERPNext backend) running locally.

Reads live data:
  - Stock / Inventory  → production_agent
  - Sales (Delivery Notes) → sales_agent
  - Purchase Orders    → decision_agent context

Usage:
  from core.erpuiux_connector import ERPUIUXConnector
  connector = ERPUIUXConnector()
  stock = await connector.get_stock("HARISSA-140G")
"""

import os
import json
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
ERP_BASE_URL = os.getenv("ERPUIUX_URL", "http://localhost:8000")
ERP_API_KEY  = os.getenv("ERPUIUX_API_KEY", "")
ERP_SECRET   = os.getenv("ERPUIUX_SECRET", "")
ERP_SITE     = os.getenv("ERPUIUX_SITE", "localhost")   # Frappe site name


class ERPUIUXConnector:
    """
    Client for ERP-UI-UX (Frappe/ERPNext) REST API.
    All methods are async — safe to use inside agents.
    """

    def __init__(self):
        self.base_url = ERP_BASE_URL.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
        }
        # Frappe token auth (API Key + Secret)
        if ERP_API_KEY and ERP_SECRET:
            self.headers["Authorization"] = f"token {ERP_API_KEY}:{ERP_SECRET}"

    # ─── Internal helper ──────────────────────────────────────────────────────

    async def _get(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, headers=self.headers, params=params or {})
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("[ERP] HTTP error %s — %s", e.response.status_code, url)
            raise
        except Exception as e:
            logger.error("[ERP] Connection error: %s", str(e))
            raise

    # ─── Stock / Inventory ────────────────────────────────────────────────────

    async def get_stock(self, item_code: str) -> dict:
        """
        Returns real-time stock for an item.
        Maps to → production_agent input.

        Returns:
            {
                "item_code": "HARISSA-140G",
                "item_name": "Harissa piquante 140g",
                "actual_qty": 3000,
                "projected_qty": 3000,
                "reserved_qty": 0,
                "status": "OK",   # OK | WARNING | RUPTURE
                "warehouse": "Goods In Transit - AGI"
            }
        """
        try:
            data = await self._get(
                "/api/resource/Bin",
                params={
                    "filters": f'[["item_code","=","{item_code}"]]',
                    "fields": '["item_code","actual_qty","projected_qty","reserved_qty","warehouse"]',
                    "limit": 1,
                }
            )
            bins = data.get("data", [])
            if not bins:
                logger.warning("[ERP] No stock found for item: %s", item_code)
                return self._empty_stock(item_code)

            bin_data = bins[0]
            actual_qty = float(bin_data.get("actual_qty", 0))

            # Fetch item name
            item_data = await self._get(
                f"/api/resource/Item/{item_code}",
                params={"fields": '["item_name","safety_stock"]'}
            )
            item_name    = item_data.get("data", {}).get("item_name", item_code)
            safety_stock = float(item_data.get("data", {}).get("safety_stock", 0))

            # Determine status
            if actual_qty == 0:
                status = "RUPTURE"
            elif safety_stock and actual_qty <= safety_stock:
                status = "WARNING"
            else:
                status = "OK"

            return {
                "item_code":      item_code,
                "item_name":      item_name,
                "actual_qty":     actual_qty,
                "projected_qty":  float(bin_data.get("projected_qty", actual_qty)),
                "reserved_qty":   float(bin_data.get("reserved_qty", 0)),
                "warehouse":      bin_data.get("warehouse", ""),
                "status":         status,
                "source":         "erp_live",
            }

        except Exception as e:
            logger.error("[ERP] get_stock failed: %s", str(e))
            return self._empty_stock(item_code, error=str(e))

    async def get_all_stock(self) -> list[dict]:
        """Returns stock for all items (for dashboard overview)."""
        try:
            data = await self._get(
                "/api/resource/Bin",
                params={
                    "fields": '["item_code","actual_qty","projected_qty","reserved_qty","warehouse"]',
                    "limit": 50,
                }
            )
            return data.get("data", [])
        except Exception as e:
            logger.error("[ERP] get_all_stock failed: %s", str(e))
            return []

    # ─── Sales (Delivery Notes) ───────────────────────────────────────────────

    async def get_sales_last_30_days(self, item_code: str) -> dict:
        from datetime import datetime, timedelta
        date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        try:
            data = await self._get(
                "/api/method/erp_ui_ux.api.multiagent.get_item_sales",
                params={"item_code": item_code, "date_from": date_from}
            )
            result = data.get("message", {})
            total_qty = float(result.get("total_qty", 0))
            delivery_count = int(result.get("delivery_count", 0))

            return {
                "item_code":      item_code,
                "qty_sold_30d":   total_qty,
                "avg_daily":      round(total_qty / 30, 2),
                "delivery_count": delivery_count,
                "source":         "erp_live",
            }

        except Exception as e:
            logger.error("[ERP] get_sales_last_30_days failed: %s", str(e))
            return {"item_code": item_code, "qty_sold_30d": 0, "avg_daily": 0.0, "delivery_count": 0, "source": "erp_error", "error": str(e)}

    # ─── Purchase Orders ──────────────────────────────────────────────────────

    async def get_pending_orders(self, item_code: str) -> dict:
        """
        Returns pending purchase orders for an item.
        Useful for decision_agent to know incoming stock.
        """
        try:
            data = await self._get(
                "/api/resource/Purchase Order Item",
                params={
                    "filters": (
                        f'[["item_code","=","{item_code}"],'
                        f'["parent.status","in","To Receive and Bill,To Receive"]]'
                    ),
                    "fields": '["item_code","qty","schedule_date","parent"]',
                    "limit": 20,
                }
            )
            orders = data.get("data", [])
            total_pending = sum(float(o.get("qty", 0)) for o in orders)

            return {
                "item_code":       item_code,
                "pending_qty":     total_pending,
                "orders_count":    len(orders),
                "next_delivery":   orders[0].get("schedule_date") if orders else None,
                "source":          "erp_live",
            }

        except Exception as e:
            logger.error("[ERP] get_pending_orders failed: %s", str(e))
            return {"item_code": item_code, "pending_qty": 0, "source": "erp_error"}

    # ─── Health check ─────────────────────────────────────────────────────────

    async def ping(self) -> bool:
        """Returns True if ERP-UI-UX is reachable."""
        try:
            await self._get("/api/method/ping")
            return True
        except Exception:
            return False

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _empty_stock(self, item_code: str, error: str = None) -> dict:
        return {
            "item_code":     item_code,
            "item_name":     item_code,
            "actual_qty":    0,
            "projected_qty": 0,
            "reserved_qty":  0,
            "warehouse":     "",
            "status":        "UNKNOWN",
            "source":        "erp_fallback",
            "error":         error,
        }


# ─── Singleton ────────────────────────────────────────────────────────────────
_connector: Optional[ERPUIUXConnector] = None


def get_erp_connector() -> ERPUIUXConnector:
    global _connector
    if _connector is None:
        _connector = ERPUIUXConnector()
    return _connector
