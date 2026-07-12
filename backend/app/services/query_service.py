"""
Query Service — semantic answer cache + LLM query expansion.

Semantic cache: embeds incoming questions and returns a cached reply when a
previous question is close enough (cosine ≥ threshold) and fresh (TTL). Only
plain questions (no file, non-agent path) are cached; the cache is wiped
whenever the knowledge base changes (hooked from rag_service).

Query expansion (default off): one fast LLM call rewrites the question into
2 French reformulations; callers search all variants and merge candidates.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)

MAX_CACHE_ENTRIES = 500


class QueryService:
    def __init__(self):
        self._cache: List[dict] = []   # {vec, query, reply, sources, citations, created_at}
        self._lock = asyncio.Lock()

    # ── Semantic cache ────────────────────────────────────────────

    async def get_cached(
        self, query: str, threshold: float = 0.93, ttl_hours: float = 24
    ) -> Optional[dict]:
        """Return {reply, sources, citations, matched_query} for a near-duplicate
        fresh question, else None."""
        try:
            from app.services.embedding_service import embedding_service
            if not embedding_service.available or not self._cache:
                return None
            vec = (await embedding_service.encode([query[:500]], normalize=True))[0]
        except Exception:
            return None

        cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
        best, best_sim = None, 0.0
        async with self._lock:
            self._cache = [e for e in self._cache if e["created_at"] >= cutoff]
            for entry in self._cache:
                sim = float(entry["vec"] @ vec)
                if sim > best_sim:
                    best, best_sim = entry, sim
        if best is not None and best_sim >= threshold:
            logger.info("Semantic cache hit (%.3f) for: %.60s", best_sim, query)
            return {
                "reply": best["reply"],
                "sources": best["sources"],
                "citations": best["citations"],
                "matched_query": best["query"],
            }
        return None

    async def put(
        self, query: str, reply: str,
        sources: Optional[list] = None, citations: Optional[list] = None,
    ) -> None:
        try:
            from app.services.embedding_service import embedding_service
            if not embedding_service.available:
                return
            vec = (await embedding_service.encode([query[:500]], normalize=True))[0]
        except Exception:
            return
        async with self._lock:
            self._cache.append({
                "vec": vec,
                "query": query[:500],
                "reply": reply,
                "sources": sources or [],
                "citations": citations or [],
                "created_at": datetime.now(timezone.utc),
            })
            if len(self._cache) > MAX_CACHE_ENTRIES:
                self._cache = self._cache[-MAX_CACHE_ENTRIES:]

    def invalidate_cache(self) -> None:
        count = len(self._cache)
        self._cache = []
        if count:
            logger.info("Semantic cache invalidated (%d entries)", count)

    # ── Query expansion ───────────────────────────────────────────

    async def expand_query(self, query: str) -> List[str]:
        """Rewrite the question into up to 2 French reformulations (may return [])."""
        from app.services.llm_service import llm_service
        if not llm_service.available:
            return []
        messages = [
            {"role": "system", "content": (
                "Reformule la question de l'utilisateur en 2 variantes françaises qui "
                "utilisent un vocabulaire différent mais gardent le même sens (contexte : "
                "maintenance applicative / incidents IT). Réponds UNIQUEMENT avec un tableau "
                'JSON de 2 chaînes, par exemple: ["variante 1", "variante 2"]'
            )},
            {"role": "user", "content": query[:500]},
        ]
        try:
            msg = await llm_service.chat_completion(
                messages, fast=True, max_tokens=120, temperature=0.5, timeout=8.0
            )
            content = (msg.content or "").strip()
            match = re.search(r"\[.*\]", content, re.DOTALL)
            if not match:
                return []
            variants = json.loads(match.group(0))
            return [str(v)[:500] for v in variants if isinstance(v, str) and v.strip()][:2]
        except Exception as e:
            logger.warning("Query expansion failed: %s", e)
            return []


# Singleton
query_service = QueryService()
