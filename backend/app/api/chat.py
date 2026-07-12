import uuid
import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, text
from jose import jwt
from typing import Optional, List, Tuple

from app.core.database import get_db, async_session
from app.core.config import JWT_SECRET, JWT_ALGORITHM
from app.models.db import Session, Message, Incident
from app.models.schemas import ChatResponse, SessionResponse, MessageResponse
from app.services.ocr_service import ocr_service
from app.services.stt_service import stt_service
from app.services.rag_service import rag_service
from app.services.llm_service import llm_service
from app.services.agent_service import kb_enabled, rag_settings
from app.services.intent_service import (
    intent_service, INTENT_INCIDENT, INTENT_JIRA, INTENT_QUESTION, INTENT_SMALLTALK
)
from app.services.chat_agent_service import chat_agent_service
from app.services.query_service import query_service
from app.services.conversation_index_service import conversation_index_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

INCIDENT_KEYWORDS = [
    "erreur", "error", "panne", "bug", "incident",
    "problème", "dysfonctionnement", "crash", "timeout", "exception"
]

# ── Jira ticket intent detection (keyword fallback + RG2 labels) ──
JIRA_CRITICAL_KEYWORDS = ["critique", "urgent", "bloquant", "p1", "production down", "prod down"]

# Below this intent-classifier confidence, keyword detection is also consulted
INTENT_FALLBACK_CONFIDENCE = 0.5

CITATION_RE = re.compile(r"\[(\d+)\]")


def _detect_jira_intent(message: str) -> bool:
    """True when the user asks to create/open a Jira (or similar) ticket."""
    m = message.lower()
    if "jira" in m or "servicenow" in m or "smax" in m:
        return True
    if "ticket" in m:
        return True
    return ("créer" in m or "creer" in m or "ouvrir" in m) and ("bug" in m or "issue" in m)


def _build_jira_draft(message: str, recent_msgs: list, detected_type: Optional[str]) -> dict:
    """Build a pre-filled Jira ticket draft from the message and conversation context."""
    m = message.lower()
    if any(kw in m for kw in JIRA_CRITICAL_KEYWORDS):
        priority = "Critique"
    elif detected_type or any(kw in m for kw in INCIDENT_KEYWORDS):
        priority = "Haute"
    else:
        priority = "Moyenne"

    summary = message.strip().replace("\n", " ")
    if len(summary) > 80:
        summary = summary[:77] + "..."

    context_lines = []
    for msg in recent_msgs:
        role = "Utilisateur" if msg.sender == "user" else "Copilot"
        text = msg.text[:200] + ("..." if len(msg.text) > 200 else "")
        context_lines.append(f"[{role}] {text}")
    context = "\n\n".join(context_lines) if context_lines else message

    return {
        "summary": summary,
        "description": (
            "=== Contexte des derniers échanges ===\n\n"
            f"{context}\n\n"
            "=== Détails techniques ===\n"
            f"Type d'incident détecté : {detected_type or 'non catégorisé'}\n"
            "Environnement : Production\n"
            "Impact : à préciser"
        ),
        "type": "Incident",
        "priority": priority,
        "project": "TMA",
        "assignee": "Équipe TMA",
    }


async def get_current_user_id(request: Request) -> int:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Non authentifié")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return int(str(payload.get("sub", 0)))
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide")


# ── Turn helpers (shared by blocking and streaming endpoints) ─────

async def _ensure_session(db: AsyncSession, user_id: int, session_id: Optional[str], message: str) -> str:
    if not session_id:
        session_id = str(uuid.uuid4())
        db.add(Session(id=session_id, user_id=user_id, title=message[:50]))
        await db.flush()
        return session_id
    # Verify the provided session belongs to the current user (prevent session hijacking)
    existing = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    if not existing.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Accès à cette session refusé")
    return session_id


