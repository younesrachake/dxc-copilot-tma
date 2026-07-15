"""
Integration API — admin config/test + user-facing confirmed-write execution.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import registry
from app.connectors.http import ConnectorError
from app.core.audit import audit
from app.core.config import JWT_SECRET, JWT_ALGORITHM
from app.core.database import get_db

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/api/admin/integrations", tags=["integrations"])
user_router = APIRouter(prefix="/api/integrations", tags=["integrations"])


async def _require_admin(request: Request, db: AsyncSession):
    from app.api.admin import require_admin
    return await require_admin(request, db)


async def _require_user(request: Request) -> int:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Non authentifié")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return int(str(payload.get("sub", 0)))
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide")


# ── Admin: list / configure / test connectors ────────────────────

@admin_router.get("")
async def list_integrations(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin(request, db)
    return {"connectors": await registry.status(db)}


@admin_router.put("/{key}")
async def save_integration(key: str, data: dict, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _require_admin(request, db)
    try:
        result = await registry.save_config(db, key, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await audit(db, int(str(admin.id)), "integration_configured", resource=f"integration:{key}",
                detail=f'{{"enabled": {str(result["enabled"]).lower()}}}')
    return result


@admin_router.post("/{key}/test")
async def test_integration(key: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin(request, db)
    return await registry.test(db, key)


# ── User: execute a confirmed write action from a chat card ───────

@user_router.post("/execute")
async def execute_action(data: dict, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_user(request)
    tool = data.get("tool")
    args = data.get("args") or {}
    if not tool:
        raise HTTPException(status_code=400, detail="Action non spécifiée.")
    try:
        result = await registry.execute(db, tool, args)
    except ConnectorError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Integration execute failed for %s: %s", tool, e)
        raise HTTPException(status_code=500, detail=f"Échec de l'action : {e}")
    return {"status": "success", "result": result}
