import asyncio
import functools
import logging
import os
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from passlib.context import CryptContext
from sqlalchemy import select
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.limiter import limiter

from app.core.database import init_db, async_session
from app.core.config import validate_config, CORS_ORIGINS, SESSION_TTL_DAYS, ENV, SENTRY_DSN
from app.models.db import User, IncidentGuide, MaintenanceTask, Session as ChatSession
from app.api import auth, chat, admin, feedback, jira, terminal, agent

# ── Sentry error tracking (optional) ─────────────────────────────
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.1,
                        integrations=[FastApiIntegration()])
    except ImportError:
        logging.getLogger(__name__).warning("sentry-sdk not installed — skipping Sentry init")

validate_config()

# ── Persistent rotating file logging ─────────────────────────────
_log_dir = os.getenv("LOG_DIR", "/app/logs")
os.makedirs(_log_dir, exist_ok=True)
_file_handler = RotatingFileHandler(
    os.path.join(_log_dir, "app.log"),
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding="utf-8",
)
# JSON logs in production (LOG_JSON=1) so Loki/Grafana can query fields
if os.getenv("LOG_JSON", "").lower() in ("1", "true", "yes"):
    try:
        from pythonjsonlogger import jsonlogger
        _json_fmt = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        _file_handler.setFormatter(_json_fmt)
        for _h in logging.getLogger().handlers:
            _h.setFormatter(_json_fmt)
    except ImportError:
        pass
else:
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ"
    ))
_file_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(_file_handler)

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

logger = logging.getLogger(__name__)


async def _session_cleanup_loop():
    """Background task: delete sessions older than SESSION_TTL_DAYS."""
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=SESSION_TTL_DAYS)
            async with async_session() as db:
                result = await db.execute(
                    select(ChatSession).where(ChatSession.created_at < cutoff)
                )
                old_sessions = result.scalars().all()
                for s in old_sessions:
                    await db.delete(s)
                if old_sessions:
                    await db.commit()
                    logger.info("Session cleanup: removed %d sessions older than %d days",
                                len(old_sessions), SESSION_TTL_DAYS)
        except Exception as exc:
            logger.warning("Session cleanup error: %s", exc)
        await asyncio.sleep(86400)  # run once per day


async def _agent_scheduler_loop():
    """Background task: hourly wake — knowledge sync (when due), anomaly sweep,
    and the daily admin digest (when due)."""
    from app.services.agent_service import knowledge_sync_agent
    from app.services.anomaly_service import check_anomalies
    await asyncio.sleep(30)  # let startup seeding finish before the first run
    while True:
        try:
            async with async_session() as db:
                await knowledge_sync_agent.run_if_due(db)
        except Exception as exc:
            logger.warning("Knowledge sync agent error: %s", exc)
        try:
            async with async_session() as db:
                await check_anomalies(db)
        except Exception as exc:
            logger.warning("Anomaly sweep error: %s", exc)
        try:
            async with async_session() as db:
                await knowledge_sync_agent.run_digest_if_due(db)
        except Exception as exc:
            logger.warning("Daily digest error: %s", exc)
        await asyncio.sleep(3600)  # wake hourly, run only when due


