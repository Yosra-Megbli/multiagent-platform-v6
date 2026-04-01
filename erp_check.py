import asyncio, sys
sys.path.insert(0, '/app')
from core.erpuiux_connector import ERPUIUXConnector

async def check():
    c = ERPUIUXConnector()
    print("=== ERP CONNECTION ===")
    print("URL:", c.base_url)
    print("Auth:", "OK" if c.headers.get("Authorization") else "MISSING")
    ok = await c.ping()
    print("Ping:", "OK" if ok else "FAIL")

    print("\n=== STOCK ===")
    for code in ["FAR-001", "HARISSA-140G", "HUI-001", "LEV-001", "SARDINE-125G"]:
        s = await c.get_stock(code)
        print(f"  {code}: qty={s.get('actual_qty')} status={s.get('status')} source={s.get('source')}")

    print("\n=== SALES (last 30d) ===")
    for code in ["FAR-001", "HARISSA-140G", "HUI-001", "LEV-001", "SARDINE-125G"]:
        sa = await c.get_sales_last_30_days(code)
        print(f"  {code}: qty={sa.get('qty_sold_30d')} deliveries={sa.get('delivery_count')} source={sa.get('source')}")

asyncio.run(check())
