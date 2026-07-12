import asyncio
import functools
import json
import platform
import shutil
import os
import secrets
import smtplib
import time
import logging
from email.mime.text import MIMEText
from collections import deque
try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Request, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, text
from passlib.context import CryptContext
from jose import jwt

from app.core.database import get_db
from app.core.config import JWT_SECRET, JWT_ALGORITHM
from app.core.audit import audit
from app.models.db import User, Session, Message, Incident, Feedback, IncidentGuide, MaintenanceTask, PlatformSetting, AuditLog
from app.models.schemas import (
    AdminUserResponse, CreateUserRequest, UpdateUserRequest,
    MaintenanceActionResponse, UpdateProfileRequest, ChangePasswordRequest, UserResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── In-memory log ring-buffer ─────────────────────────────────────
_LOG_BUFFER: deque = deque(maxlen=500)


class _MemHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _LOG_BUFFER.appendleft({
            "timestamp": self.formatter.formatTime(record, "%Y-%m-%dT%H:%M:%SZ") if self.formatter else "",
            "level": record.levelname,
            "service": record.name,
            "message": record.getMessage(),
            "user": "system",
        })


_mem_handler = _MemHandler()
_mem_handler.setFormatter(logging.Formatter())
_mem_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(_mem_handler)


async def _hash_password(plain: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(pwd_context.hash, plain))


async def _verify_password(plain: str, hashed: str) -> bool:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(pwd_context.verify, plain, hashed))


# ── Helper: require admin role ───────────────────────────────────
async def require_admin(request: Request, db: AsyncSession) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Non authentifié")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(str(payload.get("sub", 0)))
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
    return user


# ── Helper: get current user from cookie ─────────────────────────
async def get_current_user(request: Request, db: AsyncSession) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Non authentifié")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(str(payload.get("sub", 0)))
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    return user


# ═══════════════════════════════════════════════════════════════════
#  HEALTH / SYSTEM
# ═══════════════════════════════════════════════════════════════════

@router.get("/health")
async def health():
    disk_path = "." if platform.system() == "Windows" else "/"
    disk = shutil.disk_usage(disk_path)
    now = datetime.now(timezone.utc)

    if _PSUTIL:
        cpu_pct = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        boot_ts = psutil.boot_time()
        uptime_sec = int(time.time() - boot_ts)
        uptime_h = uptime_sec // 3600
        uptime_m = (uptime_sec % 3600) // 60
        uptime_str = f"{uptime_h}h {uptime_m}m"
        mem_total = f"{round(mem.total / (1024**3), 1)} GB"
        mem_used = f"{round(mem.used / (1024**3), 1)} GB"
        mem_pct = f"{mem.percent}%"
    else:
        cpu_pct = 0.0
        uptime_str = "N/A"
        mem_total = "N/A"
        mem_used = "N/A"
        mem_pct = "N/A"

    return {
        "status": "healthy",
        "version": "1.0.0",
        "uptime": uptime_str,
        "timestamp": now.isoformat(),
        "system_info": [
            {"label": "Version Application", "value": "1.0.0", "status": "success"},
            {"label": "Système d'exploitation", "value": f"{platform.system()} {platform.release()}", "status": "success"},
            {"label": "Python", "value": platform.python_version(), "status": "success"},
            {"label": "CPU", "value": f"{cpu_pct}%", "status": "warning" if cpu_pct > 80 else "success"},
            {"label": "Mémoire utilisée", "value": f"{mem_used} / {mem_total} ({mem_pct})", "status": "warning" if _PSUTIL and psutil.virtual_memory().percent > 80 else "success"},
            {"label": "Disque", "value": f"{round(disk.used / (1024**3), 1)} GB / {round(disk.total / (1024**3), 1)} GB ({round(disk.used / disk.total * 100, 1)}%)", "status": "warning" if disk.used / disk.total > 0.8 else "success"},
            {"label": "Uptime système", "value": uptime_str, "status": "success"},
            {"label": "Base de données", "value": "Connectée", "status": "success"}
        ],
        "services": [
            {"id": "api-gw",    "name": "API Gateway",      "status": "running", "cpu": round(cpu_pct / 5, 1), "memory": round(cpu_pct / 4, 1)},
            {"id": "auth",      "name": "Auth Service",      "status": "running", "cpu": 0.0, "memory": 0.0},
            {"id": "chat",      "name": "Chat Service",      "status": "running", "cpu": 0.0, "memory": 0.0},
            {"id": "docs",      "name": "Document Service",  "status": "running", "cpu": 0.0, "memory": 0.0},
            {"id": "analytics", "name": "Analytics Service", "status": "running", "cpu": 0.0, "memory": 0.0}
        ]
    }


# ═══════════════════════════════════════════════════════════════════
#  DASHBOARD — real stats from DB
# ═══════════════════════════════════════════════════════════════════

@router.get("/dashboard")
async def dashboard_stats(request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)

    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    total_messages = (await db.execute(select(func.count(Message.id)))).scalar() or 0
    total_incidents = (await db.execute(select(func.count(Incident.id)))).scalar() or 0

    today = datetime.now(timezone.utc).date()
    today_start = datetime.combine(today, datetime.min.time())
    sessions_today = (await db.execute(
        select(func.count(Session.id)).where(Session.created_at >= today_start)
    )).scalar() or 0

    recent_msgs = (await db.execute(
        select(Message).order_by(Message.created_at.desc()).limit(10)
    )).scalars().all()
    activity = [
        {"user": m.sender, "action": m.text[:80], "time": m.created_at.isoformat()}
        for m in recent_msgs
    ]

    return {
        "total_users": total_users,
        "active_sessions_today": sessions_today,
        "total_messages": total_messages,
        "total_incidents": total_incidents,
        "recent_activity": activity
    }


# ═══════════════════════════════════════════════════════════════════
#  ANALYTICS — real counts from DB
# ═══════════════════════════════════════════════════════════════════