async def _conversation_backfill_once():
    """One-shot: index pre-existing chat messages for semantic search
    (guarded by a platform_settings flag inside backfill)."""
    from app.services.conversation_index_service import conversation_index_service
    await asyncio.sleep(20)  # after startup seeding, before agent loop
    try:
        async with async_session() as db:
            await conversation_index_service.backfill(db)
    except Exception as exc:
        logger.warning("Conversation index backfill error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    # ── Seed admin user ───────────────────────────────────────────
    initial_password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    async with async_session() as session:
        result = await session.execute(select(User).where(User.email == "admin@dxc.com"))
        existing_admin = result.scalar_one_or_none()
        if not existing_admin:
            if not initial_password:
                logger.error(
                    "❌ INITIAL_ADMIN_PASSWORD env var is not set and no admin user exists. "
                    "Please set it to create the first admin account."
                )
                # Use a random secure password so the app can still start in dev
                import secrets
                initial_password = secrets.token_urlsafe(24)
                logger.warning("Generated random admin password — SET INITIAL_ADMIN_PASSWORD in .env!")
                logger.warning("Temporary admin password: %s", initial_password)
            if len(initial_password) < 12:
                logger.error("INITIAL_ADMIN_PASSWORD must be at least 12 characters")
                import sys
                sys.exit("Set a stronger INITIAL_ADMIN_PASSWORD (min 12 chars)")
            loop = asyncio.get_event_loop()
            hashed = await loop.run_in_executor(
                None, functools.partial(pwd_context.hash, initial_password)
            )
            admin_user = User(
                email="admin@dxc.com",
                full_name="DXC Admin",
                hashed_password=hashed,
                role="admin",
                department="IT",
                status="active"
            )
            session.add(admin_user)
            await session.commit()
            logger.info("✅ Admin user created: admin@dxc.com")
        else:
            logger.info("✅ Admin user already exists")

    # ── Seed incident guides if table is empty ────────────────────
    async with async_session() as session:
        guide_count = (await session.execute(select(IncidentGuide))).scalars().first()
        if not guide_count:
            seed_guides = [
                {"title": "Guide d'incident — Saturation mémoire API Gateway", "description": "L'API Gateway a atteint 98% d'utilisation mémoire après un pic de trafic non anticipé.", "category": "Infrastructure", "severity": "P2", "status": "Résolu", "tags": ["memory", "gateway", "autoscaling"], "generated_from": "Session : Analyse de perfor...", "is_draft": False},
                {"title": "Guide d'incident — Timeout LLM Service", "description": "Le service LLM a produit des timeouts répétés lors de l'inférence de modèles volumineux.", "category": "Performance", "severity": "P2", "status": "Résolu", "tags": ["llm", "timeout", "circuit-breaker"], "generated_from": "Session : Revue de code", "is_draft": False},
                {"title": "Guide d'incident — Pic de charge nocturne", "description": "Un pic inattendu de requêtes entre 02h et 04h a saturé les workers.", "category": "Infrastructure", "severity": "P2", "status": "Résolu", "tags": ["scaling", "workers", "cron"], "generated_from": "Session : Optimisation SQL", "is_draft": False},
                {"title": "Guide d'incident — Dégradation Auth Service", "description": "Le service d'authentification a répondu avec des latences anormales (>800ms) suite à une mauvaise configuration du cache Redis.", "category": "Sécurité", "severity": "P3", "status": "Résolu", "tags": ["auth", "redis", "latency"], "generated_from": "Session : Documentation API", "is_draft": False},
                {"title": "Guide d'incident — Erreurs 502 Bad Gateway", "description": "Des erreurs 502 intermittentes ont impacté 12% des requêtes pendant 45 minutes.", "category": "Disponibilité", "severity": "P2", "status": "En cours", "tags": ["502", "load-balancer", "health-check"], "generated_from": "Session : Déploiement CI/CD", "is_draft": False},
                {"title": "Guide d'incident — Fuite mémoire Queue Worker", "description": "Une fuite mémoire critique dans le service Queue Worker a provoqué des redémarrages en boucle.", "category": "Infrastructure", "severity": "P1", "status": "Résolu", "tags": ["memory-leak", "queue", "worker"], "generated_from": "Session : Revue de code", "is_draft": False},
                {"title": "Guide d'incident — Interruption base de données", "description": "Une interruption de 18 minutes de la base de données principale due à une migration mal planifiée.", "category": "Disponibilité", "severity": "P1", "status": "Résolu", "tags": ["database", "migration", "downtime"], "generated_from": "Session : Optimisation SQL", "is_draft": False},
                {"title": "Guide d'incident — Tentatives d'accès suspectes", "description": "1 842 tentatives d'accès non autorisées détectées en provenance de 3 IP distinctes.", "category": "Sécurité", "severity": "P2", "status": "Résolu", "tags": ["security", "firewall", "rate-limiting"], "generated_from": "Session : Documentation API", "is_draft": False},
                {"title": "Guide d'incident — Saturation CPU Service d'Inférence", "description": "Le service d'inférence LLM a atteint 98% d'utilisation CPU lors du traitement simultané de 12 requêtes.", "category": "Performance", "severity": "P2", "status": "En cours", "tags": ["cpu", "llm", "throttling"], "generated_from": "Session : Analyse de performance", "is_draft": True, "triggered_by": "Jean Dupont (jean.dupont@dxc.com)", "occurrences": 3},
                {"title": "Guide d'incident — Certificat SSL Expiré sur Staging", "description": "Le certificat SSL du sous-domaine staging a expiré sans renouvellement automatique.", "category": "Sécurité", "severity": "P3", "status": "En cours", "tags": ["ssl", "certificate", "staging"], "generated_from": "Session : Déploiement CI/CD", "is_draft": True, "triggered_by": "Marie Martin (marie.martin@dxc.com)", "occurrences": 3},
            ]
            for g in seed_guides:
                session.add(IncidentGuide(
                    title=g["title"], description=g["description"],
                    category=g["category"], severity=g["severity"], status=g["status"],
                    tags=g["tags"], generated_from=g.get("generated_from"),
                    is_draft=g.get("is_draft", False),
                    triggered_by=g.get("triggered_by"),
                    occurrences=g.get("occurrences", 1),
                ))
            await session.commit()
            logger.info("✅ Seeded %d incident guides", len(seed_guides))

    # ── Seed maintenance tasks if table is empty ──────────────────
    async with async_session() as session:
        task_exists = (await session.execute(select(MaintenanceTask))).scalars().first()
        if not task_exists:
            seed_tasks = [
                {"name": "Sauvegarde de la base de données", "status": "Programmée", "schedule": "Tous les jours à 02:00"},
                {"name": "Nettoyage des logs anciens", "status": "Active", "schedule": "Tous les dimanches à 03:00"},
                {"name": "Optimisation des index", "status": "Programmée", "schedule": "Premier du mois à 04:00"},
                {"name": "Mise à jour des dépendances", "status": "En attente", "schedule": "Manuel"},
                {"name": "Vérification de sécurité", "status": "Active", "schedule": "Tous les jours à 01:00"},
            ]
            for t in seed_tasks:
                session.add(MaintenanceTask(name=t["name"], status=t["status"], schedule=t["schedule"]))
            await session.commit()
            logger.info("✅ Seeded %d maintenance tasks", len(seed_tasks))

    # ── Start background session cleanup task ─────────────────────
    cleanup_task = asyncio.create_task(_session_cleanup_loop())

    # ── Start knowledge sync agent scheduler ──────────────────────
    agent_task = asyncio.create_task(_agent_scheduler_loop())

    # ── One-shot conversation index backfill ──────────────────────
    backfill_task = asyncio.create_task(_conversation_backfill_once())

    yield

    for task in (cleanup_task, agent_task, backfill_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="DXC Copilot TMA API",
    description="Backend API for DXC Copilot - TMA Assistant",
    version="1.0.0",
    lifespan=lifespan,
    # Restrict docs to prevent public exposure; access via /api/docs requires auth (see route below)
    docs_url=None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if ENV != "production" else None,
)

# ── Rate Limiting (OWASP) ─────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Global exception handler — no stack traces to clients ─────────
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "Erreur interne du serveur"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "X-Requested-With", "Authorization"],
)


# ── Security Headers Middleware ───────────────────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
    return response


# ── File Size Validation Middleware (15 MB limit) ─────────────────
@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH"):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_UPLOAD_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": "Le fichier dépasse la limite de 15 MB."}
            )
    return await call_next(request)


# ── Prometheus metrics (/metrics — blocked at nginx, scraped internally) ──
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator(
        excluded_handlers=["/metrics", "/healthz"],
        should_group_status_codes=False,
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    logger.info("Prometheus /metrics endpoint enabled")
except ImportError:
    logger.info("prometheus-fastapi-instrumentator not installed — /metrics disabled")


app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(feedback.router)
app.include_router(jira.router)
app.include_router(terminal.router)
app.include_router(agent.router)



@app.get("/")
async def root():
    return {"message": "DXC Copilot TMA API", "version": "1.0.0"}


@app.get("/healthz", include_in_schema=False)
async def healthz():
    """Lightweight liveness probe for Kubernetes/load balancers — no DB dependency."""
    return {"status": "ok"}
