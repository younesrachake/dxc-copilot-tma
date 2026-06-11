"""
Audit logging helper — records security-relevant admin actions to the audit_log table.
"""
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.db import AuditLog

logger = logging.getLogger(__name__)


async def audit(
    db: AsyncSession,
    user_id: Optional[int],
    action: str,
    resource: Optional[str] = None,
    detail: Optional[str] = None,
    ip: Optional[str] = None,
) -> None:
    """
    Persist an audit record. Never raises — failures are logged only.

    Args:
        db: Active async DB session (will flush, not commit — caller commits).
        user_id: ID of the user performing the action (None for system actions).
        action: Short action name, e.g. "USER_CREATE", "LOGIN_SUCCESS", "CONFIG_UPDATE".
        resource: Affected resource, e.g. "user:42", "session:abc-123".
        detail: Human-readable detail string.
        ip: Client IP address.
    """
    try:
        entry = AuditLog(
            user_id=user_id,
            action=action,
            resource=resource,
            detail=detail,
            ip_address=ip,
        )
        db.add(entry)
        await db.commit()
    except Exception as exc:
        logger.error("Audit log write failed (action=%s): %s", action, exc)