async def _classify_message(message: str) -> Tuple[str, float, Optional[str], bool, bool, bool]:
    """Classify with the embedding kNN model; consult keywords at low confidence.

    Returns (intent, confidence, detected_type, is_incident, is_jira, is_smalltalk)."""
    intent, conf = await intent_service.classify(message)

    msg_lower = message.lower()
    detected_type = next((kw for kw in INCIDENT_KEYWORDS if kw in msg_lower), None)
    kw_jira = _detect_jira_intent(message)

    if intent is None:
        # Classifier unavailable — legacy keyword behaviour
        if kw_jira:
            return INTENT_JIRA, 0.0, detected_type, detected_type is not None, True, False
        if detected_type:
            return INTENT_INCIDENT, 0.0, detected_type, True, False, False
        return INTENT_QUESTION, 0.0, None, False, False, False

    is_jira = intent == INTENT_JIRA
    is_incident = intent == INTENT_INCIDENT
    is_smalltalk = intent == INTENT_SMALLTALK
    if conf < INTENT_FALLBACK_CONFIDENCE:
        is_jira = is_jira or kw_jira
        is_incident = is_incident or (detected_type is not None and not is_jira)
        if is_jira or is_incident:
            is_smalltalk = False
    if is_incident and detected_type is None:
        detected_type = "incident"
    return intent, conf, detected_type, is_incident, is_jira, is_smalltalk


async def _do_rag(
    message: str, kb_on: bool, skip: bool, rag_cfg: dict
) -> Tuple[List[str], List[float], List[str], int]:
    """Hybrid search (+ optional query expansion). Returns (docs, scores, sources, latency_ms)."""
    if not kb_on or skip:
        return [], [], [], 0
    start = time.monotonic()
    rerank = bool(rag_cfg.get("reranker_enabled", True))
    docs, scores, sources = await rag_service.search(message, n_results=3, rerank=rerank)

    if rag_cfg.get("expansion_enabled"):
        try:
            variants = await query_service.expand_query(message)
            best = {src: (doc, score) for doc, score, src in zip(docs, scores, sources)}
            for variant in variants:
                v_docs, v_scores, v_sources = await rag_service.search(
                    variant, n_results=3, rerank=rerank
                )
                for doc, score, src in zip(v_docs, v_scores, v_sources):
                    if src not in best or score > best[src][1]:
                        best[src] = (doc, score)
            ranked = sorted(best.items(), key=lambda kv: kv[1][1], reverse=True)[:3]
            docs = [doc for _, (doc, _) in ranked]
            scores = [score for _, (_, score) in ranked]
            sources = [src for src, _ in ranked]
        except Exception as e:
            logger.warning("Query expansion merge failed: %s", e)

    latency_ms = int((time.monotonic() - start) * 1000)
    return docs, scores, sources, latency_ms


async def _track_incident(db: AsyncSession, detected_type: Optional[str], is_incident: bool) -> Optional[dict]:
    """RG2 recurring-incident tracking. Returns a guide card at ≥3 occurrences."""
    if not (is_incident and detected_type):
        return None
    result = await db.execute(select(Incident).where(Incident.incident_type == detected_type))
    incident = result.scalar_one_or_none()
    if not incident:
        db.add(Incident(incident_type=detected_type, count=1))
        return None
    incident.count = (incident.count or 0) + 1  # type: ignore[assignment]
    incident.last_seen = datetime.now(timezone.utc)  # type: ignore[assignment]
    if incident.count < 3:
        return None
    return {
        "title": f"Guide RG2 — {detected_type.capitalize()}",
        "incident_type": detected_type,
        "occurrences": incident.count,
        "steps": [
            "Vérifier les logs du service concerné",
            "Analyser les métriques et la charge système",
            "Redémarrer le service si nécessaire",
            "Vérifier la base de données et les connexions",
            "Contacter l'équipe de support N2 si le problème persiste"
        ],
        "recommendation": "Incident récurrent détecté. Envisagez une analyse de cause racine."
    }


def _extract_citations(reply: str, sources: List[str]) -> Tuple[str, Optional[List[dict]]]:
    """Map [n] markers in the reply to sources; strip out-of-range markers."""
    if not sources:
        return CITATION_RE.sub("", reply), None
    cited: List[dict] = []
    seen = set()

    def _check(match):
        n = int(match.group(1))
        if 1 <= n <= len(sources):
            if n not in seen:
                seen.add(n)
                cited.append({"index": n, "source": sources[n - 1]})
            return match.group(0)
        return ""  # out-of-range marker — strip it

    reply = CITATION_RE.sub(_check, reply)
    cited.sort(key=lambda c: c["index"])
    return reply, (cited or None)


def _routing_label(top_score: float, rag_cfg: dict) -> str:
    if top_score >= rag_cfg["t_high"]:
        return "kb_primary"
    if top_score >= rag_cfg["t_low"]:
        return "kb_hint"
    return "groq_only"


