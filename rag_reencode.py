"""Re-encode all existing decision_memory rows with sentence-transformers."""
import asyncio, sys
sys.path.insert(0, '/app')

async def main():
    from db.database import get_pool
    from core.rag_memory import embed_text, _to_pgvector, _get_model

    # Warm up model
    print("Loading sentence-transformers model...")
    model = _get_model()
    print("Model:", "sentence-transformers" if model != 'hash' else "hash fallback")

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, summary FROM decision_memory")
        print(f"Re-encoding {len(rows)} decisions...")

        ok = 0
        for row in rows:
            try:
                embedding = await embed_text(row['summary'])
                pg_vec = _to_pgvector(embedding)
                await conn.execute(
                    "UPDATE decision_memory SET embedding = $1::vector WHERE id = $2",
                    pg_vec, row['id']
                )
                ok += 1
            except Exception as e:
                print(f"  [FAIL] id={row['id']}: {e}")

        print(f"Done: {ok}/{len(rows)} re-encoded")

        # Test similarity
        print("\nTesting similarity for FAR-001...")
        test_emb = await embed_text("FAR-001 supply chain Tunis LOW urgency 280 days stock")
        test_vec = _to_pgvector(test_emb)
        results = await conn.fetch("""
            SELECT product_id, 1 - (embedding <=> $1::vector) AS similarity
            FROM decision_memory
            WHERE product_id = 'FAR-001'
            ORDER BY embedding <=> $1::vector
            LIMIT 3
        """, test_vec)
        for r in results:
            print(f"  {r['product_id']} similarity: {float(r['similarity']):.3f}")

asyncio.run(main())
