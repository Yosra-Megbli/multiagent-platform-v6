"""
DATA CONNECTORS
================
Instead of waiting for clients to push data,
connectors pull data directly from external sources.

Supported:
  - CSV files (local or S3)
  - Google Sheets
  - Generic REST API (ERP, SAP, etc.)
  - PostgreSQL (internal)

Usage:
  connector = get_connector("google_sheets", config)
  data = await connector.fetch_sales(tenant_id, product_id)
"""

import os
import csv
import json
import httpx
from abc import ABC, abstractmethod
from typing import Optional


# ─── Base Connector ───────────────────────────────────────────────────────────

class BaseConnector(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def fetch_sales(self, tenant_id: str, product_id: str) -> list[dict]:
        """Returns list of {ds: date, y: float}"""
        pass

    @abstractmethod
    async def fetch_production_config(self, tenant_id: str, product_id: str) -> dict:
        """Returns production capacity and stock levels"""
        pass


# ─── CSV Connector ────────────────────────────────────────────────────────────

class CSVConnector(BaseConnector):
    """
    Reads sales data from a CSV file.
    Expected format: date,product_id,quantity
    """

    async def fetch_sales(self, tenant_id: str, product_id: str) -> list[dict]:
        file_path = self.config.get("sales_file")
        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        rows = []
        with open(file_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("product_id") == product_id:
                    rows.append({"ds": row["date"], "y": float(row["quantity"])})

        return sorted(rows, key=lambda x: x["ds"])

    async def fetch_production_config(self, tenant_id: str, product_id: str) -> dict:
        file_path = self.config.get("production_file")
        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(f"Production config file not found: {file_path}")

        with open(file_path, "r") as f:
            data = json.load(f)

        config = data.get(product_id)
        if not config:
            raise ValueError(f"No config for product_id={product_id}")
        return config


# ─── Google Sheets Connector ──────────────────────────────────────────────────

class GoogleSheetsConnector(BaseConnector):
    """
    Reads data from Google Sheets via the Sheets API.
    Requires: spreadsheet_id, range, google_api_key or service_account_json
    """

    BASE_URL = "https://sheets.googleapis.com/v4/spreadsheets"

    async def _fetch_sheet(self, spreadsheet_id: str, range_: str) -> list[list]:
        api_key = self.config.get("google_api_key")
        url = f"{self.BASE_URL}/{spreadsheet_id}/values/{range_}"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params={"key": api_key})
            response.raise_for_status()
            data = response.json()

        return data.get("values", [])

    async def fetch_sales(self, tenant_id: str, product_id: str) -> list[dict]:
        spreadsheet_id = self.config["spreadsheet_id"]
        range_ = self.config.get("sales_range", "Sales!A:C")  # date, product_id, quantity

        rows = await self._fetch_sheet(spreadsheet_id, range_)
        if not rows:
            return []

        headers = rows[0]
        result = []
        for row in rows[1:]:
            if len(row) < 3:
                continue
            record = dict(zip(headers, row))
            if record.get("product_id") == product_id:
                result.append({
                    "ds": record["date"],
                    "y": float(record["quantity"])
                })

        return sorted(result, key=lambda x: x["ds"])

    async def fetch_production_config(self, tenant_id: str, product_id: str) -> dict:
        spreadsheet_id = self.config["spreadsheet_id"]
        range_ = self.config.get("production_range", "Production!A:E")

        rows = await self._fetch_sheet(spreadsheet_id, range_)
        headers = rows[0] if rows else []

        for row in rows[1:]:
            record = dict(zip(headers, row))
            if record.get("product_id") == product_id:
                return {
                    "daily_capacity": int(record["daily_capacity"]),
                    "current_stock": int(record["current_stock"]),
                    "packaging_stock": int(record["packaging_stock"]),
                    "supplier_lead_time": int(record.get("lead_time", 4)),
                }

        raise ValueError(f"No production config found for product_id={product_id}")


# ─── Generic REST API Connector (ERP / SAP) ───────────────────────────────────

class RESTConnector(BaseConnector):
    """
    Connects to any REST API (ERP, SAP, custom).
    Requires: base_url, headers, sales_endpoint, production_endpoint
    """

    async def fetch_sales(self, tenant_id: str, product_id: str) -> list[dict]:
        url = f"{self.config['base_url']}{self.config['sales_endpoint']}"
        headers = self.config.get("headers", {})
        params = {"product_id": product_id, "tenant_id": tenant_id}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

        # Normalize: expects list of {date, quantity}
        return [{"ds": row["date"], "y": float(row["quantity"])} for row in data]

    async def fetch_production_config(self, tenant_id: str, product_id: str) -> dict:
        url = f"{self.config['base_url']}{self.config['production_endpoint']}"
        headers = self.config.get("headers", {})
        params = {"product_id": product_id, "tenant_id": tenant_id}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()


# ─── Connector Factory ────────────────────────────────────────────────────────

from core.erpnext_connector import ERPNextConnector

CONNECTOR_MAP = {
    "csv":          CSVConnector,
    "google_sheets": GoogleSheetsConnector,
    "rest_api":     RESTConnector,
    "erpnext":      ERPNextConnector,
}


def get_connector(connector_type: str, config: dict) -> BaseConnector:
    """
    Returns the appropriate connector based on tenant config.

    Usage:
        connector = get_connector(tenant["config"]["connector_type"], tenant["config"])
        sales = await connector.fetch_sales(tenant_id, product_id)
    """
    cls = CONNECTOR_MAP.get(connector_type)
    if not cls:
        raise ValueError(f"Unknown connector: '{connector_type}'. Available: {list(CONNECTOR_MAP.keys())}")
    return cls(config)
