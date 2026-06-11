import asyncio
import shlex
import subprocess
import uuid
import os
import logging
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import Depends
from jose import jwt

from app.core.database import get_db
from app.core.config import JWT_SECRET, JWT_ALGORITHM
from app.core.audit import audit
from app.models.db import User
from app.models.schemas import TerminalRequest, TerminalResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/terminal", tags=["terminal"])

TERMINAL_ENABLED = os.getenv("ENABLE_TERMINAL", "false").lower() == "true"

# Strict allowlist — only these base commands are permitted (shell=False, no expansion)
ALLOWED_BASE_COMMANDS = {
    "ls", "dir", "pwd", "echo", "cat", "head", "tail",
    "ps", "df", "du", "free", "uptime", "date", "whoami",
    "python", "pip", "uvicorn",
}


async def _require_admin_terminal(request: Request, db: AsyncSession) -> User:
    if not TERMINAL_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Terminal désactivé. Définissez ENABLE_TERMINAL=true dans .env pour l'activer."
        )
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Non authentifié")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(str(payload.get("sub", "0")))
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or str(user.role) != "admin":
        raise HTTPException(status_code=403, detail="Terminal réservé aux administrateurs")
    return user


def _parse_and_validate(command: str):
    """
    Parse command using shlex (no shell expansion) and verify the base command
    is in the strict allowlist. Returns (cmd, args) tuple or raises HTTPException.
    """
    try:
        parts = shlex.split(command)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Commande invalide: {e}")

    if not parts:
        raise HTTPException(status_code=400, detail="Commande vide")

    base_cmd = os.path.basename(parts[0]).lower()
    if base_cmd not in ALLOWED_BASE_COMMANDS:
        raise HTTPException(
            status_code=403,
            detail=f"Commande '{base_cmd}' non autorisée. Commandes autorisées: {', '.join(sorted(ALLOWED_BASE_COMMANDS))}"
        )
    return parts[0], parts[1:]


@router.post("/execute", response_model=TerminalResponse)
async def execute_command(
    req: TerminalRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    user = await _require_admin_terminal(request, db)

    cmd, args = _parse_and_validate(req.command)

    # Sanitize for logging — strip newlines, truncate
    cmd_safe = req.command.replace('\n', ' ').replace('\r', ' ')[:200]
    logger.info("TERMINAL EXEC user=%s cmd=%r", user.email, cmd_safe)
    await audit(db, int(str(user.id)), "terminal_execute", resource="terminal",
                detail=cmd_safe, ip=request.client.host if request.client else None)

    loop = asyncio.get_event_loop()
    try:
        def _run():
            return subprocess.run(
                [cmd, *args],
                shell=False,          # Never use shell=True
                capture_output=True,
                text=True,
                timeout=15,
                env={**os.environ, "PATH": os.environ.get("PATH", "")},
            )
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _run),
            timeout=20.0
        )
        return TerminalResponse(
            output=result.stdout or result.stderr or "(no output)",
            exit_code=result.returncode,
            execution_id=str(uuid.uuid4())
        )
    except (asyncio.TimeoutError, subprocess.TimeoutExpired):
        raise HTTPException(status_code=408, detail="Commande expirée (timeout 15s)")
    except Exception:
        logger.exception("Terminal execution error for user=%s", user.email)
        raise HTTPException(status_code=500, detail="Erreur interne du serveur")
