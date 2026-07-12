"""
Prometheus metrics — custom business/AI metrics for the RAG pipeline.

Degrades to no-ops when prometheus_client is not installed, so dev
environments without the observability extras keep working unchanged.
"""
import logging

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Histogram

    RAG_ROUTING = Counter(
        "dxc_rag_routing_total",
        "Chat turns by RAG routing decision",
        ["routing"],  # kb_primary | kb_hint | groq_only | cache
    )
    RAG_LATENCY = Histogram(
        "dxc_rag_latency_seconds",
        "RAG retrieval latency (hybrid search + rerank)",
        buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
    )
    INTENTS = Counter(
        "dxc_intent_total",
        "Classified intents of user messages",
        ["intent"],
    )
    LLM_ERRORS = Counter(
        "dxc_llm_errors_total",
        "LLM call failures (timeouts and API errors)",
        ["provider", "kind"],  # kind: timeout | api_error
    )
    SEMANTIC_CACHE_HITS = Counter(
        "dxc_semantic_cache_hits_total",
        "Chat replies served from the semantic answer cache",
    )
    AVAILABLE = True
except ImportError:  # pragma: no cover — observability extras not installed
    class _Noop:
        def labels(self, *a, **kw):
            return self

        def inc(self, *a, **kw):
            pass

        def observe(self, *a, **kw):
            pass

    RAG_ROUTING = RAG_LATENCY = INTENTS = LLM_ERRORS = SEMANTIC_CACHE_HITS = _Noop()
    AVAILABLE = False
    logger.info("prometheus_client not installed — metrics are no-ops")


def record_chat_turn(routing: str, intent: str | None, rag_latency_ms: int) -> None:
    """Single hook called from the chat analytics path."""
    RAG_ROUTING.labels(routing=routing).inc()
    INTENTS.labels(intent=intent or "unknown").inc()
    if routing == "cache":
        SEMANTIC_CACHE_HITS.inc()
    elif rag_latency_ms > 0:
        RAG_LATENCY.observe(rag_latency_ms / 1000.0)
