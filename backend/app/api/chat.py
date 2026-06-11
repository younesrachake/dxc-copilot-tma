import uuid
import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, text
from jose import jwt
from typing import Optional, List

from app.core.database import get_db
from app.core.config import JWT_SECRET, JWT_ALGORITHM
from app.models.db import Session, Message, Incident
from app.models.schemas import ChatResponse, SessionResponse, MessageResponse
from app.services.ocr_service import ocr_service
from app.services.stt_service import stt_service
from app.services.rag_service import rag_service
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

INCIDENT_KEYWORDS = [
    "erreur", "error", "panne", "bug", "incident",
    "problème", "dysfonctionnement", "crash", "timeout", "exception"
]


async def get_current_user_id(request: Request) -> int:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Non authentifié")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return int(str(payload.get("sub", 0)))
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide")


@router.post("", response_model=ChatResponse)
async def chat(
    request: Request,
    message: str = Form(...),
    session_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db)
):
    user_id = await get_current_user_id(request)

    # ── Create or get session ─────────────────────────────────
    if not session_id:
        session_id = str(uuid.uuid4())
        new_session = Session(id=session_id, user_id=user_id, title=message[:50])
        db.add(new_session)
        await db.flush()
    else:
        # Verify the provided session belongs to the current user (prevent session hijacking)
        existing = await db.execute(
            select(Session).where(Session.id == session_id, Session.user_id == user_id)
        )
        if not existing.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Accès à cette session refusé")

    # ── Process file + RAG in parallel (asyncio.gather) ─────────
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
            if ext in _KB_INGEST_EXTS and not content_type.startswith("image/"):
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

    rag_start = time.monotonic()
    file_context, rag_result = await asyncio.gather(
        process_file(),
        rag_service.search(message, n_results=3)
    )
    rag_latency_ms = int((time.monotonic() - rag_start) * 1000)
    context_docs, context_scores, context_sources = rag_result

    # ── Save user message ─────────────────────────────────────
    user_msg = Message(
        session_id=session_id, sender="user", text=message,
        attachments=attachments_meta
    )
    db.add(user_msg)
    await db.flush()

    # ── Track incidents (RG2) ─────────────────────────────────
    guide_card = None
    detected_type = None
    msg_lower = message.lower()
    for kw in INCIDENT_KEYWORDS:
        if kw in msg_lower:
            detected_type = kw
            break

    if detected_type:
        result = await db.execute(select(Incident).where(Incident.incident_type == detected_type))
        incident = result.scalar_one_or_none()
        if incident:
            incident.count = (incident.count or 0) + 1  # type: ignore[assignment]
            incident.last_seen = datetime.now(timezone.utc)  # type: ignore[assignment]
            if incident.count >= 3:
                guide_card = {
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
        else:
            db.add(Incident(incident_type=detected_type, count=1))

    # ── Generate AI response (with 45s timeout) ───────────────
    bot_reply = await llm_service.generate_response(
        user_message=message,
        context_docs=context_docs if context_docs else None,
        context_scores=context_scores if context_scores else None,
        file_context=file_context if file_context else None,
        timeout=45.0
    )

    # ── Determine routing decision for analytics ───────────────
    top_score = max(context_scores) if context_scores else 0.0
    if top_score >= 0.75:
        routing = "kb_primary"
    elif top_score >= 0.35:
        routing = "kb_hint"
    else:
        routing = "groq_only"

    # ── Write RAG analytics row ────────────────────────────────
    try:
        query_hash = hashlib.sha256(message.encode()).hexdigest()[:16]
        used_sources = context_sources if routing != "groq_only" else []
        await db.execute(
            text(
                "INSERT INTO rag_analytics (query_hash, top_score, routing, doc_ids, latency_ms) "
                "VALUES (:qh, :ts, :rt, :di, :lm)"
            ),
            {
                "qh": query_hash,
                "ts": round(top_score, 4),
                "rt": routing,
                "di": json.dumps(used_sources),
                "lm": rag_latency_ms,
            }
        )
    except Exception as _analytics_err:
        logger.warning("RAG analytics insert failed: %s", _analytics_err)

    # Append KB ingestion confirmation if a document was auto-ingested
    if _kb_ingested.get("filename"):
        bot_reply += (
            f'\n\n📚 *Le document **"{_kb_ingested["filename"]}"** a été automatiquement ajouté à la '
            f'base de connaissances ({_kb_ingested["chunks"]} chunk(s)). '
            f'Il sera utilisé comme référence dans toutes les prochaines conversations.*'
        )

    # ── Save bot message ──────────────────────────────────────
    bot_msg = Message(
        session_id=session_id, sender="bot", text=bot_reply,
        guide_card=guide_card
    )
    db.add(bot_msg)
    await db.commit()

    # Only expose sources when KB was actually used
    response_sources = context_sources if routing != "groq_only" else []
    return ChatResponse(
        reply=bot_reply,
        session_id=session_id,
        guide_card=guide_card,
        sources=response_sources if response_sources else None
    )


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
    return {"status": "success", "message": "Session supprimée"}
