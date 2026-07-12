"""
Conversation Index Service — semantic search over past chat messages.

Maintains a second ChromaDB collection ("dxc_conversations") in the same
persistent store as the knowledge base, embedded with the shared multilingual
model. Every user/bot message is indexed at save time; users can then search
their own history semantically ("cette conversation sur la corruption Redis").

Privacy: every query is filtered server-side on user_id; deleting a session
also removes its vectors.
"""
import asyncio
import logging
from typing import List

from sqlalchemy import select

logger = logging.getLogger(__name__)

COLLECTION_NAME = "dxc_conversations"
MAX_TEXT_CHARS = 1000


class ConversationIndexService:
    def __init__(self):
        self._collection = None
        self._failed = False
        self._init_lock = asyncio.Lock()

    def _get_collection(self):
        if self._collection is not None or self._failed:
            return self._collection
        try:
            from app.services.rag_service import rag_service
            from app.services.embedding_service import (
                embedding_service, EMBEDDING_MODEL_NAME, MultilingualEmbeddingFunction
            )
            client = rag_service._client
            if client is None or not embedding_service.available:
                self._failed = True
                return None
            self._collection = client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine", "embedding_model": EMBEDDING_MODEL_NAME},
                embedding_function=MultilingualEmbeddingFunction(),
            )
            logger.info("Conversation index ready (%d messages)", self._collection.count())
        except Exception as e:
            self._failed = True
            logger.warning("Conversation index unavailable: %s", e)
        return self._collection

    # ── Indexing ──────────────────────────────────────────────────

    async def index_message(
        self, message_id: int, session_id: str, user_id: int, sender: str, text: str
    ) -> None:
        """Fire-and-forget indexing of a chat message (errors only logged)."""
        text = (text or "").strip()
        if not text:
            return
        collection = self._get_collection()
        if collection is None:
            return
        try:
            await asyncio.to_thread(
                collection.upsert,
                ids=[f"msg-{message_id}"],
                documents=[text[:MAX_TEXT_CHARS]],
                metadatas=[{
                    "session_id": session_id,
                    "user_id": int(user_id),
                    "sender": sender,
                    "message_id": int(message_id),
                }],
            )
        except Exception as e:
            logger.warning("Conversation indexing failed for msg %s: %s", message_id, e)

    async def delete_session(self, session_id: str) -> None:
        collection = self._get_collection()
        if collection is None:
            return
        try:
            await asyncio.to_thread(collection.delete, where={"session_id": session_id})
        except Exception as e:
            logger.warning("Conversation index cleanup failed for session %s: %s", session_id, e)

    # ── Search ────────────────────────────────────────────────────

    async def search(self, user_id: int, query: str, n_results: int = 5) -> List[dict]:
        """Semantic search over the caller's own messages."""
        collection = self._get_collection()
        if collection is None or not query.strip():
            return []
        try:
            results = await asyncio.to_thread(
                collection.query,
                query_texts=[query[:500]],
                n_results=n_results,
                where={"user_id": int(user_id)},
                include=["documents", "distances", "metadatas"],
            )
        except Exception as e:
            logger.warning("Conversation search failed: %s", e)
            return []
        docs = results.get("documents", [[]])[0]
        dists = results.get("distances", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        hits = []
        for doc, dist, meta in zip(docs, dists, metas):
            hits.append({
                "session_id": (meta or {}).get("session_id"),
                "message_id": (meta or {}).get("message_id"),
                "sender": (meta or {}).get("sender"),
                "snippet": doc[:300],
                "score": round(max(0.0, min(1.0, 1.0 - dist / 2.0)), 4),
            })
        return hits

    # ── One-time backfill of pre-existing messages ────────────────

    async def backfill(self, db) -> int:
        """Index all existing messages once (guarded by platform_settings flag)."""
        from app.models.db import Message, Session
        from app.services.agent_service import _get_setting, _merge_setting

        collection = self._get_collection()
        if collection is None:
            return 0
        async with self._init_lock:
            row = await _get_setting(db, "conversation_index")
            if row and (row.data or {}).get("backfilled"):
                return 0
            sessions = {
                str(s.id): int(str(s.user_id))
                for s in (await db.execute(select(Session))).scalars().all()
            }
            messages = (await db.execute(select(Message))).scalars().all()
            count = 0
            batch_ids, batch_docs, batch_metas = [], [], []
            for m in messages:
                text = (str(m.text) or "").strip()
                session_id = str(m.session_id)
                if not text or session_id not in sessions:
                    continue
                batch_ids.append(f"msg-{m.id}")
                batch_docs.append(text[:MAX_TEXT_CHARS])
                batch_metas.append({
                    "session_id": session_id,
                    "user_id": sessions[session_id],
                    "sender": str(m.sender),
                    "message_id": int(str(m.id)),
                })
                if len(batch_ids) >= 100:
                    await asyncio.to_thread(
                        collection.upsert, ids=batch_ids, documents=batch_docs, metadatas=batch_metas
                    )
                    count += len(batch_ids)
                    batch_ids, batch_docs, batch_metas = [], [], []
            if batch_ids:
                await asyncio.to_thread(
                    collection.upsert, ids=batch_ids, documents=batch_docs, metadatas=batch_metas
                )
                count += len(batch_ids)
            await _merge_setting(db, "conversation_index", {"backfilled": True})
            await db.commit()
            if count:
                logger.info("Conversation index backfill: %d messages indexed", count)
            return count


# Singleton
conversation_index_service = ConversationIndexService()
