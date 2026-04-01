"""
LLM — v5 GROQ (100% Gratuit)
==============================
Remplacement de OpenAI + Anthropic par Groq (gratuit).
Modèles utilisés :
  FULL : llama-3.3-70b-versatile  (meilleure qualité)
  MINI : mixtral-8x7b-32768       (plus rapide, fallback)
Inscription gratuite : https://console.groq.com
"""

import os
import logging
from enum import Enum
from groq import AsyncGroq

logger = logging.getLogger(__name__)


class LLMTier(str, Enum):
    MINI = "llama-3.1-8b-instant"   # FIX 9: mixtral-8x7b-32768 deprecated on Groq
    FULL = "llama-3.3-70b-versatile"


# Groq est gratuit — coûts toujours à 0
def _make_cost(model: str) -> dict:
    return {
        "model":         model,
        "provider":      "groq",
        "input_tokens":  0,
        "output_tokens": 0,
        "input_usd":     0.0,
        "output_usd":    0.0,
        "total_usd":     0.0,
        "fallback_used": False,
    }


async def call_llm(prompt, tier=LLMTier.MINI, max_tokens=500, temperature=0.2, json_mode=False):
    """
    Calls Groq LLM with automatic fallback chain. Returns (text, cost_info).
    Primary   : tier.value  (FULL = llama-3.3-70b, MINI = mixtral-8x7b)
    Fallback 1: gemma2-9b-it
    Fallback 2: llama-3.1-8b-instant
    """
    client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

    # Chaîne de fallback Groq
    if tier == LLMTier.FULL:
        # FIX 9: mixtral-8x7b-32768 removed from Groq — updated fallback chain
        models = ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "gemma2-9b-it"]
    else:
        models = ["llama-3.1-8b-instant", "gemma2-9b-it", "llama3-8b-8192"]

    last_error = None
    for model in models:
        try:
            logger.info("[LLM] Trying groq/%s", model)
            r = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = r.choices[0].message.content
            cost = _make_cost(model)
            cost["fallback_used"] = model != tier.value
            logger.info("[LLM] OK: groq/%s | $0.00 (gratuit)", model)
            return text, cost
        except Exception as e:
            last_error = e
            logger.warning("[LLM] Failed groq/%s: %s", model, str(e)[:80])

    return (
        f"⚠️ AI recommendation unavailable. Review alerts manually. Error: {str(last_error)[:200]}",
        {"model": "static_fallback", "provider": "none", "total_usd": 0.0, "fallback_used": True},
    )
