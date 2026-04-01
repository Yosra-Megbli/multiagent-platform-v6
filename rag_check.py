import asyncio, sys
sys.path.insert(0, '/app')

async def main():
    from db.database import get_pool, DEMO_MODE
    print("DEMO_MODE:", DEMO_MODE)

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Check table exists
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name='decision_memory')"
        )
        print("decision_memory table exists:", exists)

        if exists:
            count = await conn.fetchval("SELECT COUNT(*) FROM decision_memory")
            print("decision_memory rows:", count)

            # Check pgvector extension
            ext = await conn.fetchval("SELECT EXISTS (SELECT FROM pg_extension WHERE extname='vector')")
            print("pgvector extension:", ext)

            # Show columns
            cols = await conn.fetch(
                "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='decision_memory'"
            )
            print("Columns:", [dict(c) for c in cols])

asyncio.run(main())
