import asyncio, sys
sys.path.insert(0, '/app')

async def main():
    from db.database import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Check embeddings
        null_emb = await conn.fetchval("SELECT COUNT(*) FROM decision_memory WHERE embedding IS NULL")
        total = await conn.fetchval("SELECT COUNT(*) FROM decision_memory")
        print(f"Total: {total} | NULL embeddings: {null_emb}")

        # Sample rows
        rows = await conn.fetch(
            "SELECT tenant_id, product_id, sector, summary, created_at FROM decision_memory ORDER BY created_at DESC LIMIT 5"
        )
        print("\nRecent decisions:")
        for r in rows:
            print(f"  {r['product_id']} | {r['tenant_id']} | {r['sector']} | {str(r['created_at'])[:10]}")
            print(f"    summary: {str(r['summary'])[:80]}")

    # Test RAG retrieval
    print("\n--- Testing RAG retrieval for FAR-001 ---")
    from core.rag_memory import retrieve_similar_decisions
    results = await retrieve_similar_decisions(
        tenant_id="demo",
        product_id="FAR-001",
        sector="supply_chain",
        query_insights={"urgency": "LOW", "alerts": [], "stock_days": 280}
    )
    print("RAG results:", len(results), "found")
    for r in results:
        print(" -", r.get("product_id"), r.get("summary", "")[:60])

asyncio.run(main())
