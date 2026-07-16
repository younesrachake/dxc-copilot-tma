"""
Live-applied admin settings.

The admin Settings page persists a JSON blob per section in the
``platform_settings`` table. On its own that only stores data — nothing reads
it back. This module projects the relevant sections onto in-process runtime
state so that saving a section in the UI actually changes behaviour, without a
server restart.

Flow:
  • startup  → ``load_and_apply_all(db)`` reads every stored section and applies it
  • on save  → the ``PUT /api/admin/settings/{section}`` endpoint calls
               ``apply_section(section, data)`` right after committing

Only settings that can be *honestly* enforced from application code are wired
here. Pure-infrastructure toggles (autoscaling, S3, CDN, LDAP, ISO/SOC…) are
intentionally left as declarative config — they would require real
infrastructure to take effect and are not faked.
"""
import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import PlatformSetting

logger = logging.getLogger(__name__)


# ── Live state (defaults mirror the frontend section defaults) ────────
security: dict[str, Any] = {
    "minPasswordLength": 10,
    "requireUppercase": True,
    "requireNumbers": True,
    "requireSpecialChars": True,
    "maxFailedAttempts": 5,
    "lockoutDurationMin": 15,
    "sessionTimeoutMin": 30,
}

general: dict[str, Any] = {
    "maintenanceMode": False,
    "registrationOpen": False,
}

users: dict[str, Any] = {
    "maxUsers": 500,
    "allowSelfRegistration": False,
}

storage: dict[str, Any] = {
    "maxFileSizeMb": 15,
}

audit_cfg: dict[str, Any] = {
    "auditLogEnabled": True,
    "logAdminActions": True,
    "logFailedLogins": True,
}


def _merge_known(target: dict, data: dict) -> None:
    """Copy only the keys we already know about, ignoring unrelated fields."""
    for k in target:
        if k in data and data[k] is not None:
            target[k] = data[k]


# ── Password policy helper (used by every password-setting endpoint) ──
def validate_password(password: str) -> Optional[str]:
    """Return an error message if the password violates the live policy, else None."""
    if len(password or "") < int(security["minPasswordLength"]):
        return f"Le mot de passe doit contenir au moins {security['minPasswordLength']} caractères."
    if security["requireUppercase"] and not any(c.isupper() for c in password):
        return "Le mot de passe doit contenir au moins une majuscule."
    if security["requireNumbers"] and not any(c.isdigit() for c in password):
        return "Le mot de passe doit contenir au moins un chiffre."
    if security["requireSpecialChars"] and password.isalnum():
        return "Le mot de passe doit contenir au moins un caractère spécial."
    return None


def session_timeout_minutes() -> int:
    try:
        return max(1, int(security["sessionTimeoutMin"]))
    except (TypeError, ValueError):
        return 30


def max_upload_bytes() -> int:
    try:
        return max(1, int(storage["maxFileSizeMb"])) * 1024 * 1024
    except (TypeError, ValueError):
        return 15 * 1024 * 1024


def audit_enabled(kind: str = "") -> bool:
    """Whether an audit write of the given kind should be persisted."""
    if not audit_cfg["auditLogEnabled"]:
        return False
    if kind == "admin" and not audit_cfg["logAdminActions"]:
        return False
    if kind == "failed_login" and not audit_cfg["logFailedLogins"]:
        return False
    return True


# ── Section application ───────────────────────────────────────────────
def _apply_ai(data: dict) -> None:
    # Imported lazily to avoid a circular import at module load time.
    from app.services.llm_service import llm_service
    llm_service.apply_runtime_config(data)


def apply_section(section: str, data: Any) -> None:
    """Project one saved settings section onto live runtime state."""
    if not isinstance(data, dict):
        return
    if section == "security":
        _merge_known(security, data)
    elif section == "general":
        _merge_known(general, data)
    elif section == "users":
        _merge_known(users, data)
    elif section == "storage":
        _merge_known(storage, data)
    elif section == "audit":
        _merge_known(audit_cfg, data)
    elif section == "ai":
        _apply_ai(data)


# Immutable snapshots of the shipped defaults, used to revert on reset.
import copy as _copy
_DEFAULTS = {
    "security": _copy.deepcopy(security),
    "general": _copy.deepcopy(general),
    "users": _copy.deepcopy(users),
    "storage": _copy.deepcopy(storage),
    "audit": _copy.deepcopy(audit_cfg),
}


def reset_section(section: str) -> None:
    """Revert one section's live state to the shipped defaults."""
    if section in _DEFAULTS:
        apply_section(section, _copy.deepcopy(_DEFAULTS[section]))
    elif section == "ai":
        _apply_ai({})  # empty → llm_service falls back to its built-in defaults


async def load_and_apply_all(db: AsyncSession) -> None:
    """Read every stored settings section and apply it. Best-effort per section."""
    try:
        rows = (await db.execute(select(PlatformSetting))).scalars().all()
    except Exception as exc:
        logger.warning("Could not load platform settings for runtime apply: %s", exc)
        return
    for r in rows:
        try:
            apply_section(str(r.section), r.data)
        except Exception as exc:
            logger.warning("Applying settings section '%s' failed: %s", r.section, exc)
    logger.info("Runtime settings applied from %d stored section(s)", len(rows))