async def _log_analytics(
    db: AsyncSession, message: str, top_score: float, routing: str,
    sources: List[str], latency_ms: int, bot_message_id: Optional[int],
    intent: Optional[str], grounded: Optional[bool],
) -> None:
    try:
        from app.core.metrics import record_chat_turn
        record_chat_turn(routing, intent, latency_ms)
    except Exception:
        pass
    try:
        query_hash = hashlib.sha256(message.encode()).hexdigest()[:16]
        used_sources = sources if routing not in ("groq_only", "cache") else []
        await db.execute(
            text(
                "INSERT INTO rag_analytics "
                "(query_hash, query_text, top_score, routing, doc_ids, latency_ms, bot_message_id, intent, grounded) "
                "VALUES (:qh, :qt, :ts, :rt, :di, :lm, :bm, :it, :gr)"
            ),
            {
                "qh": query_hash,
                "qt": message[:500],
                "ts": round(top_score, 4),
                "rt": routing,
                "di": json.dumps(used_sources),
                "lm": latency_ms,
                "bm": bot_message_id,
                "it": intent,
                "gr": (1 if grounded else 0) if grounded is not None else None,
            }
        )
    except Exception as _analytics_err:
        logger.warning("RAG analytics insert failed: %s", _analytics_err)


def _index_messages_async(session_id: str, user_id: int, *messages: Message) -> None:
    """Fire-and-forget conversation indexing (needs flushed message ids)."""
    for m in messages:
        try:
            asyncio.create_task(conversation_index_service.index_message(
                message_id=int(str(m.id)), session_id=session_id,
                user_id=user_id, sender=str(m.sender), text=str(m.text),
            ))
        except Exception:
            pass


# ── Main chat endpoint (blocking) ─────────────────────────────────

