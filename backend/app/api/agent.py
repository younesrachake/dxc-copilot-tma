"""
API du Knowledge Sync Agent — statut, fréquence et exécution manuelle.

- GET  /api/agent/status     : tout utilisateur connecté
- PUT  /api/agent/frequency  : tout utilisateur connecté (réglage dans les paramètres utilisateur)
- POST /api/agent/run        : administrateurs uniquement
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.audit import audit
from app.api.admin import get_current_user, require_admin
from app.services.agent_service import knowledge_sync_agent, FREQUENCIES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/status")
async def agent_status(request: Request, db: AsyncSession = Depends(get_db)):
    """Return the knowledge sync agent status (any logged-in user)."""
    await get_current_user(request, db)
    return await knowledge_sync_agent.get_status(db)


@router.put("/frequency")
async def set_agent_frequency(data: dict, request: Request, db: AsyncSession = Depends(get_db)):
    """Set the agent update frequency (any logged-in user — user settings page)."""
    user = await get_current_user(request, db)
    frequency = str(data.get("frequency", "")).lower()
    if frequency not in FREQUENCIES:
        raise HTTPException(
            status_code=400,
            detail=f"Fréquence invalide. Valeurs acceptées : {', '.join(FREQUENCIES)}."
        )
    status = await knowledge_sync_agent.set_frequency(db, frequency)
    await audit(db, user_id=int(str(user.id)), action="AGENT_FREQUENCY_CHANGED",
                resource="agent", detail=f"Fréquence de synchronisation : {frequency}",
                ip=request.client.host if request.client else None)
    return status


@router.post("/run")
async def run_agent_now(request: Request, db: AsyncSession = Depends(get_db)):
    """Run the knowledge sync agent immediately (admin only)."""
    admin_user = await require_admin(request, db)
    if knowledge_sync_agent._running:
        raise HTTPException(status_code=409, detail="L'agent est déjà en cours d'exécution.")
    try:
        result = await knowledge_sync_agent.run_sync(db)
    except Exception as exc:
        logger.exception("Manual agent run failed: %s", exc)
        raise HTTPException(status_code=500, detail="Échec de l'exécution de l'agent.")
    await audit(db, user_id=int(str(admin_user.id)), action="AGENT_RUN_MANUAL",
                resource="agent",
                detail=f"{result['guides_ingested']} guide(s) ingéré(s), {result['docs_mirrored']} document(s) synchronisé(s)",
                ip=request.client.host if request.client else None)
    return {"status": "success", **result, **await knowledge_sync_agent.get_status(db)}
