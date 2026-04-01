"""
ERPNext Connector — Argo Industries
=====================================
Reads real data from ERPNext (Frappe) via REST API:
  - fetch_sales()            → Sales Invoice items → Prophet forecast
  - fetch_production_config() → Bin stock levels → production agent
"""

import os
import httpx
import logging
from datetime import datetime, timedelta
from core.connectors import BaseConnector

logger = logging.getLogger(__name__)

# BUG FIX #3: credentials now read from env vars (never hardcoded)
# BUG FIX #4: URL now read from env — set ERPUIUX_URL to your real ERPNext address
ERPNEXT_BASE_URL = os.getenv("ERPUIUX_URL", "http://localhost:8080")
_api_key         = os.getenv("ERPUIUX_API_KEY", "")
_api_secret      = os.getenv("ERPUIUX_SECRET", "")
ERPNEXT_TOKEN    = f"token {_api_key}:{_api_secret}" if _api_key else ""
HEADERS          = {"Authorization": ERPNEXT_TOKEN} if ERPNEXT_TOKEN else {}


class ERPNextConnector(BaseConnector):
    """
    Connects MultiAgent Platform to ERPNext (Frappe).
    Reads Sales Invoices for demand forecasting and Bin for stock levels.
    """

    async def fetch_sales(self, tenant_id: str, product_id: str) -> list[dict]:
        """
        Fetches sales history from ERPNext Sales Invoice items.
        Returns list of {ds: date, y: quantity} for Prophet.
        """
        url = f"{self.config.get('base_url', ERPNEXT_BASE_URL)}/api/resource/Sales%20Invoice"
        headers = {"Authorization": self.config.get("token", ERPNEXT_TOKEN)}

        # Fetch last 365 days of invoices
        date_from = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=headers, params={
                    "limit": 500,
                    "filters": f'[["posting_date",">=","{date_from}"]]',
                    "fields": '["name","posting_date"]'
                })
                resp.raise_for_status()
                invoices = resp.json().get("data", [])

            # For each invoice, get items matching product_id
            sales_by_date = {}
            for inv in invoices:
                inv_name = inv["name"]
                inv_date = inv["posting_date"]

                # Get invoice detail
                detail_resp = await self._get_invoice_items(inv_name, headers)
                for item in detail_resp:
                    if item.get("item_code") == product_id:
                        qty = float(item.get("qty", 0))
                        if inv_date in sales_by_date:
                            sales_by_date[inv_date] += qty
                        else:
                            sales_by_date[inv_date] = qty

            rows = [{"ds": date, "y": qty} for date, qty in sales_by_date.items()]
            rows.sort(key=lambda x: x["ds"])

            logger.info("[ERPNEXT] Fetched %d sales days for %s", len(rows), product_id)
            return rows

        except Exception as e:
            logger.warning("[ERPNEXT] fetch_sales failed: %s", str(e))
            raise

    async def _get_invoice_items(self, invoice_name: str, headers: dict) -> list:
        """Get items from a single Sales Invoice."""
        url = f"{self.config.get('base_url', ERPNEXT_BASE_URL)}/api/resource/Sales%20Invoice/{invoice_name}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.json().get("data", {}).get("items", [])
        except Exception:
            return []

    async def fetch_production_config(self, tenant_id: str, product_id: str) -> dict:
        """
        Fetches stock levels from ERPNext Bin.
        Returns production config compatible with ProductionAgent.
        """
        url = f"{self.config.get('base_url', ERPNEXT_BASE_URL)}/api/resource/Bin"
        headers = {"Authorization": self.config.get("token", ERPNEXT_TOKEN)}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=headers, params={
                    "limit": 50,
                    "filters": f'[["item_code","=","{product_id}"]]',
                    "fields": '["name","item_code","warehouse","actual_qty","projected_qty","valuation_rate"]'
                })
                resp.raise_for_status()
                bins = resp.json().get("data", [])

            if not bins:
                raise ValueError(f"No stock found for item {product_id} in ERPNext")

            # Aggregate stock across all warehouses
            total_stock     = sum(float(b.get("actual_qty", 0)) for b in bins)
            finished_stock  = sum(
                float(b.get("actual_qty", 0)) for b in bins
                if "Finished" in b.get("warehouse", "") or "Stores" in b.get("warehouse", "")
            )
            packaging_stock = sum(
                float(b.get("actual_qty", 0)) for b in bins
                if "Transit" in b.get("warehouse", "")
            )

            logger.info("[ERPNEXT] Stock for %s: total=%.0f finished=%.0f",
                        product_id, total_stock, finished_stock)

            return {
                "daily_capacity":      int(total_stock / 30) if total_stock > 0 else 500,
                "current_stock":       int(finished_stock or total_stock),
                "packaging_stock":     int(packaging_stock or total_stock * 0.3),
                "supplier_lead_time":  5,
                "data_source":         "erpnext",
                "warehouses":          [b.get("warehouse") for b in bins],
            }

        except Exception as e:
            logger.warning("[ERPNEXT] fetch_production_config failed: %s", str(e))
            raise
