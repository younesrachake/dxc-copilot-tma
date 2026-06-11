import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./dxc_copilot.db")

_DEFAULT_SECRET = "dxc_copilot_dev_secret_key_change_in_prod_32chars"
JWT_SECRET = os.getenv("JWT_SECRET", _DEFAULT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
# API key loaded exclusively from .env — never hardcoded here
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

ENV = os.getenv("APP_ENV", "development").lower()

# SSO / OIDC configuration
SSO_CLIENT_ID = os.getenv("SSO_CLIENT_ID", "")
SSO_CLIENT_SECRET = os.getenv("SSO_CLIENT_SECRET", "")
SSO_TENANT_ID = os.getenv("SSO_TENANT_ID", "")
SSO_REDIRECT_URI = os.getenv("SSO_REDIRECT_URI", "http://localhost:8000/api/auth/sso/callback")
SSO_ENABLED = bool(SSO_CLIENT_ID and SSO_CLIENT_SECRET and SSO_TENANT_ID)

# SMTP email configuration
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@dxc.com")

# Sentry
SENTRY_DSN = os.getenv("SENTRY_DSN", "")

# Session cleanup
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "90"))

# CORS origins (comma-separated in env var for production)
CORS_ORIGINS_ENV = os.getenv("CORS_ORIGINS", "")
if CORS_ORIGINS_ENV:
    CORS_ORIGINS = [o.strip() for o in CORS_ORIGINS_ENV.split(",") if o.strip()]
else:
    CORS_ORIGINS = ["http://localhost:4200", "http://localhost:80", "http://localhost"]


def validate_config() -> None:
    errors = []
    warnings = []

    # JWT secret must never be the default in any real environment
    if JWT_SECRET == _DEFAULT_SECRET:
        if ENV == "production":
            errors.append("JWT_SECRET must be changed from the default value in production")
        else:
            warnings.append("JWT_SECRET is using the default dev value — change it before deploying")

    if len(JWT_SECRET) < 32:
        errors.append("JWT_SECRET must be at least 32 characters long")

    if not GROQ_API_KEY and not OPENAI_API_KEY:
        warnings.append("Neither GROQ_API_KEY nor OPENAI_API_KEY is set — LLM features will use fallback mode")
    elif not GROQ_API_KEY:
        warnings.append("GROQ_API_KEY is not set — LLM will use OpenAI only")

    if ENV == "production":
        if DATABASE_URL.startswith("sqlite"):
            errors.append("SQLite is not allowed in production. Set DATABASE_URL to a PostgreSQL connection string.")
        if not CORS_ORIGINS_ENV:
            warnings.append("CORS_ORIGINS env var not set — using localhost defaults in production")

    for w in warnings:
        logger.warning("⚠️  CONFIG: %s", w)

    if errors:
        for e in errors:
            logger.error("❌ CONFIG ERROR: %s", e)
        sys.exit(f"Configuration error(s) detected. Fix them before starting the server.\n" + "\n".join(errors))
