#!/usr/bin/env python3
"""Check and fix sales data in ERPNext"""
import requests
import json
import random
from datetime import datetime, timedelta

ERP_URL = "http://localhost:8080"
HEADERS = {"Authorization": "token 9e7cabe3b04bb2b:889e8f68d894307"}

PRODUCTS = [
    "ADD-001","EMB-001","EMB-002","FAR-001","FAR-002","GAT-001",
    "HARISSA-140G","HUI-001","HUILE-500ML","LEV-001","PAIN-001",
    "PAIN-002","sardine","SARDINE-125G","SUC-001","THON-160G","VIE-001","VIE-002"
]

MONTHLY_DEMAND = {
    "ADD-001": 180, "EMB-001": 3500, "EMB-002": 800, "FAR-001": 2800,
    "FAR-002": 900, "GAT-001": 250, "HARISSA-140G": 600, "HUI-001": 320,
    "HUILE-500ML": 280, "LEV-001": 80, "PAIN-001": 1800, "PAIN-002": 2200,
    "sardine": 400, "SARDINE-125G": 500, "SUC-001": 1200, "THON-160G": 380,
    "VIE-001": 350, "VIE-002": 180
}

def get(endpoint, params=None):
    r = requests.get(ERP_URL + endpoint, headers=HEADERS, params=params or {}, timeout=10)
    return r.json() if r.status_code == 200 else {}

def post(endpoint, data):
    r = requests.post(ERP_URL + endpoint, headers=HEADERS, json=data, timeout=15)
    return r.status_code in (200, 201), r.text[:200]

def get_date(days_ago):
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")

# Step 1: Check existing Delivery Notes
print("=== Checking existing Delivery Notes ===")
date_from = get_date(30)
r = get("/api/resource/Delivery Note", {
    "filters": f'[["posting_date",">=","{date_from}"],["docstatus","=","1"]]',
    "fields": '["name","posting_date"]',
    "limit": 100
})
dns = r.get("data", [])
print(f"Delivery Notes last 30 days: {len(dns)}")

# Check if FAR-001 is in any DN
far_found = False
for dn in dns[:5]:
    r2 = get("/api/resource/Delivery Note Item", {
        "filters": f'[["parent","=","{dn["name"]}"],["item_code","=","FAR-001"]]',
        "fields": '["item_code","qty"]',
        "limit": 5
    })
    items = r2.get("data", [])
    if items:
        far_found = True
        print(f"FAR-001 found in {dn['name']}: {items}")

print(f"FAR-001 in recent DNs: {far_found}")

# Step 1.5: Replenish stock first
print("\n=== Replenishing stock ===" )
for code in PRODUCTS:
    avg = MONTHLY_DEMAND.get(code, 100)
    qty_in = avg * 3  # 3 months of stock
    success, msg = post("/api/resource/Stock Entry", {
        "stock_entry_type": "Material Receipt",
        "posting_date": get_date(31),
        "items": [{"item_code": code, "t_warehouse": "Stores - AGI", "qty": qty_in, "basic_rate": 10.0}],
        "docstatus": 1
    })
    print(f"  {'[OK]' if success else '[WARN]'} {code} +{qty_in}")

# Step 2: Create new Delivery Notes with ALL products guaranteed
print("\n=== Creating new Delivery Notes (all products included) ===")

# Ensure customer exists
customer = "Client Tunis Demo"
r = get(f"/api/resource/Customer/{customer}")
if "data" not in r:
    post("/api/resource/Customer", {
        "customer_name": customer,
        "customer_type": "Company",
        "customer_group": "Commercial",
        "territory": "Tunisia"
    })

ok = 0
random.seed(2024)

# Create 1 DN per day for last 30 days, each containing ALL products
for day in range(30, 0, -1):
    items = []
    for code in PRODUCTS:
        avg = MONTHLY_DEMAND.get(code, 100)
        qty = max(1, int(random.gauss(avg / 30, avg / 60)))
        items.append({
            "item_code": code,
            "item_name": code,
            "qty": qty,
            "rate": round(random.uniform(2.0, 50.0), 2),
            "uom": "Nos",
            "warehouse": "Stores - AGI",
        })

    success, msg = post("/api/resource/Delivery Note", {
        "customer": customer,
        "posting_date": get_date(day),
        "set_warehouse": "Stores - AGI",
        "items": items,
        "docstatus": 1
    })
    if success:
        ok += 1
    else:
        print(f"  [WARN] Day -{day}: {msg[:100]}")

print(f"\n[OK] {ok}/30 delivery notes created with ALL {len(PRODUCTS)} products")

# Step 3: Verify FAR-001 sales
print("\n=== Verifying FAR-001 sales ===")
date_from = get_date(30)
r = get("/api/resource/Delivery Note", {
    "filters": f'[["posting_date",">=","{date_from}"],["docstatus","=","1"]]',
    "fields": '["name"]',
    "limit": 100
})
dns = r.get("data", [])
print(f"Total DNs last 30d: {len(dns)}")

total_far = 0
for dn in dns[:5]:
    dn_name = dn["name"]
    r2 = get("/api/resource/Delivery Note Item", {
        "filters": f'[["parent","=","{dn_name}"],["item_code","=","FAR-001"]]',
        "fields": '["qty"]',
        "limit": 5
    })
    for item in r2.get("data", []):
        total_far += float(item.get("qty", 0))

print(f"FAR-001 qty in first 5 DNs: {total_far}")
print("\n[DONE] Run a new analysis to see sales > 0")