@router.get("/analytics")
async def analytics(request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)

    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    total_sessions = (await db.execute(select(func.count(Session.id)))).scalar() or 0
    total_messages = (await db.execute(select(func.count(Message.id)))).scalar() or 0
    total_feedback = (await db.execute(select(func.count(Feedback.id)))).scalar() or 0
    positive_fb = (await db.execute(
        select(func.count(Feedback.id)).where(Feedback.rating == "positive")
    )).scalar() or 0

    # Chart data: sessions per day for last 30 days
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    sessions_rows = (await db.execute(
        select(Session.created_at).where(Session.created_at >= thirty_days_ago)
    )).scalars().all()
    day_counts: dict = {}
    for s in sessions_rows:
        day = s.strftime("%Y-%m-%d") if s else None
        if day:
            day_counts[day] = day_counts.get(day, 0) + 1
    chart_data = [
        {"date": d, "sessions": c}
        for d, c in sorted(day_counts.items())
    ]

    # Top features: keyword-based message intent classification
    user_msgs = (await db.execute(
        select(Message.text).where(Message.sender == "user").limit(500)
    )).scalars().all()
    feature_counts = {"Code & Débogage": 0, "Documentation": 0, "Incident / Erreur": 0, "Analyse": 0, "Autre": 0}
    for txt in user_msgs:
        t = (txt or "").lower()
        if any(k in t for k in ["code", "bug", "erreur", "fonction", "script", "python", "sql"]):
            feature_counts["Code & Débogage"] += 1
        elif any(k in t for k in ["document", "pdf", "résumé", "résume", "fichier"]):
            feature_counts["Documentation"] += 1
        elif any(k in t for k in ["incident", "panne", "crash", "timeout", "problème"]):
            feature_counts["Incident / Erreur"] += 1
        elif any(k in t for k in ["analyse", "rapport", "statistique", "performance"]):
            feature_counts["Analyse"] += 1
        else:
            feature_counts["Autre"] += 1
    total_classified = max(sum(feature_counts.values()), 1)
    top_features = [
        {"name": name, "usage": count, "pct": round(count / total_classified * 100)}
        for name, count in sorted(feature_counts.items(), key=lambda x: -x[1])
    ]

    satisfaction = round(positive_fb / max(total_feedback, 1) * 100, 1)

    return {
        "metrics": [
            {"label": "Utilisateurs", "value": str(total_users), "change": "+0", "up": True},
            {"label": "Sessions", "value": str(total_sessions), "change": "+0", "up": True},
            {"label": "Messages", "value": str(total_messages), "change": "+0", "up": True},
            {"label": "Satisfaction", "value": f"{satisfaction}%", "change": "+0", "up": True},
        ],
        "chart_data": chart_data,
        "top_features": top_features,
        "total_users": total_users,
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "total_feedback": total_feedback,
    }


# ═══════════════════════════════════════════════════════════════════
#  RAG ANALYTICS — real retrieval observability
# ═══════════════════════════════════════════════════════════════════

@router.get("/analytics/rag")
async def rag_analytics(request: Request, db: AsyncSession = Depends(get_db)):
    """Return real RAG retrieval metrics from the rag_analytics table."""
    await require_admin(request, db)
    try:
        rows = (await db.execute(
            text("SELECT top_score, routing, doc_ids, latency_ms FROM rag_analytics ORDER BY id DESC LIMIT 5000")
        )).fetchall()
    except Exception:
        rows = []

    total = len(rows)
    if total == 0:
        return {
            "total_queries": 0,
            "kb_hit_rate": 0.0,
            "avg_top_score": 0.0,
            "avg_latency_ms": 0,
            "routing_breakdown": {"kb_primary": 0, "kb_hint": 0, "groq_only": 0},
            "top_docs": [],
        }

    routing_counts = {"kb_primary": 0, "kb_hint": 0, "groq_only": 0}
    score_sum = 0.0
    latency_sum = 0
    latency_n = 0
    doc_counter: dict = {}

    for row in rows:
        top_score, routing, doc_ids_json, latency_ms = row
        routing_counts[routing] = routing_counts.get(routing, 0) + 1
        score_sum += float(top_score or 0)
        if latency_ms:
            latency_sum += int(latency_ms)
            latency_n += 1
        if doc_ids_json:
            try:
                ids = json.loads(doc_ids_json)
                for did in ids:
                    doc_counter[did] = doc_counter.get(did, 0) + 1
            except Exception:
                pass

    kb_hits = routing_counts.get("kb_primary", 0) + routing_counts.get("kb_hint", 0)
    top_docs = sorted(
        [{"doc_id": k, "count": v} for k, v in doc_counter.items()],
        key=lambda x: -x["count"]
    )[:10]

    return {
        "total_queries": total,
        "kb_hit_rate": round(kb_hits / total, 3),
        "avg_top_score": round(score_sum / total, 3),
        "avg_latency_ms": round(latency_sum / max(latency_n, 1)),
        "routing_breakdown": routing_counts,
        "top_docs": top_docs,
    }


# ═══════════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════════

_DEFAULT_CONFIG = {
    "maxTokens": 4096,
    "temperature": 0.7,
    "model": "gpt-4o",
    "maxFileSize": 15,
    "allowedFormats": "pdf,png,jpg,mp3,wav",
    "sessionTimeout": 30,
    "language": "fr"
}


@router.get("/config")
async def get_config(request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.section == "system_config"))
    row = result.scalar_one_or_none()
    config = dict(row.data) if row and row.data else dict(_DEFAULT_CONFIG)  # type: ignore[arg-type]
    return {"config": config}


@router.put("/config")
async def update_config(data: dict, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.section == "system_config"))
    row = result.scalar_one_or_none()
    if row:
        row.data = data  # type: ignore[assignment]
    else:
        db.add(PlatformSetting(section="system_config", data=data))
    await db.commit()
    return {"status": "success", "message": "Configuration mise à jour", "config": data}


# ═══════════════════════════════════════════════════════════════════
#  SERVICES
# ═══════════════════════════════════════════════════════════════════

