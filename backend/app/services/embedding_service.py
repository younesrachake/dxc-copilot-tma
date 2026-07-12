"""
Embedding Service — shared local multilingual embeddings + cross-encoder reranking.

Single lazy-loaded SentenceTransformer reused by:
  - RAG dense retrieval (ChromaDB embedding function)
  - Cross-encoder reranking of hybrid search candidates
  - Intent classification (embedding-similarity kNN)
  - Incident / knowledge-gap clustering
  - Semantic conversation search and semantic query cache

Models run on CPU. If sentence-transformers is not installed the service
degrades gracefully: `available` is False and callers fall back to their
previous behaviour (ChromaDB default embeddings, no reranking, keyword intents).
"""
import asyncio
import logging
import math
import os
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
CROSS_ENCODER_MODEL_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

# Hermetic-test / constrained-deploy switch: skip loading local models entirely
_DISABLE_LOCAL_ML = os.getenv("DISABLE_LOCAL_ML", "").lower() in ("1", "true", "yes")


class EmbeddingService:
    def __init__(self):
        self._model = None
        self._cross_encoder = None
        self._model_failed = _DISABLE_LOCAL_ML
        self._ce_failed = _DISABLE_LOCAL_ML
        self._model_lock = threading.Lock()
        self._ce_lock = threading.Lock()
        if _DISABLE_LOCAL_ML:
            logger.info("DISABLE_LOCAL_ML set — local embeddings and reranker disabled")

    # ── Model loading (lazy, thread-safe) ─────────────────────────

    def _get_model(self):
        if self._model is None and not self._model_failed:
            with self._model_lock:
                if self._model is None and not self._model_failed:
                    try:
                        from sentence_transformers import SentenceTransformer
                        logger.info("Loading embedding model %s ...", EMBEDDING_MODEL_NAME)
                        self._model = SentenceTransformer(EMBEDDING_MODEL_NAME, device="cpu")
                        logger.info("Embedding model %s loaded", EMBEDDING_MODEL_NAME)
                    except Exception as e:
                        self._model_failed = True
                        logger.warning(
                            "sentence-transformers unavailable (%s) — local embeddings disabled. "
                            "Install with: pip install sentence-transformers", e
                        )
        return self._model

    def _get_cross_encoder(self):
        if self._cross_encoder is None and not self._ce_failed:
            with self._ce_lock:
                if self._cross_encoder is None and not self._ce_failed:
                    try:
                        from sentence_transformers import CrossEncoder
                        logger.info("Loading cross-encoder %s ...", CROSS_ENCODER_MODEL_NAME)
                        self._cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL_NAME, device="cpu")
                        logger.info("Cross-encoder %s loaded", CROSS_ENCODER_MODEL_NAME)
                    except Exception as e:
                        self._ce_failed = True
                        logger.warning("Cross-encoder unavailable (%s) — reranking disabled", e)
        return self._cross_encoder

    @property
    def available(self) -> bool:
        return self._get_model() is not None

    @property
    def reranker_available(self) -> bool:
        return self._get_cross_encoder() is not None

    # ── Embeddings ────────────────────────────────────────────────

    def encode_sync(self, texts: List[str], normalize: bool = True):
        """Embed texts → np.ndarray of shape (len(texts), 384). Raises if model unavailable."""
        model = self._get_model()
        if model is None:
            raise RuntimeError("Embedding model unavailable")
        return model.encode(
            texts, normalize_embeddings=normalize,
            show_progress_bar=False, batch_size=32
        )

    async def encode(self, texts: List[str], normalize: bool = True):
        return await asyncio.to_thread(self.encode_sync, texts, normalize)

    # ── Cross-encoder reranking ───────────────────────────────────

    def rerank_sync(self, query: str, documents: List[str]) -> Optional[List[float]]:
        """Score (query, doc) pairs with the cross-encoder. Returns sigmoid scores in [0,1],
        or None when the cross-encoder is unavailable."""
        ce = self._get_cross_encoder()
        if ce is None or not documents:
            return None
        logits = ce.predict([(query, doc) for doc in documents], show_progress_bar=False)
        return [1.0 / (1.0 + math.exp(-float(x))) for x in logits]

    async def rerank(self, query: str, documents: List[str]) -> Optional[List[float]]:
        return await asyncio.to_thread(self.rerank_sync, query, documents)


class MultilingualEmbeddingFunction:
    """ChromaDB 0.4.x embedding function backed by the shared local model.

    The parameter MUST be named `input` — chromadb validates the signature.
    """

    def __call__(self, input):  # noqa: A002 — name required by chromadb
        return embedding_service.encode_sync(list(input), normalize=False).tolist()


# Singleton
embedding_service = EmbeddingService()