@router.post("", response_model=ChatResponse)
async def chat(
    request: Request,
    message: str = Form(...),
    session_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db)
):
    user_id = await get_current_user_id(request)
    session_id = await _ensure_session(db, user_id, session_id, message)

    rag_cfg = await rag_settings(db)
    kb_on = await kb_enabled(db)
    intent, intent_conf, detected_type, is_incident, is_jira, is_smalltalk = \
        await _classify_message(message)
    use_agent = (is_jira or is_incident) and llm_service.available

    # ── Semantic cache (plain questions only, no file) ─────────
    if (
        rag_cfg["cache_enabled"] and file is None
        and intent == INTENT_QUESTION and not use_agent
    ):
        cached = await query_service.get_cached(
            message, threshold=rag_cfg["cache_threshold"], ttl_hours=rag_cfg["cache_ttl_hours"]
        )
        if cached:
            user_msg = Message(session_id=session_id, sender="user", text=message)
            bot_msg = Message(
                session_id=session_id, sender="bot", text=cached["reply"]
            )
            db.add_all([user_msg, bot_msg])
            await db.flush()
            await _log_analytics(
                db, message, 0.0, "cache", [], 0,
                int(str(bot_msg.id)), intent, None
            )
            await db.commit()
            _index_messages_async(session_id, user_id, user_msg, bot_msg)
            return ChatResponse(
                reply=cached["reply"], session_id=session_id,
                sources=cached["sources"] or None,
                citations=cached["citations"] or None,
                intent=intent, cached=True,
            )

    # ── Process file + RAG in parallel ─────────────────────────
    file_context = ""
    attachments_meta = None
    _kb_ingested: dict = {}   # {filename: chunks} populated if file ingested into KB

    _KB_INGEST_EXTS = {"pdf", "txt", "md", "docx", "csv"}

    async def process_file():
        if not file:
            return ""
        file_bytes = await file.read()
        content_type = file.content_type or ""
        # Sanitize filename — strip path components to prevent path traversal
        from pathlib import Path
        filename = Path(file.filename or "unknown").name or "unknown"
        nonlocal attachments_meta
        attachments_meta = {"filename": filename, "content_type": content_type, "size": len(file_bytes)}
        from app.services.stt_service import SUPPORTED_AUDIO_TYPES as AUDIO_TYPES
        if content_type in AUDIO_TYPES:
            error = stt_service.validate_audio(content_type, len(file_bytes))
            if error:
                raise HTTPException(status_code=400, detail=error)
            return await stt_service.transcribe(file_bytes, content_type, filename)
        else:
            error = ocr_service.validate_file(content_type, len(file_bytes))
            if error:
                raise HTTPException(status_code=400, detail=error)
            extracted = await ocr_service.extract_text(file_bytes, content_type, filename)

            # Auto-ingest document types into the KB so all future queries benefit
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if kb_on and ext in _KB_INGEST_EXTS and not content_type.startswith("image/"):
                try:
                    if ext == "pdf":
                        n = await rag_service.ingest_pdf(file_bytes, filename)
                    elif ext == "docx":
                        n = await rag_service.ingest_docx(file_bytes, filename)
                    elif ext == "csv":
                        n = await rag_service.ingest_csv(file_bytes, filename)
                    else:
                        raw_text = file_bytes.decode("utf-8", errors="ignore")
                        n = await rag_service.ingest_text(raw_text, filename)
                    if n > 0:
                        _kb_ingested["filename"] = filename
                        _kb_ingested["chunks"] = n
                        logger.info("Auto-KB: ingested %d chunks from chat-uploaded %s", n, filename)
                except Exception as _ingest_err:
                    logger.warning("Auto-KB ingest failed for %s: %s", filename, _ingest_err)

            return extracted

    file_context, rag_result = await asyncio.gather(
        process_file(),
        _do_rag(message, kb_on, skip=is_smalltalk, rag_cfg=rag_cfg)
    )
    context_docs, context_scores, context_sources, rag_latency_ms = rag_result

    # ── Save user message ─────────────────────────────────────
    user_msg = Message(
        session_id=session_id, sender="user", text=message,
        attachments=attachments_meta
    )
    db.add(user_msg)
    await db.flush()

    # ── Track incidents (RG2) ─────────────────────────────────
    guide_card = await _track_incident(db, detected_type, is_incident)

    # ── Generate: agent loop for incident/jira intents, else single shot ──
    jira_ticket = None
    if use_agent:
        agent_result = await chat_agent_service.run(
            message, session_id, db,
            file_context=file_context if file_context else None,
            kb_on=kb_on,
        )
        bot_reply = agent_result["reply"]
        jira_ticket = agent_result["jira_ticket"]
        # KB attribution comes from the agent's own search_kb calls
        if agent_result["sources"]:
            context_docs = None  # docs already consumed inside the loop
            context_sources = agent_result["sources"]
            context_scores = agent_result["scores"]
        if is_jira and jira_ticket is None:
            # Safety net: the model didn't call draft_jira_ticket
            recent = (await db.execute(
                select(Message).where(Message.session_id == session_id)
                .order_by(Message.created_at.desc()).limit(4)
            )).scalars().all()
            jira_ticket = _build_jira_draft(message, list(reversed(recent)), detected_type)
    else:
        bot_reply = await llm_service.generate_response(
            user_message=message,
            context_docs=context_docs if context_docs else None,
            context_scores=context_scores if context_scores else None,
            context_sources=context_sources if context_sources else None,
            file_context=file_context if file_context else None,
            timeout=45.0,
            t_low=rag_cfg["t_low"],
            t_high=rag_cfg["t_high"],
        )

    # ── Routing decision + citations + groundedness ────────────
    top_score = max(context_scores) if context_scores else 0.0
    routing = _routing_label(top_score, rag_cfg)
    response_sources = context_sources if routing != "groq_only" else []

    citations = None
    if response_sources:
        bot_reply, citations = _extract_citations(bot_reply, response_sources)

    grounded = None
    if rag_cfg["evaluator_enabled"] and routing != "groq_only" and context_docs:
        grounded = await llm_service.evaluate_groundedness(bot_reply, context_docs)

    # Append KB ingestion confirmation if a document was auto-ingested
    if _kb_ingested.get("filename"):
        bot_reply += (
            f'\n\n📚 *Le document **"{_kb_ingested["filename"]}"** a été automatiquement ajouté à la '
            f'base de connaissances ({_kb_ingested["chunks"]} chunk(s)). '
            f'Il sera utilisé comme référence dans toutes les prochaines conversations.*'
        )

    # ── Save bot message + analytics ──────────────────────────
    bot_msg = Message(
        session_id=session_id, sender="bot", text=bot_reply,
        guide_card=guide_card
    )
    db.add(bot_msg)
    await db.flush()
    await _log_analytics(
        db, message, top_score, routing, context_sources, rag_latency_ms,
        int(str(bot_msg.id)), intent, grounded
    )
    await db.commit()
    _index_messages_async(session_id, user_id, user_msg, bot_msg)

    # ── Populate semantic cache ────────────────────────────────
    if (
        rag_cfg["cache_enabled"] and file is None and not use_agent
        and intent == INTENT_QUESTION and llm_service.available
        and not bot_reply.startswith(("⏱️", "⚠️"))
    ):
        await query_service.put(message, bot_reply, response_sources, citations)

    return ChatResponse(
        reply=bot_reply,
        session_id=session_id,
        guide_card=guide_card,
        sources=response_sources if response_sources else None,
        jira_ticket=jira_ticket,
        citations=citations,
        grounded=grounded,
        intent=intent,
    )