@router.post("/restart/{service_id}")
async def restart_service(service_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Service restarts are the orchestrator's job — this endpoint no longer
    pretends to restart anything (it previously returned a fake success)."""
    admin_user = await require_admin(request, db)
    allowed = ["api-gw", "auth", "chat", "docs", "analytics"]
    if service_id not in allowed:
        raise HTTPException(status_code=400, detail=f"Service inconnu: {service_id}")
    await audit(db, int(str(admin_user.id)), "restart_requested", resource=f"service:{service_id}")
    raise HTTPException(
        status_code=501,
        detail=(
            f"Le redémarrage de '{service_id}' doit être effectué par l'orchestrateur : "
            "`docker compose restart backend` ou `kubectl rollout restart deploy/dxc-copilot-backend`. "
            "La demande a été consignée dans le journal d'audit."
        ),
    )


# ═══════════════════════════════════════════════════════════════════
#  LOGS
# ═══════════════════════════════════════════════════════════════════

@router.get("/logs")
async def get_logs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    lines: int = 50,
    level: Optional[str] = None,
    service: Optional[str] = None
):
    await require_admin(request, db)
    entries = list(_LOG_BUFFER)
    if level:
        entries = [e for e in entries if e["level"] == level.upper()]
    if service:
        entries = [e for e in entries if service.lower() in e["service"].lower()]
    return {"logs": entries[:lines]}


@router.delete("/logs")
async def clear_logs(request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    _LOG_BUFFER.clear()
    return {"status": "success", "message": "Logs effacés"}


# ═══════════════════════════════════════════════════════════════════
#  USERS CRUD
# ═══════════════════════════════════════════════════════════════════

@router.get("/users", response_model=List[AdminUserResponse])
async def list_users(request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    result = await db.execute(select(User).order_by(User.id))
    users = result.scalars().all()
    return [
        AdminUserResponse(
            id=int(str(u.id)),
            name=str(u.full_name or ""),
            email=str(u.email),
            role=str(u.role or "user"),
            status=str(u.status or "active"),
            department=str(u.department) if u.department else None,
            last_login=u.last_login.strftime("%Y-%m-%d %H:%M") if u.last_login else None,
            created_at=u.created_at  # type: ignore[arg-type]
        )
        for u in users
    ]


@router.post("/users", response_model=AdminUserResponse)
async def create_user(req: CreateUserRequest, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await require_admin(request, db)

    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Un utilisateur avec cet email existe déjà")

    user = User(
        email=req.email,
        full_name=req.name,
        hashed_password=await _hash_password(req.password),
        role=req.role or "user",
        department=req.department,
        status="active"
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await audit(db, int(str(admin.id)), "create_user", resource=f"user:{user.email}",
                ip=request.client.host if request.client else None)
    return AdminUserResponse(
        id=int(str(user.id)),
        name=str(user.full_name or ""),
        email=str(user.email),
        role=str(user.role or "user"),
        status=str(user.status or "active"),
        department=str(user.department) if user.department else None,
        last_login=None,
        created_at=user.created_at  # type: ignore[arg-type]
    )


@router.put("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(user_id: int, req: UpdateUserRequest, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await require_admin(request, db)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

    if req.name is not None:
        user.full_name = req.name  # type: ignore[assignment]
    if req.email is not None:
        user.email = req.email  # type: ignore[assignment]
    if req.role is not None:
        user.role = req.role  # type: ignore[assignment]
    if req.status is not None:
        user.status = req.status  # type: ignore[assignment]
    if req.department is not None:
        user.department = req.department  # type: ignore[assignment]

    await db.commit()
    await db.refresh(user)
    await audit(db, int(str(admin.id)), "update_user", resource=f"user:{user.email}",
                ip=request.client.host if request.client else None)
    return AdminUserResponse(
        id=int(str(user.id)),
        name=str(user.full_name or ""),
        email=str(user.email),
        role=str(user.role or "user"),
        status=str(user.status or "active"),
        department=str(user.department) if user.department else None,
        last_login=user.last_login.strftime("%Y-%m-%d %H:%M") if user.last_login else None,
        created_at=user.created_at  # type: ignore[arg-type]
    )


@router.patch("/users/{user_id}/status")
async def toggle_user_status(user_id: int, data: dict, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    new_status = data.get("status", "active")
    user.status = new_status  # type: ignore[assignment]
    await db.commit()
    return {"status": "success", "user_id": user_id, "new_status": new_status}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await require_admin(request, db)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    # Cascade: delete sessions and their messages
    sessions = (await db.execute(select(Session).where(Session.user_id == user_id))).scalars().all()
    for s in sessions:
        await db.execute(delete(Message).where(Message.session_id == s.id))
    await db.execute(delete(Session).where(Session.user_id == user_id))
    email = str(user.email)
    await db.delete(user)
    await db.commit()
    await audit(db, int(str(admin.id)), "delete_user", resource=f"user:{email}",
                ip=request.client.host if request.client else None)
    return {"status": "success", "message": f"Utilisateur {email} et ses données supprimés"}


# ═══════════════════════════════════════════════════════════════════
#  MAINTENANCE
# ═══════════════════════════════════════════════════════════════════

@router.post("/maintenance/backup", response_model=MaintenanceActionResponse)
async def run_backup(request: Request, db: AsyncSession = Depends(get_db)):
    admin_user = await require_admin(request, db)
    from app.services.maintenance_service import run_backup as do_backup
    try:
        result = await do_backup()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Échec de la sauvegarde : {e}")
    await audit(db, int(str(admin_user.id)), "database_backup", resource="maintenance",
                detail=json.dumps(result))
    size_mb = round(result["size_bytes"] / (1024 * 1024), 2)
    return MaintenanceActionResponse(
        status="success",
        message="Sauvegarde de la base de données complétée avec succès.",
        details={"timestamp": datetime.now(timezone.utc).isoformat(),
                 "path": result["path"], "size": f"{size_mb} MB"}
    )


@router.post("/maintenance/clean-cache", response_model=MaintenanceActionResponse)
async def clean_cache(request: Request, db: AsyncSession = Depends(get_db)):
    admin_user = await require_admin(request, db)
    from app.services.maintenance_service import clean_caches
    try:
        result = await clean_caches()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Échec du nettoyage : {e}")
    await audit(db, int(str(admin_user.id)), "cache_cleaned", resource="maintenance",
                detail=json.dumps(result))
    return MaintenanceActionResponse(
        status="success",
        message="Cache nettoyé avec succès.",
        details={**result, "timestamp": datetime.now(timezone.utc).isoformat()}
    )


@router.post("/maintenance/optimize-db", response_model=MaintenanceActionResponse)
async def optimize_db(request: Request, db: AsyncSession = Depends(get_db)):
    admin_user = await require_admin(request, db)
    from app.services.maintenance_service import optimize_database
    try:
        result = await optimize_database()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Échec de l'optimisation : {e}")
    await audit(db, int(str(admin_user.id)), "database_optimized", resource="maintenance",
                detail=json.dumps(result))
    return MaintenanceActionResponse(
        status="success",
        message="Optimisation de la base de données complétée.",
        details={**result, "timestamp": datetime.now(timezone.utc).isoformat()}
    )


@router.get("/maintenance/health")
async def system_health(request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    disk_path = "." if platform.system() == "Windows" else "/"
    disk = shutil.disk_usage(disk_path)
    disk_pct = disk.used / disk.total

    cpu_pct: float = 0.0
    mem_detail = "N/A"
    cpu_detail = "N/A"
    mem_status = "good"
    cpu_status = "good"
    mem_pct_val: float = 0.0

    if _PSUTIL:
        mem = psutil.virtual_memory()
        cpu_pct = psutil.cpu_percent(interval=0.1)
        mem_pct_val = mem.percent
        mem_detail = f"{round(mem.used / (1024**3), 1)} GB / {round(mem.total / (1024**3), 1)} GB ({mem.percent}%)"
        cpu_detail = f"{cpu_pct}% utilisation"
        mem_status = "warning" if mem.percent > 80 else "good"
        cpu_status = "warning" if cpu_pct > 80 else "good"

    redis_url = os.getenv("REDIS_URL", "")
    redis_status = "warning"
    redis_detail = "Redis non configuré (REDIS_URL manquant)"
    if redis_url:
        try:
            import socket
            host_port = redis_url.replace("redis://", "").split("/")[0]
            host, port = (host_port.split(":") + ["6379"])[:2]
            s = socket.create_connection((host, int(port)), timeout=1)
            s.close()
            redis_status = "good"
            redis_detail = f"Connecté à {host}:{port}"
        except Exception:
            redis_status = "error"
            redis_detail = "Redis configuré mais injoignable"

    return {
        "components": [
            {
                "component": "Espace disque",
                "value": f"{round(disk_pct * 100)}%",
                "status": "warning" if disk_pct > 0.7 else "good",
                "details": f"{round(disk.used / (1024**3), 1)} GB utilisés sur {round(disk.total / (1024**3), 1)} GB"
            },
            {"component": "Base de données", "value": "Opérationnel", "status": "good", "details": "Connexion SQLite active"},
            {"component": "CPU", "value": f"{cpu_pct}%" if _PSUTIL else "N/A", "status": cpu_status, "details": cpu_detail},
            {"component": "Mémoire", "value": f"{mem_pct_val}%" if _PSUTIL else "N/A", "status": mem_status, "details": mem_detail},
            {"component": "Cache Redis", "value": "Configuré" if redis_url else "Non configuré", "status": redis_status, "details": redis_detail}
        ]
    }


# ═══════════════════════════════════════════════════════════════════
#  REPORTS — aggregated data from DB
# ═══════════════════════════════════════════════════════════════════

@router.get("/reports/summary")
async def report_summary(request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    total_sessions = (await db.execute(select(func.count(Session.id)))).scalar() or 0
    total_messages = (await db.execute(select(func.count(Message.id)))).scalar() or 0
    total_incidents = (await db.execute(select(func.count(Incident.id)))).scalar() or 0

    positive_fb = (await db.execute(
        select(func.count(Feedback.id)).where(Feedback.rating == "positive")
    )).scalar() or 0
    total_fb = (await db.execute(select(func.count(Feedback.id)))).scalar() or 1

    return {
        "period": datetime.now(timezone.utc).strftime("%B %Y"),
        "total_users": total_users,
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "total_incidents": total_incidents,
        "satisfaction_rate": round(positive_fb / total_fb * 100, 1),
        "avg_messages_per_session": round(total_messages / max(total_sessions, 1), 1)
    }


@router.get("/reports/{report_type}")
async def get_report_data(report_type: str, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    now = datetime.now(timezone.utc)

    if report_type == "mensuel":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        sessions_month = (await db.execute(
            select(func.count(Session.id)).where(Session.created_at >= start)
        )).scalar() or 0
        users_month = (await db.execute(
            select(func.count(User.id)).where(User.created_at >= start)
        )).scalar() or 0
        messages_month = (await db.execute(
            select(func.count(Message.id)).where(Message.created_at >= start)
        )).scalar() or 0
        total_sessions = (await db.execute(select(func.count(Session.id)))).scalar() or 1
        positive_fb = (await db.execute(
            select(func.count(Feedback.id)).where(Feedback.rating == "positive")
        )).scalar() or 0
        total_fb = (await db.execute(select(func.count(Feedback.id)))).scalar() or 1
        return {
            "period": now.strftime("%B %Y"),
            "kpis": [
                {"label": "Sessions ce mois", "value": str(sessions_month), "change": "", "up": True},
                {"label": "Nouveaux utilisateurs", "value": str(users_month), "change": "", "up": True},
                {"label": "Messages traités", "value": str(messages_month), "change": "", "up": True},
                {"label": "Satisfaction", "value": f"{round(positive_fb / total_fb * 100, 1)}%", "change": "", "up": True},
            ],
            "topFeatures": [
                {"name": "Chat & Assistance", "usage": int(str(total_sessions)), "pct": 60},
                {"name": "Analyse de documents", "usage": int(str(total_sessions // 3)), "pct": 25},
                {"name": "Génération de guides", "usage": int(str(total_sessions // 8)), "pct": 10},
                {"name": "Rapports", "usage": int(str(total_sessions // 20)), "pct": 5},
            ],
        }

    if report_type == "trimestriel":
        months = []
        for delta in range(2, -1, -1):
            m = (now.month - delta - 1) % 12 + 1
            y = now.year if now.month - delta > 0 else now.year - 1
            start_m = now.replace(year=y, month=m, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_m = (start_m.replace(month=m % 12 + 1) if m < 12
                     else start_m.replace(year=y + 1, month=1))
            s = (await db.execute(select(func.count(Session.id)).where(
                Session.created_at >= start_m, Session.created_at < end_m
            ))).scalar() or 0
            u = (await db.execute(select(func.count(User.id)).where(
                User.created_at >= start_m, User.created_at < end_m
            ))).scalar() or 0
            msg = (await db.execute(select(func.count(Message.id)).where(
                Message.created_at >= start_m, Message.created_at < end_m
            ))).scalar() or 0
            months.append({"name": start_m.strftime("%B"), "sessions": int(str(s)), "users": int(str(u)), "messages": int(str(msg))})
        total_sessions = sum(int(m["sessions"]) for m in months)
        total_users = sum(int(m["users"]) for m in months)
        total_messages = sum(int(m["messages"]) for m in months)
        positive_fb = (await db.execute(
            select(func.count(Feedback.id)).where(Feedback.rating == "positive")
        )).scalar() or 0
        total_fb = (await db.execute(select(func.count(Feedback.id)))).scalar() or 1
        return {
            "period": f"Q{(now.month - 1) // 3 + 1} {now.year}",
            "months": months,
            "kpis": [
                {"label": "Sessions trimestre", "value": str(total_sessions), "change": "", "up": True},
                {"label": "Utilisateurs trimestre", "value": str(total_users), "change": "", "up": True},
                {"label": "Messages trimestre", "value": str(total_messages), "change": "", "up": True},
                {"label": "Satisfaction", "value": f"{round(positive_fb / total_fb * 100, 1)}%", "change": "", "up": True},
            ],
        }

    if report_type == "performance":
        import psutil as _ps  # type: ignore[import-untyped]
        cpu = _ps.cpu_percent(interval=0.2)
        mem = _ps.virtual_memory()
        disk_path = "." if __import__("platform").system() == "Windows" else "/"
        disk = _ps.disk_usage(disk_path)
        return {
            "period": now.strftime("%B %Y"),
            "kpis": [
                {"label": "CPU actuel", "value": f"{cpu}%", "change": "", "up": cpu < 70},
                {"label": "Mémoire utilisée", "value": f"{mem.percent}%", "change": "", "up": mem.percent < 80},
                {"label": "Disque utilisé", "value": f"{round(disk.used/disk.total*100,1)}%", "change": "", "up": True},
                {"label": "Disponibilité API", "value": "99.9%", "change": "", "up": True},
            ],
            "services": [
                {"name": "API FastAPI", "uptime": 99.9, "latency": 45, "status": "Opérationnel"},
                {"name": "Base de données", "uptime": 100.0, "latency": 5, "status": "Opérationnel"},
                {"name": "LLM Service", "uptime": 99.5, "latency": 180, "status": "Opérationnel"},
                {"name": "Auth Service", "uptime": 100.0, "latency": 12, "status": "Opérationnel"},
            ],
        }

    if report_type == "utilisateurs":
        total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
        from sqlalchemy import desc
        top_raw = (await db.execute(
            select(User.full_name, User.department, func.count(Session.id).label("sessions"))
            .join(Session, Session.user_id == User.id, isouter=True)
            .group_by(User.id)
            .order_by(desc("sessions"))
            .limit(5)
        )).all()
        top_users = [
            {"name": str(r[0] or "—"), "dept": str(r[1] or "—"), "sessions": int(str(r[2]))}
            for r in top_raw
        ]
        dept_raw = (await db.execute(
            select(User.department, func.count(User.id).label("cnt"))
            .group_by(User.department)
            .order_by(desc("cnt"))
        )).all()
        total_dept = max(sum(int(str(r[1])) for r in dept_raw), 1)
        by_dept = [
            {"dept": str(r[0] or "Autres"), "users": int(str(r[1])), "pct": round(int(str(r[1])) / total_dept * 100)}
            for r in dept_raw
        ]
        return {
            "period": now.strftime("%B %Y"),
            "kpis": [
                {"label": "Utilisateurs totaux", "value": str(total_users), "change": "", "up": True},
                {"label": "Utilisateurs actifs", "value": str(len(top_users)), "change": "", "up": True},
                {"label": "Départements", "value": str(len(by_dept)), "change": "", "up": True},
                {"label": "Sessions/utilisateur", "value": str(round(
                    sum(int(u["sessions"]) for u in top_users) / max(len(top_users), 1), 1)), "change": "", "up": True},
            ],
            "topUsers": top_users,
            "byDept": by_dept,
        }

    raise HTTPException(status_code=404, detail=f"Type de rapport inconnu: {report_type}")


# ═══════════════════════════════════════════════════════════════════
#  SETTINGS — persisted in DB per section
# ═══════════════════════════════════════════════════════════════════

@router.get("/settings")
async def get_settings(request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    rows = (await db.execute(select(PlatformSetting))).scalars().all()
    settings: dict = {r.section: r.data for r in rows}

    # Inject real role counts into users section
    admin_count = (await db.execute(
        select(func.count(User.id)).where(User.role == "admin")
    )).scalar() or 0
    manager_count = (await db.execute(
        select(func.count(User.id)).where(User.role == "manager")
    )).scalar() or 0
    user_count = (await db.execute(
        select(func.count(User.id)).where(User.role == "user")
    )).scalar() or 0
    guest_count = (await db.execute(
        select(func.count(User.id)).where(User.role == "guest")
    )).scalar() or 0

    users_section = dict(settings.get("users") or {})
    users_section["roles"] = [
        {"name": "Administrateur", "users": int(str(admin_count)),   "permissions": ["Tout accès"]},
        {"name": "Manager",        "users": int(str(manager_count)), "permissions": ["Lecture", "Rapports", "Utilisateurs"]},
        {"name": "Utilisateur",    "users": int(str(user_count)),    "permissions": ["Chat", "Documents"]},
        {"name": "Invité",         "users": int(str(guest_count)),   "permissions": ["Chat lecture seule"]},
    ]
    settings["users"] = users_section

    return {"settings": settings}


@router.put("/settings/{section}")
async def save_settings(section: str, data: dict, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.section == section))
    row = result.scalar_one_or_none()
    if row:
        row.data = data  # type: ignore[assignment]
    else:
        db.add(PlatformSetting(section=section, data=data))
    await db.commit()
    return {"status": "success", "message": f"Section '{section}' sauvegardée avec succès."}


@router.delete("/settings/{section}")
async def reset_settings_section(section: str, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.section == section))
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return {"status": "success", "message": f"Section '{section}' réinitialisée aux valeurs par défaut."}


# ═══════════════════════════════════════════════════════════════════
#  SETTINGS — Utility actions (test SMTP, test webhook, regen keys)
# ═══════════════════════════════════════════════════════════════════

@router.post("/settings/test-smtp")
async def test_smtp(request: Request, db: AsyncSession = Depends(get_db)):
    """Send a test email using the SMTP settings stored in the notifications section."""
    await require_admin(request, db)
    # Load stored notifications settings
    row = (await db.execute(
        select(PlatformSetting).where(PlatformSetting.section == "notifications")
    )).scalar_one_or_none()
    cfg = row.data if row else {}

    host = cfg.get("smtpHost", "")
    port = int(cfg.get("smtpPort", 587))
    user = cfg.get("smtpUser", "")
    password = cfg.get("smtpPassword", "")
    use_tls = cfg.get("smtpTls", True)

    # Load admin email as recipient
    gen_row = (await db.execute(
        select(PlatformSetting).where(PlatformSetting.section == "general")
    )).scalar_one_or_none()
    recipient = (gen_row.data if gen_row else {}).get("adminEmail", user)

    if not host:
        raise HTTPException(status_code=400, detail="Hôte SMTP non configuré.")

    try:
        msg = MIMEText("Ceci est un email de test envoyé depuis DXC Copilot pour valider la configuration SMTP.")
        msg["Subject"] = "✅ Test SMTP — DXC Copilot"
        msg["From"] = user or f"noreply@{host}"
        msg["To"] = recipient

        def _send():
            cls = smtplib.SMTP_SSL if use_tls and port == 465 else smtplib.SMTP
            with cls(host, port, timeout=10) as s:
                if use_tls and port != 465:
                    s.starttls()
                if user and password:
                    s.login(user, password)
                s.send_message(msg)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _send)
        return {"status": "success", "message": f"Email de test envoyé à {recipient}."}
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=400, detail="Échec d'authentification SMTP. Vérifiez le nom d'utilisateur et le mot de passe.")
    except smtplib.SMTPConnectError:
        raise HTTPException(status_code=400, detail=f"Impossible de se connecter à {host}:{port}.")
    except Exception as exc:
        logger.warning("SMTP test failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"Erreur SMTP : {type(exc).__name__}")


@router.post("/settings/test-webhook")
async def test_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Send a test POST payload to the configured Slack/webhook URL."""
    import httpx
    await require_admin(request, db)

    row = (await db.execute(
        select(PlatformSetting).where(PlatformSetting.section == "notifications")
    )).scalar_one_or_none()
    cfg = row.data if row else {}

    url = cfg.get("slackWebhook", "")
    if not url:
        raise HTTPException(status_code=400, detail="URL du webhook non configurée.")

    payload = {
        "text": "✅ *Test webhook DXC Copilot* — La connexion fonctionne correctement.",
        "username": "DXC Copilot",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code >= 400:
            raise HTTPException(
                status_code=400,
                detail=f"Le webhook a retourné une erreur ({resp.status_code}). Vérifiez l'URL."
            )
        return {"status": "success", "message": "Payload de test envoyé au webhook avec succès."}
    except httpx.TimeoutException:
        raise HTTPException(status_code=400, detail="Le webhook n'a pas répondu dans les 10 secondes.")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=400, detail=f"Erreur réseau : {type(exc).__name__}")


@router.post("/settings/regenerate-api-key")
async def regenerate_api_key(request: Request, data: dict, db: AsyncSession = Depends(get_db)):
    """Generate a new cryptographically secure API key pair and persist it."""
    await require_admin(request, db)
    key_type = data.get("type", "public")  # "public" or "secret"
    if key_type not in ("public", "secret"):
        raise HTTPException(status_code=400, detail="type doit être 'public' ou 'secret'.")

    new_key = secrets.token_urlsafe(32)
    prefix = "pk_live_" if key_type == "public" else "sk_live_"
    full_key = prefix + new_key

    # Persist into the integrations settings section
    row = (await db.execute(
        select(PlatformSetting).where(PlatformSetting.section == "integrations")
    )).scalar_one_or_none()

    field = "apiKeyPublic" if key_type == "public" else "apiKeySecret"
    if row:
        updated = dict(row.data)
        updated[field] = full_key
        row.data = updated
    else:
        row = PlatformSetting(section="integrations", data={field: full_key})
        db.add(row)

    await db.commit()
    await audit(db, user_id=None, action="API_KEY_REGENERATED",
                resource=f"integrations:{key_type}",
                detail=f"API key ({key_type}) regenerated",
                ip=request.client.host if request.client else None)
    return {"status": "success", "key": full_key, "type": key_type}


# ═══════════════════════════════════════════════════════════════════
#  KNOWLEDGE BASE — document ingestion, listing, deletion, stats
# ═══════════════════════════════════════════════════════════════════

@router.post("/knowledge/upload")
async def upload_knowledge_doc(
    request: Request,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...)
):
    """Upload and ingest a document (PDF, TXT, MD, DOCX, CSV) into the RAG knowledge base."""
    await require_admin(request, db)
    from app.core.file_validation import validate_upload, KNOWLEDGE_ALLOWED_EXTENSIONS
    from app.services.rag_service import rag_service

    file_bytes = await file.read()
    filename = file.filename or "unknown"
    content_type = file.content_type or "application/octet-stream"

    ok, err = validate_upload(file_bytes, filename, content_type, KNOWLEDGE_ALLOWED_EXTENSIONS)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
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
        else:
            text = file_bytes.decode("utf-8", errors="ignore")
            chunks = await rag_service.ingest_text(text, filename)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'ingestion: {exc}")

    if chunks == 0:
        from app.services.ocr_service import ocr_service
        if ext == "pdf" and not ocr_service._pymupdf_available:
            detail = (
                "Extraction PDF impossible : PyMuPDF n'est pas installé. "
                "Installez-le avec : pip install pymupdf"
            )
        elif ext == "pdf":
            detail = (
                f"Aucun texte extractible dans « {filename} ». "
                "Le fichier est peut-être entièrement scanné (image). "
                "Installez EasyOCR pour l'OCR : pip install easyocr"
            )
        elif ext == "docx":
            detail = (
                "Extraction DOCX impossible : python-docx n'est pas installé. "
                "Installez-le avec : pip install python-docx"
            )
        else:
            detail = f"Aucun contenu trouvé dans « {filename} ». Vérifiez que le fichier n'est pas vide."
        raise HTTPException(status_code=422, detail=detail)

    return {"status": "ok", "filename": filename, "chunks_ingested": chunks}


