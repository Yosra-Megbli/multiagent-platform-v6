"""
RAG MEMORY — v6 (100% Gratuit)
================================
Remplacement de OpenAI embeddings par sentence-transformers (local, gratuit).
Modèle : all-MiniLM-L6-v2 (léger, rapide, 384 dimensions)

Fonctionnement :
  store_decision_vector()      → encode + sauvegarde dans pgvector
  retrieve_similar_decisions() → recherche par similarité cosine
  build_rag_context()          → construit le contexte pour le LLM

Utilisé par : decision_agent (supply_chain)
"""

import json
import logging
import math

logger = logging.getLogger(__name__)

MAX_CONTEXT_TOKENS = 500
TOP_K              = 3
MIN_SIMILARITY     = 0.0
EMBED_DIM          = 384

_model = None

def _get_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info('[RAG] sentence-transformers model loaded')
        except Exception as e:
            logger.warning('[RAG] sentence-transformers unavailable, using hash fallback: %s', e)
            _model = 'hash'
    return _model


def _hash_embed(text: str) -> list[float]:
    import hashlib
    vec = [0.0] * EMBED_DIM
    for i, chunk in enumerate([text[j:j+8] for j in range(0, min(len(text), EMBED_DIM * 8), 8)]):
        h = int(hashlib.md5(chunk.encode()).hexdigest(), 16)
        vec[i % EMBED_DIM] += (h % 1000) / 1000.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


async def embed_text(text: str) -> list[float]:
    model = _get_model()
    if model == 'hash':
        return _hash_embed(text[:1000])
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(None, lambda: model.encode(text[:512]).tolist())
        return embedding
    except Exception as e:
        logger.warning('[RAG] embed_text failed, using hash: %s', e)
        return _hash_embed(text[:1000])


def _to_pgvector(embedding: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"


async def store_decision_vector(
    tenant_id: str, product_id: str, sector: str,
    decision_text: str, insights: dict, accuracy: float = None,
):
    """Encode la décision et la sauvegarde dans pgvector."""
    from db.database import get_pool

    summary = (
        f"Sector: {sector}. Product: {product_id}. "
        f"Urgency: {insights.get('urgency')}. "
        f"Alerts: {', '.join(insights.get('alerts', []))}. "
        f"Decision: {decision_text[:200]}"
    )

    try:
        embedding_list = await embed_text(summary)
        pg_vector      = _to_pgvector(embedding_list)
        pool           = await get_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO decision_memory
                  (tenant_id, product_id, sector, summary, decision_text,
                   insights, accuracy, embedding, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector, NOW())
                """,
                tenant_id, product_id, sector, summary,
                decision_text, json.dumps(insights),
                accuracy, pg_vector,
            )
        logger.info("[RAG] Stored: tenant=%s product=%s", tenant_id, product_id)
    except Exception as e:
        logger.warning("[RAG] Store failed: %s", str(e))


async def retrieve_similar_decisions(
    tenant_id: str, sector: str, query: str, top_k: int = TOP_K,
    product_id: str = None,
) -> list[dict]:
    """Recherche les décisions passées similaires à la situation actuelle."""
    from db.database import get_pool
    try:
        query_embedding = await embed_text(query)
        pg_vector       = _to_pgvector(query_embedding)
        pool            = await get_pool()

        async with pool.acquire() as conn:
            # First try: same product
            if product_id:
                rows = await conn.fetch(
                    """
                    SELECT summary, decision_text, accuracy, created_at, product_id,
                           1 - (embedding <=> $3::vector) AS similarity
                    FROM decision_memory
                    WHERE tenant_id = $1 AND sector = $2 AND product_id = $4
                    ORDER BY embedding <=> $3::vector
                    LIMIT $5
                    """,
                    tenant_id, sector, pg_vector, product_id, top_k,
                )
                if not rows:
                    # Fallback: any product same sector
                    rows = await conn.fetch(
                        """
                        SELECT summary, decision_text, accuracy, created_at, product_id,
                               1 - (embedding <=> $3::vector) AS similarity
                        FROM decision_memory
                        WHERE tenant_id = $1 AND sector = $2
                        ORDER BY embedding <=> $3::vector
                        LIMIT $4
                        """,
                        tenant_id, sector, pg_vector, top_k,
                    )
            else:
                rows = await conn.fetch(
                    """
                    SELECT summary, decision_text, accuracy, created_at, product_id,
                           1 - (embedding <=> $3::vector) AS similarity
                    FROM decision_memory
                    WHERE tenant_id = $1 AND sector = $2
                    ORDER BY embedding <=> $3::vector
                    LIMIT $4
                    """,
                    tenant_id, sector, pg_vector, top_k,
                )

        return [
            {
                "summary":    row["summary"],
                "decision":   row["decision_text"][:300],
                "accuracy":   row["accuracy"],
                "date":       row["created_at"].strftime("%Y-%m-%d"),
                "similarity": round(float(row["similarity"]), 3),
                "product_id": row.get("product_id", ""),
            }
            for row in rows
        ]
    except Exception as e:
        logger.warning("[RAG] Retrieve failed: %s", str(e))
        return []


async def build_rag_context(tenant_id: str, sector: str, current_situation: str, product_id: str = None) -> str:
    """Construit le bloc contexte historique à injecter dans le prompt LLM."""
    similar = await retrieve_similar_decisions(tenant_id, sector, current_situation, product_id=product_id)

    if not similar:
        return "No relevant historical decisions found."

    lines       = ["=== RELEVANT PAST DECISIONS (learned from experience) ==="]
    token_count = 0

    for past in similar:
        entry = (
            f"[{past['date']} | similarity={past['similarity']} | accuracy={past.get('accuracy','N/A')}]\n"
            f"Situation: {past['summary'][:150]}\n"
            f"Decision: {past['decision'][:200]}\n"
        )
        token_count += len(entry) // 4
        if token_count > MAX_CONTEXT_TOKENS:
            break
        lines.append(entry)

    lines.append("=== END HISTORICAL CONTEXT ===")
    return "\n".join(lines)