# ── Streaming chat endpoint (SSE over POST) ───────────────────────

def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/stream")
async def chat_stream(
    request: Request,
    message: str = Form(...),
    session_id: Optional[str] = Form(None),
):
    """Token-by-token chat. Events: status → token* → meta → done.
    File uploads use the blocking POST /api/chat endpoint."""
    user_id = await get_current_user_id(request)

    async def event_stream():
        # Own session: dependency-injected sessions may close before a
        # StreamingResponse finishes on newer FastAPI versions.
        async with async_session() as db:
            try:
                sid = await _ensure_session(db, user_id, session_id, message)
            except HTTPException as e:
                yield _sse("error", {"detail": e.detail})
                return

            rag_cfg = await rag_settings(db)
            kb_on = await kb_enabled(db)
            intent, intent_conf, detected_type, is_incident, is_jira, is_smalltalk = \
                await _classify_message(message)
            use_agent = (is_jira or is_incident) and llm_service.available

            # ── Semantic cache short-circuit ──────────────────
            if (
                rag_cfg["cache_enabled"] and intent == INTENT_QUESTION and not use_agent
            ):
                cached = await query_service.get_cached(
                    message, threshold=rag_cfg["cache_threshold"],
                    ttl_hours=rag_cfg["cache_ttl_hours"]
                )
                if cached:
                    user_msg = Message(session_id=sid, sender="user", text=message)
                    bot_msg = Message(session_id=sid, sender="bot", text=cached["reply"])
                    db.add_all([user_msg, bot_msg])
                    await db.flush()
                    await _log_analytics(db, message, 0.0, "cache", [], 0,
                                         int(str(bot_msg.id)), intent, None)
                    await db.commit()
                    _index_messages_async(sid, user_id, user_msg, bot_msg)
                    yield _sse("token", {"text": cached["reply"]})
                    yield _sse("meta", {
                        "session_id": sid, "sources": cached["sources"] or None,
                        "citations": cached["citations"] or None,
                        "guide_card": None, "jira_ticket": None,
                        "grounded": None, "intent": intent, "cached": True,
                    })
                    yield _sse("done", {})
                    return

            if use_agent:
                yield _sse("status", {"text": "Recherche dans la base de connaissances…"})

            context_docs, context_scores, context_sources, rag_latency_ms = await _do_rag(
                message, kb_on, skip=is_smalltalk, rag_cfg=rag_cfg
            )

            user_msg = Message(session_id=sid, sender="user", text=message)
            db.add(user_msg)
            await db.flush()

            guide_card = await _track_incident(db, detected_type, is_incident)

            jira_ticket = None
            chunks: List[str] = []

            async def persist(bot_reply: str):
                """Persist the (possibly partial) reply. Returns the meta payload."""
                nonlocal context_docs, context_sources, context_scores
                if not bot_reply.strip():
                    # Nothing generated: keep the user message, no orphan bot message
                    await db.commit()
                    return None
                top_score = max(context_scores) if context_scores else 0.0
                routing = _routing_label(top_score, rag_cfg)
                response_sources = context_sources if routing != "groq_only" else []
                citations = None
                if response_sources:
                    bot_reply, citations = _extract_citations(bot_reply, response_sources)
                grounded = None
                if rag_cfg["evaluator_enabled"] and routing != "groq_only" and context_docs:
                    grounded = await llm_service.evaluate_groundedness(bot_reply, context_docs)

                bot_msg = Message(session_id=sid, sender="bot", text=bot_reply, guide_card=guide_card)
                db.add(bot_msg)
                await db.flush()
                await _log_analytics(
                    db, message, top_score, routing, context_sources,
                    rag_latency_ms, int(str(bot_msg.id)), intent, grounded
                )
                await db.commit()
                _index_messages_async(sid, user_id, user_msg, bot_msg)

                if (
                    rag_cfg["cache_enabled"] and not use_agent
                    and intent == INTENT_QUESTION and llm_service.available
                    and not bot_reply.startswith(("⏱️", "⚠️"))
                ):
                    await query_service.put(message, bot_reply, response_sources, citations)

                return {
                    "session_id": sid,
                    "sources": response_sources if response_sources else None,
                    "citations": citations,
                    "guide_card": guide_card,
                    "jira_ticket": jira_ticket,
                    "grounded": grounded,
                    "intent": intent,
                    "cached": False,
                }

            try:
                if use_agent:
                    # Run the tool loop to completion, then stream the final answer
                    agent_result = await chat_agent_service.run(
                        message, sid, db, file_context=None, kb_on=kb_on
                    )
                    bot_reply_raw = agent_result["reply"]
                    jira_ticket = agent_result["jira_ticket"]
                    if agent_result["sources"]:
                        context_docs = None
                        context_sources = agent_result["sources"]
                        context_scores = agent_result["scores"]
                    if is_jira and jira_ticket is None:
                        recent = (await db.execute(
                            select(Message).where(Message.session_id == sid)
                            .order_by(Message.created_at.desc()).limit(4)
                        )).scalars().all()
                        jira_ticket = _build_jira_draft(message, list(reversed(recent)), detected_type)
                    # Chunked pseudo-stream for a consistent typing effect
                    for i in range(0, len(bot_reply_raw), 60):
                        piece = bot_reply_raw[i:i + 60]
                        chunks.append(piece)
                        yield _sse("token", {"text": piece})
                        await asyncio.sleep(0)
                else:
                    async for delta in llm_service.generate_response_stream(
                        user_message=message,
                        context_docs=context_docs if context_docs else None,
                        context_scores=context_scores if context_scores else None,
                        context_sources=context_sources if context_sources else None,
                        t_low=rag_cfg["t_low"],
                        t_high=rag_cfg["t_high"],
                    ):
                        chunks.append(delta)
                        yield _sse("token", {"text": delta})
            except GeneratorExit:
                # Client disconnected mid-stream: persist what we have, no more yields
                try:
                    await persist("".join(chunks))
                except Exception as e:
                    logger.warning("Persist after disconnect failed: %s", e)
                return

            meta = await persist("".join(chunks))
            if meta is not None:
                yield _sse("meta", meta)
                yield _sse("done", {})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",   # disable nginx proxy buffering
            "Connection": "keep-alive",
        },
    )