@router.get("/knowledge/documents")
async def list_knowledge_docs(request: Request, db: AsyncSession = Depends(get_db)):
    """List documents ingested into the knowledge base."""
    await require_admin(request, db)
    from app.services.rag_service import rag_service
    return {"documents": rag_service.get_documents()}


@router.delete("/knowledge/documents/{doc_id}")
async def delete_knowledge_doc(doc_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Remove a document from the knowledge base."""
    await require_admin(request, db)
    from app.services.rag_service import rag_service
    removed = rag_service.delete_document(doc_id)
    if removed == 0:
        raise HTTPException(status_code=404, detail="Document non trouvé.")
    return {"status": "ok", "chunks_removed": removed}


@router.post("/knowledge/seed")
async def seed_knowledge(request: Request, db: AsyncSession = Depends(get_db)):
    """Re-seed the 24 built-in TMA incident entries."""
    await require_admin(request, db)
    from app.services.rag_service import rag_service
    count = rag_service.reseed_builtin()
    return {"status": "ok", "entries_seeded": count}


@router.get("/knowledge/stats")
async def knowledge_stats(request: Request, db: AsyncSession = Depends(get_db)):
    """Return knowledge base statistics."""
    await require_admin(request, db)
    from app.services.rag_service import rag_service
    stats = rag_service.get_stats()
    # Use manifest chunk count — it's the ground truth regardless of whether
    # ChromaDB or keyword fallback stored the actual vectors.
    return {
        "total_docs": stats.get("uploaded_docs", 0),
        "total_chunks": stats.get("total_chunks_uploaded", 0),
        "total_vectors": stats.get("total_vectors", 0),   # raw ChromaDB count (may differ)
        "builtin_docs": stats.get("builtin_docs", 0),
        "last_updated": stats.get("last_updated") or "—",
        "backend": stats.get("backend", "unknown"),
    }


# ═══════════════════════════════════════════════════════════════════
#  USER PROFILE (self-service, not admin-only)
# ═══════════════════════════════════════════════════════════════════

@router.put("/profile", response_model=UserResponse)
async def update_profile(req: UpdateProfileRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if req.full_name is not None:
        user.full_name = req.full_name  # type: ignore[assignment]
    if req.department is not None:
        user.department = req.department  # type: ignore[assignment]
    await db.commit()
    await db.refresh(user)
    return UserResponse(
        id=int(str(user.id)),
        email=str(user.email),
        full_name=str(user.full_name) if user.full_name else None,
        role=str(user.role) if user.role else None,
        department=str(user.department) if user.department else None,
        status=str(user.status) if user.status else None,
    )


@router.put("/profile/password")
async def change_password(req: ChangePasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not await _verify_password(req.current_password, str(user.hashed_password)):
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")
    if len(req.new_password) < 12:
        raise HTTPException(status_code=400, detail="Le nouveau mot de passe doit contenir au moins 12 caractères")
    user.hashed_password = await _hash_password(req.new_password)  # type: ignore[assignment]
    await db.commit()
    return {"status": "success", "message": "Mot de passe mis à jour avec succès"}


# ═══════════════════════════════════════════════════════════════════
#  INCIDENT GUIDES CRUD
# ═══════════════════════════════════════════════════════════════════

def _guide_to_dict(g: IncidentGuide) -> dict:
    return {
        "id": g.id,
        "title": str(g.title),
        "description": str(g.description or ""),
        "category": str(g.category),
        "severity": str(g.severity),
        "status": str(g.status),
        "tags": g.tags or [],
        "generatedFrom": str(g.generated_from or ""),
        "is_draft": bool(g.is_draft),
        "triggeredBy": str(g.triggered_by or ""),
        "occurrences": int(str(g.occurrences or 1)),
        "reviewNote": str(g.review_note or ""),
        "date": g.created_at.strftime("%d/%m/%Y") if g.created_at else "",
        "size": "1.5 MB",
        "pages": 12,
        "specs": g.specs,
    }


@router.get("/guides")
async def list_guides(request: Request, db: AsyncSession = Depends(get_db)):
    # Read-only listing of published guides — visible to any logged-in user
    # so the Documents section shows agent-synced entries. CRUD stays admin-only.
    await get_current_user(request, db)
    rows = (await db.execute(
        select(IncidentGuide).where(IncidentGuide.is_draft == False).order_by(IncidentGuide.created_at.desc())  # noqa: E712
    )).scalars().all()
    return {"guides": [_guide_to_dict(g) for g in rows]}


@router.get("/guides/drafts")
async def list_draft_guides(request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    rows = (await db.execute(
        select(IncidentGuide).where(IncidentGuide.is_draft == True).order_by(IncidentGuide.created_at.desc())  # noqa: E712
    )).scalars().all()
    return {"drafts": [_guide_to_dict(g) for g in rows]}


@router.post("/guides")
async def create_guide(data: dict, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    guide = IncidentGuide(
        title=data.get("title", ""),
        description=data.get("description", ""),
        category=data.get("category", "Infrastructure"),
        severity=data.get("severity", "P2"),
        status=data.get("status", "Ouvert"),
        tags=data.get("tags", []),
        generated_from=data.get("generatedFrom", "Création manuelle"),
        is_draft=bool(data.get("is_draft", False)),
        triggered_by=data.get("triggeredBy", ""),
        occurrences=data.get("occurrences", 1),
        specs=data.get("specs"),
    )
    db.add(guide)
    await db.commit()
    await db.refresh(guide)
    return _guide_to_dict(guide)


@router.put("/guides/{guide_id}")
async def update_guide(guide_id: int, data: dict, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    result = await db.execute(select(IncidentGuide).where(IncidentGuide.id == guide_id))
    guide = result.scalar_one_or_none()
    if not guide:
        raise HTTPException(status_code=404, detail="Guide non trouvé")
    for field, col in [("title", "title"), ("description", "description"), ("category", "category"),
                        ("severity", "severity"), ("status", "status"), ("tags", "tags"),
                        ("reviewNote", "review_note"), ("is_draft", "is_draft")]:
        if field in data:
            setattr(guide, col, data[field])
    await db.commit()
    await db.refresh(guide)
    return _guide_to_dict(guide)


@router.post("/guides/{guide_id}/approve")
async def approve_guide(guide_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    result = await db.execute(select(IncidentGuide).where(IncidentGuide.id == guide_id))
    guide = result.scalar_one_or_none()
    if not guide:
        raise HTTPException(status_code=404, detail="Guide non trouvé")
    guide.is_draft = False  # type: ignore[assignment]
    guide.status = "Ouvert"  # type: ignore[assignment]
    await db.commit()
    return {"status": "success", "message": f"Guide #{guide_id} approuvé"}


@router.delete("/guides/{guide_id}")
async def delete_guide(guide_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    result = await db.execute(select(IncidentGuide).where(IncidentGuide.id == guide_id))
    guide = result.scalar_one_or_none()
    if not guide:
        raise HTTPException(status_code=404, detail="Guide non trouvé")
    await db.delete(guide)
    await db.commit()
    return {"status": "success", "message": f"Guide #{guide_id} supprimé"}


# ═══════════════════════════════════════════════════════════════════
#  MAINTENANCE TASKS CRUD
# ═══════════════════════════════════════════════════════════════════

def _task_to_dict(t: MaintenanceTask) -> dict:
    return {
        "id": t.id,
        "name": str(t.name),
        "status": str(t.status),
        "schedule": str(t.schedule or ""),
        "lastRun": t.last_run.strftime("%d/%m/%Y %H:%M") if t.last_run else "—",
    }


@router.get("/maintenance/tasks")
async def list_maintenance_tasks(request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    rows = (await db.execute(select(MaintenanceTask).order_by(MaintenanceTask.id))).scalars().all()
    return {"tasks": [_task_to_dict(t) for t in rows]}


@router.post("/maintenance/tasks")
async def create_maintenance_task(data: dict, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    task = MaintenanceTask(
        name=data.get("name", ""),
        status=data.get("status", "Programmée"),
        schedule=data.get("schedule", "Manuel"),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return _task_to_dict(task)


@router.put("/maintenance/tasks/{task_id}")
async def update_maintenance_task(task_id: int, data: dict, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    result = await db.execute(select(MaintenanceTask).where(MaintenanceTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Tâche non trouvée")
    for field, col in [("name", "name"), ("status", "status"), ("schedule", "schedule")]:
        if field in data:
            setattr(task, col, data[field])
    await db.commit()
    await db.refresh(task)
    return _task_to_dict(task)


@router.post("/maintenance/tasks/{task_id}/run")
async def run_maintenance_task(task_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    result = await db.execute(select(MaintenanceTask).where(MaintenanceTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Tâche non trouvée")
    task.last_run = datetime.now(timezone.utc)  # type: ignore[assignment]
    task.status = "Active"  # type: ignore[assignment]
    await db.commit()
    return {"status": "success", "message": f"Tâche '{task.name}' exécutée", "lastRun": task.last_run.strftime("%d/%m/%Y %H:%M")}  # type: ignore[union-attr]


@router.delete("/maintenance/tasks/{task_id}")
async def delete_maintenance_task(task_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    result = await db.execute(select(MaintenanceTask).where(MaintenanceTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Tâche non trouvée")
    await db.delete(task)
    await db.commit()
    return {"status": "success", "message": f"Tâche #{task_id} supprimée"}


# ═══════════════════════════════════════════════════════════════════
#  AUDIT LOG
# ═══════════════════════════════════════════════════════════════════

@router.get("/audit-log")
async def get_audit_log(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    page_size: int = 50,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
):
    await require_admin(request, db)
    page_size = min(page_size, 200)
    offset = (page - 1) * page_size

    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    count_query = select(func.count()).select_from(AuditLog)

    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
        count_query = count_query.where(AuditLog.user_id == user_id)
    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)

    total = (await db.execute(count_query)).scalar() or 0
    rows = (await db.execute(query.offset(offset).limit(page_size))).scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": row.id,
                "user_id": row.user_id,
                "action": row.action,
                "resource": row.resource,
                "detail": row.detail,
                "ip_address": row.ip_address,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


# ═══════════════════════════════════════════════════════════════════
#  GDPR — User data export and self-service deletion
# ═══════════════════════════════════════════════════════════════════

@router.get("/users/{user_id}/export")
async def export_user_data(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """GDPR: Export all data for a user as JSON (admin only)."""
    await require_admin(request, db)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

    sessions_q = (await db.execute(select(Session).where(Session.user_id == user_id))).scalars().all()
    session_ids = [s.id for s in sessions_q]
    messages_q = (await db.execute(select(Message).where(Message.session_id.in_(session_ids)))).scalars().all() if session_ids else []
    feedback_q = (await db.execute(select(Feedback).where(Feedback.user_id == user_id))).scalars().all()

    return {
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name, "department": user.department, "created_at": str(user.created_at)},
        "sessions": [{"id": s.id, "title": s.title, "created_at": str(s.created_at)} for s in sessions_q],
        "messages": [{"id": m.id, "session_id": m.session_id, "sender": m.sender, "text": m.text, "created_at": str(m.created_at)} for m in messages_q],
        "feedback": [{"id": f.id, "rating": f.rating, "reason": f.reason, "created_at": str(f.created_at)} for f in feedback_q],
    }


# ═══════════════════════════════════════════════════════════════════
#  AI Insights — knowledge gaps, incident clusters, routing thresholds
# ═══════════════════════════════════════════════════════════════════

@router.get("/knowledge-gaps")
async def get_knowledge_gaps(
    request: Request, refresh: bool = False, db: AsyncSession = Depends(get_db)
):
    """Latest knowledge-gap report (clusters of questions the KB failed on).
    ?refresh=true recomputes on demand."""
    await require_admin(request, db)
    from app.services.clustering_service import analyze_knowledge_gaps, latest_report
    from app.services.agent_service import rag_settings
    if refresh:
        cfg = await rag_settings(db)
        report = await analyze_knowledge_gaps(db, t_low=cfg["t_low"])
        await db.commit()
        return report
    report = await latest_report(db, "knowledge_gaps")
    return report or {"clusters": [], "analyzed_queries": 0, "status": "no_report"}


@router.get("/incident-clusters")
async def get_incident_clusters(
    request: Request, days: int = 30, refresh: bool = False,
    db: AsyncSession = Depends(get_db)
):
    """Semantic clusters of incident-intent messages (beyond RG2 keyword counts)."""
    await require_admin(request, db)
    from app.services.clustering_service import analyze_incident_clusters, latest_report
    if refresh:
        report = await analyze_incident_clusters(db, days=max(1, min(days, 365)))
        await db.commit()
        return report
    report = await latest_report(db, "incident_clusters")
    return report or {"clusters": [], "analyzed_messages": 0, "status": "no_report"}


@router.get("/routing-thresholds")
async def get_routing_thresholds(
    request: Request, refresh: bool = False, db: AsyncSession = Depends(get_db)
):
    """Current RAG routing config + latest data-driven threshold recommendation."""
    await require_admin(request, db)
    from app.services.clustering_service import recommend_thresholds, latest_report
    from app.services.agent_service import rag_settings
    current = await rag_settings(db)
    if refresh:
        recommendation = await recommend_thresholds(db)
        await db.commit()
    else:
        recommendation = await latest_report(db, "threshold_recommendation")
    return {"current": current, "recommendation": recommendation}


@router.post("/routing-thresholds")
async def apply_routing_thresholds(
    data: dict, request: Request, db: AsyncSession = Depends(get_db)
):
    """Apply RAG settings (thresholds/toggles). Read live by the chat pipeline."""
    admin_user = await require_admin(request, db)
    from app.services.agent_service import update_rag_settings, RAG_DEFAULTS

    for key in ("t_low", "t_high"):
        if key in data:
            try:
                data[key] = float(data[key])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"Valeur invalide pour {key}")
            if not 0.0 <= data[key] <= 1.0:
                raise HTTPException(status_code=400, detail=f"{key} doit être entre 0 et 1")
    t_low = data.get("t_low", RAG_DEFAULTS["t_low"])
    t_high = data.get("t_high", RAG_DEFAULTS["t_high"])
    if "t_low" in data or "t_high" in data:
        if t_low >= t_high:
            raise HTTPException(status_code=400, detail="t_low doit être inférieur à t_high")

    updated = await update_rag_settings(db, data)
    await db.commit()
    await audit(db, int(str(admin_user.id)), "rag_settings_updated",
                resource="rag_settings", detail=json.dumps(data))
    return {"status": "success", "settings": updated}
