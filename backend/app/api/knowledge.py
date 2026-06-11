"""
Knowledge Base API — admin-only endpoints for managing the RAG knowledge base.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.file_validation import validate_upload, KNOWLEDGE_ALLOWED_EXTENSIONS
from app.services.rag_service import rag_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["knowledge"])


async def _require_admin(request: Request, db: AsyncSession):
    """Re-use the same admin gate as admin.py (avoids circular import)."""
    from app.api.admin import require_admin
    return await require_admin(request, db)


# ── Upload & ingest ────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_knowledge_doc(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """Upload and ingest a document into the knowledge base."""
    await _require_admin(request, db)

    file_bytes = await file.read()
    filename = file.filename or "unknown"
    content_type = file.content_type or "application/octet-stream"

    # Validate extension + magic bytes
    ok, err = validate_upload(file_bytes, filename, content_type, KNOWLEDGE_ALLOWED_EXTENSIONS)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    # Max 50 MB
    if len(file_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 50 MB).")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    try:
        if ext == "pdf":
            chunks = await rag_service.ingest_pdf(file_bytes, filename)
        elif ext == "docx":
            chunks = await rag_service.ingest_docx(file_bytes, filename)
        elif ext == "csv":
            chunks = await rag_service.ingest_csv(file_bytes, filename)
        else:  # txt, md
            text = file_bytes.decode("utf-8", errors="ignore")
            chunks = await rag_service.ingest_text(text, filename)
    except Exception as exc:
        logger.error("Knowledge ingest error for %s: %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'ingestion: {exc}")

    return {"status": "ok", "filename": filename, "chunks_ingested": chunks}


# ── List documents ─────────────────────────────────────────────────────────

@router.get("/documents")
async def list_knowledge_docs(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Return the list of ingested documents from the manifest."""
    await _require_admin(request, db)
    docs = rag_service.get_documents()
    return {"documents": docs}


# ── Delete document ────────────────────────────────────────────────────────

@router.delete("/documents/{doc_id}")
async def delete_knowledge_doc(
    doc_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Remove a document's chunks from ChromaDB and its manifest entry."""
    await _require_admin(request, db)
    removed = rag_service.delete_document(doc_id)
    if removed == 0:
        raise HTTPException(status_code=404, detail="Document non trouvé dans la base de connaissances.")
    return {"status": "ok", "chunks_removed": removed}


# ── Re-seed built-in KB ────────────────────────────────────────────────────

@router.post("/seed")
async def seed_knowledge(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Re-seed the built-in knowledge base entries."""
    await _require_admin(request, db)
    count = rag_service.reseed_builtin()
    return {"status": "ok", "entries_seeded": count}


# ── Stats ──────────────────────────────────────────────────────────────────

@router.get("/stats")
async def knowledge_stats(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Return total docs, chunks, and last update timestamp."""
    await _require_admin(request, db)
    stats = rag_service.get_stats()
    return stats
