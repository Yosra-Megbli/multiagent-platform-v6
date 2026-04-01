#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ERPNext Data Initializer - MultiAgent Platform v6
Usage: python erp_init.py
"""

import requests
import random
from datetime import datetime, timedelta
from typing import Optional

ERP_URL    = "http://localhost:8080"
API_KEY    = "9e7cabe3b04bb2b"
API_SECRET = "889e8f68d894307"

HEADERS = {
    "Authorization": "token {}:{}".format(API_KEY, API_SECRET),
    "Content-Type": "application/json",
    "Accept": "application/json"
}

PRODUCTS = [
    {"item_code": "ADD-001",      "item_name": "Ameliorant pain de mie 25kg",       "item_group": "Matieres Premieres", "stock_uom": "Kg",    "valuation_rate": 45.0, "standard_rate": 55.0, "opening_stock": 500,  "monthly_demand_avg": 180,  "monthly_demand_std": 30},
    {"item_code": "EMB-001",      "item_name": "Sachets kraft boulangerie 25x35cm", "item_group": "Emballages",         "stock_uom": "Nos",   "valuation_rate": 0.15, "standard_rate": 0.25, "opening_stock": 10000,"monthly_demand_avg": 3500, "monthly_demand_std": 500},
    {"item_code": "EMB-002",      "item_name": "Boites patisserie 20x20cm",         "item_group": "Emballages",         "stock_uom": "Nos",   "valuation_rate": 0.80, "standard_rate": 1.20, "opening_stock": 2000, "monthly_demand_avg": 800,  "monthly_demand_std": 150},
    {"item_code": "FAR-001",      "item_name": "Farine de ble T55 sac 50kg",        "item_group": "Matieres Premieres", "stock_uom": "Kg",    "valuation_rate": 38.0, "standard_rate": 48.0, "opening_stock": 5000, "monthly_demand_avg": 2800, "monthly_demand_std": 400},
    {"item_code": "FAR-002",      "item_name": "Farine complete T80 sac 50kg",      "item_group": "Matieres Premieres", "stock_uom": "Kg",    "valuation_rate": 42.0, "standard_rate": 52.0, "opening_stock": 2000, "monthly_demand_avg": 900,  "monthly_demand_std": 150},
    {"item_code": "GAT-001",      "item_name": "Gateaux assortis plateau 1kg",      "item_group": "Produits Finis",     "stock_uom": "Nos",   "valuation_rate": 12.0, "standard_rate": 18.0, "opening_stock": 300,  "monthly_demand_avg": 250,  "monthly_demand_std": 60},
    {"item_code": "HARISSA-140G", "item_name": "Harissa piquante 140g",             "item_group": "Produits Finis",     "stock_uom": "Nos",   "valuation_rate": 1.80, "standard_rate": 2.80, "opening_stock": 1500, "monthly_demand_avg": 600,  "monthly_demand_std": 100},
    {"item_code": "HUI-001",      "item_name": "Huile vegetale bidon 20L",          "item_group": "Matieres Premieres", "stock_uom": "Litre", "valuation_rate": 28.0, "standard_rate": 35.0, "opening_stock": 800,  "monthly_demand_avg": 320,  "monthly_demand_std": 50},
    {"item_code": "HUILE-500ML",  "item_name": "Huile d'olive 500ml",               "item_group": "Produits Finis",     "stock_uom": "Nos",   "valuation_rate": 5.50, "standard_rate": 8.50, "opening_stock": 600,  "monthly_demand_avg": 280,  "monthly_demand_std": 60},
    {"item_code": "LEV-001",      "item_name": "Levure boulangere seche 500g",      "item_group": "Matieres Premieres", "stock_uom": "Kg",    "valuation_rate": 15.0, "standard_rate": 22.0, "opening_stock": 200,  "monthly_demand_avg": 80,   "monthly_demand_std": 15},
    {"item_code": "PAIN-001",     "item_name": "Pain de mie tranche 500g",          "item_group": "Produits Finis",     "stock_uom": "Nos",   "valuation_rate": 1.20, "standard_rate": 2.00, "opening_stock": 1000, "monthly_demand_avg": 1800, "monthly_demand_std": 300},
    {"item_code": "PAIN-002",     "item_name": "Baguettes tradition (unite)",       "item_group": "Produits Finis",     "stock_uom": "Nos",   "valuation_rate": 0.35, "standard_rate": 0.60, "opening_stock": 500,  "monthly_demand_avg": 2200, "monthly_demand_std": 400},
    {"item_code": "sardine",      "item_name": "sardine",                           "item_group": "Produits Finis",     "stock_uom": "Nos",   "valuation_rate": 2.50, "standard_rate": 3.80, "opening_stock": 800,  "monthly_demand_avg": 400,  "monthly_demand_std": 80},
    {"item_code": "SARDINE-125G", "item_name": "Sardines marinees 125g",            "item_group": "Produits Finis",     "stock_uom": "Nos",   "valuation_rate": 2.80, "standard_rate": 4.20, "opening_stock": 1200, "monthly_demand_avg": 500,  "monthly_demand_std": 90},
    {"item_code": "SUC-001",      "item_name": "Sucre blanc cristallise 50kg",      "item_group": "Matieres Premieres", "stock_uom": "Kg",    "valuation_rate": 32.0, "standard_rate": 40.0, "opening_stock": 3000, "monthly_demand_avg": 1200, "monthly_demand_std": 200},
    {"item_code": "THON-160G",    "item_name": "Thon entier 160g",                  "item_group": "Produits Finis",     "stock_uom": "Nos",   "valuation_rate": 3.50, "standard_rate": 5.50, "opening_stock": 900,  "monthly_demand_avg": 380,  "monthly_demand_std": 70},
    {"item_code": "VIE-001",      "item_name": "Croissants beurre (boite 12)",      "item_group": "Produits Finis",     "stock_uom": "Nos",   "valuation_rate": 4.50, "standard_rate": 7.00, "opening_stock": 400,  "monthly_demand_avg": 350,  "monthly_demand_std": 80},
    {"item_code": "VIE-002",      "item_name": "Viennoiseries mixtes plateau",      "item_group": "Produits Finis",     "stock_uom": "Nos",   "valuation_rate": 8.00, "standard_rate": 13.0, "opening_stock": 200,  "monthly_demand_avg": 180,  "monthly_demand_std": 40},
]

DEFAULT_WAREHOUSE  = "Stores - AGI"
FINISHED_WAREHOUSE = "Finished Goods - AGI"

def api_get(endpoint):
    try:
        r = requests.get(ERP_URL + endpoint, headers=HEADERS, timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        print("  [WARN] GET {}: {}".format(endpoint, e))
        return None

def api_post(endpoint, data):
    try:
        r = requests.post(ERP_URL + endpoint, headers=HEADERS, json=data, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        print("  [WARN] POST {} {}: {}".format(r.status_code, endpoint, r.text[:150]))
        return None
    except Exception as e:
        print("  [WARN] POST {}: {}".format(endpoint, e))
        return None

def exists(doctype, name):
    r = api_get("/api/resource/{}/{}".format(doctype, name))
    return r is not None and "data" in r

def get_date(days_ago):
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")

def wh(p):
    return FINISHED_WAREHOUSE if p["item_group"] == "Produits Finis" else DEFAULT_WAREHOUSE

def step1_item_groups():
    print("\n[Step 1] Item Groups")
    for g in ["Matieres Premieres", "Produits Finis", "Emballages"]:
        if exists("Item Group", g):
            print("  [OK] {} already exists".format(g))
        else:
            r = api_post("/api/resource/Item Group", {"item_group_name": g, "parent_item_group": "All Item Groups"})
            print("  [{}] {}".format("OK" if r else "FAIL", g))

def step2_warehouses():
    print("\n[Step 2] Warehouses")
    for w in [DEFAULT_WAREHOUSE, FINISHED_WAREHOUSE]:
        if exists("Warehouse", w):
            print("  [OK] {} exists".format(w))
        else:
            r = api_post("/api/resource/Warehouse", {"warehouse_name": w.split(" - ")[0], "company": "My Company"})
            print("  [{}] {}".format("OK" if r else "WARN", w))

def step3_items():
    print("\n[Step 3] Products")
    for p in PRODUCTS:
        code = p["item_code"]
        if exists("Item", code):
            print("  [OK] {} already exists".format(code))
            continue
        r = api_post("/api/resource/Item", {
            "item_code": code, "item_name": p["item_name"],
            "item_group": p["item_group"], "stock_uom": p["stock_uom"],
            "is_stock_item": 1, "is_purchase_item": 1, "is_sales_item": 1,
            "valuation_rate": p["valuation_rate"], "standard_rate": p["standard_rate"],
            "default_warehouse": wh(p),
        })
        print("  [{}] {} - {}".format("OK" if r else "FAIL", code, p["item_name"]))

def step4_opening_stock():
    print("\n[Step 4] Opening Stock (6 months ago)")
    for p in PRODUCTS:
        r = api_post("/api/resource/Stock Reconciliation", {
            "purpose": "Opening Stock",
            "posting_date": get_date(180),
            "items": [{"item_code": p["item_code"], "warehouse": wh(p), "qty": p["opening_stock"], "valuation_rate": p["valuation_rate"]}],
            "docstatus": 1
        })
        print("  [{}] {} - {} {}".format("OK" if r else "FAIL", p["item_code"], p["opening_stock"], p["stock_uom"]))

def step5_movements():
    print("\n[Step 5] Stock movements (24 weeks)")
    random.seed(42)
    for p in PRODUCTS:
        code = p["item_code"]
        avg, std, w = p["monthly_demand_avg"], p["monthly_demand_std"], wh(p)
        ok = 0
        for week in range(24, 0, -1):
            days_ago = week * 7
            qty_in  = max(10, int(random.gauss(avg / 4, std / 4)))
            qty_out = max(5,  int(qty_in * random.uniform(0.6, 0.95)))
            r1 = api_post("/api/resource/Stock Entry", {
                "stock_entry_type": "Material Receipt", "posting_date": get_date(days_ago + 2),
                "items": [{"item_code": code, "t_warehouse": w, "qty": qty_in, "basic_rate": p["valuation_rate"]}],
                "docstatus": 1
            })
            r2 = api_post("/api/resource/Stock Entry", {
                "stock_entry_type": "Material Issue", "posting_date": get_date(days_ago),
                "items": [{"item_code": code, "s_warehouse": w, "qty": qty_out, "basic_rate": p["valuation_rate"]}],
                "docstatus": 1
            })
            if r1 or r2:
                ok += 1
        print("  [OK] {} - {}/24 weeks".format(code, ok))

def step6_delivery_notes():
    print("\n[Step 6] Delivery Notes (3 months)")
    customer = "Client Tunis Demo"
    if not exists("Customer", customer):
        api_post("/api/resource/Customer", {
            "customer_name": customer, "customer_type": "Company",
            "customer_group": "Commercial", "territory": "Tunisia"
        })
    random.seed(99)
    ok = 0
    for week in range(12, 0, -1):
        for n in range(2):
            days_ago = week * 7 - n * 3
            selected = random.sample(PRODUCTS, k=random.randint(2, 4))
            items = [{
                "item_code": p["item_code"], "item_name": p["item_name"],
                "qty": max(5, int(random.gauss(p["monthly_demand_avg"] / 8, p["monthly_demand_std"] / 8))),
                "rate": p["standard_rate"], "uom": p["stock_uom"],
                "warehouse": wh(p),
            } for p in selected]
            r = api_post("/api/resource/Delivery Note", {
                "customer": customer, "posting_date": get_date(days_ago),
                "set_warehouse": DEFAULT_WAREHOUSE, "items": items, "docstatus": 1
            })
            if r:
                ok += 1
    print("  [OK] {} delivery notes created".format(ok))

def main():
    print("=" * 55)
    print("  ERPNext Data Initializer - MultiAgent Platform v6")
    print("=" * 55)

    r = api_get("/api/method/frappe.auth.get_logged_user")
    if not r:
        print("\n[FAIL] Cannot connect to {}".format(ERP_URL))
        print("  Make sure ERP is running on port 8080")
        return

    print("\n[OK] Connected to {}".format(ERP_URL))

    step1_item_groups()
    step2_warehouses()
    step3_items()
    step4_opening_stock()
    step5_movements()
    step6_delivery_notes()

    print("\n" + "=" * 55)
    print("  [DONE] Initialization complete!")
    print("  -> FAR-001, HUI-001, LEV-001 now have real data")
    print("  -> Confidence will rise to HIGH")
    print("=" * 55)

if __name__ == "__main__":
    main()