# ── Semantic conversation search ──────────────────────────────────

@router.get("/search")
async def search_conversations(
    q: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """Semantic search over the caller's own conversation history."""
    user_id = await get_current_user_id(request)
    if not q or not q.strip():
        return {"results": []}
    hits = await conversation_index_service.search(user_id, q.strip(), n_results=8)
    if not hits:
        return {"results": []}
    # Attach session titles (and drop hits whose session no longer exists)
    session_ids = {h["session_id"] for h in hits if h.get("session_id")}
    if not session_ids:
        return {"results": []}
    rows = (await db.execute(
        select(Session).where(Session.id.in_(session_ids), Session.user_id == user_id)
    )).scalars().all()
    titles = {str(s.id): str(s.title or "") for s in rows}
    results = [
        {**h, "session_title": titles[h["session_id"]]}
        for h in hits if h.get("session_id") in titles
    ]
    return {"results": results}


# ── History endpoints ─────────────────────────────────────────

@router.get("/sessions", response_model=List[SessionResponse])
async def get_sessions(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await get_current_user_id(request)
    result = await db.execute(
        select(Session).where(Session.user_id == user_id).order_by(Session.updated_at.desc())
    )
    sessions = result.scalars().all()
    return [
        SessionResponse(
            id=str(s.id), title=str(s.title or ""),
            created_at=s.created_at,  # type: ignore[arg-type]
            updated_at=s.updated_at   # type: ignore[arg-type]
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}/messages", response_model=List[MessageResponse])
async def get_session_messages(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await get_current_user_id(request)
    session_result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    if not session_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Session non trouvée")

    result = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
    )
    messages = result.scalars().all()
    return [
        MessageResponse(
            id=int(str(m.id)), sender=str(m.sender), text=str(m.text),
            feedback=str(m.feedback) if m.feedback else None,
            created_at=m.created_at  # type: ignore[arg-type]
        )
        for m in messages
    ]


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await get_current_user_id(request)
    session_result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session non trouvée")
    await db.execute(
        delete(Message).where(Message.session_id == session_id)
    )
    await db.delete(session)
    await db.commit()
    await conversation_index_service.delete_session(session_id)
    return {"status": "success", "message": "Session supprimée"}
