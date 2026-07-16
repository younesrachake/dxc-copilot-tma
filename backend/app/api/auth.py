import asyncio
import functools
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from passlib.context import CryptContext
from jose import jwt

from app.core.database import get_db
from app.core.config import (
    JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_MINUTES, ENV,
    SSO_ENABLED, SSO_CLIENT_ID, SSO_CLIENT_SECRET, SSO_TENANT_ID, SSO_REDIRECT_URI,
    FRONTEND_URL,
)
from app.core.audit import audit
from app.core.limiter import limiter
from app.core import runtime_settings
from app.models.db import User, PasswordResetToken
from app.models.schemas import LoginRequest, LoginResponse, UserResponse, ForgotPasswordRequest, ResetPasswordRequest

# Fallback defaults — the live values come from runtime_settings.security,
# tunable via admin Settings → Sécurité.
_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_MINUTES = 15

router = APIRouter(prefix="/api/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Dummy hash used for constant-time comparison when email not found
_DUMMY_HASH = pwd_context.hash("dummy_constant_time_comparison_value")


async def verify_password(plain: str, hashed: str) -> bool:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(pwd_context.verify, plain, hashed))


def create_token(data: dict, expires_delta: timedelta) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _cookie_flags() -> dict:
    """Return secure cookie flags — secure=True only in production (requires HTTPS)."""
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": ENV == "production",
    }


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
async def login(request: Request, req: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    # Account lockout check — before password verification
    if user:
        locked_until = getattr(user, 'locked_until', None)
        if locked_until is not None:
            # Make timezone-aware for comparison
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            if locked_until > datetime.now(timezone.utc):
                remaining = int((locked_until - datetime.now(timezone.utc)).total_seconds() / 60) + 1
                raise HTTPException(
                    status_code=429,
                    detail=f"Compte verrouillé suite à trop de tentatives. Réessayez dans {remaining} minute(s)."
                )

    # Always run password verification to prevent timing attacks (even when user not found)
    hashed_to_check = str(user.hashed_password) if user else _DUMMY_HASH
    password_ok = await verify_password(req.password, hashed_to_check)

    if not user or not password_ok:
        # Increment failed attempts on known user
        if user:
            max_attempts = int(runtime_settings.security.get("maxFailedAttempts", _MAX_FAILED_ATTEMPTS))
            lockout_min = int(runtime_settings.security.get("lockoutDurationMin", _LOCKOUT_MINUTES))
            current_attempts = (getattr(user, 'failed_attempts', None) or 0) + 1
            user.failed_attempts = current_attempts  # type: ignore[assignment]
            if current_attempts >= max_attempts:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_min)  # type: ignore[assignment]
            await db.commit()
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    # Successful login — reset lockout counters
    user.failed_attempts = 0  # type: ignore[assignment]
    user.locked_until = None  # type: ignore[assignment]
    user.last_login = datetime.now(timezone.utc)  # type: ignore[assignment]
    await db.commit()

    await audit(db, int(str(user.id)), "login", resource="auth", ip=request.client.host if request.client else None)

    flags = _cookie_flags()
    ttl_min = runtime_settings.session_timeout_minutes()
    access_token = create_token({"sub": str(user.id), "role": user.role or "user"}, timedelta(minutes=ttl_min))
    refresh_token = create_token({"sub": str(user.id), "type": "refresh"}, timedelta(days=7))

    response.set_cookie("access_token", access_token, max_age=ttl_min * 60, **flags)
    response.set_cookie("refresh_token", refresh_token, max_age=7 * 24 * 3600, **flags)

    return {"message": "Connexion réussie", "user": {"id": user.id, "email": user.email, "full_name": user.full_name}}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"message": "Déconnexion réussie"}


@router.post("/refresh")
async def refresh_token(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token for new access + refresh tokens (rotation)."""
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="Refresh token manquant")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise ValueError("Not a refresh token")
        user_id = int(str(payload.get("sub", 0)))
    except Exception:
        raise HTTPException(status_code=401, detail="Refresh token invalide")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur non trouvé")

    flags = _cookie_flags()
    ttl_min = runtime_settings.session_timeout_minutes()
    new_access = create_token({"sub": str(user.id), "role": user.role or "user"}, timedelta(minutes=ttl_min))
    new_refresh = create_token({"sub": str(user.id), "type": "refresh"}, timedelta(days=7))

    response.set_cookie("access_token", new_access, max_age=ttl_min * 60, **flags)
    response.set_cookie("refresh_token", new_refresh, max_age=7 * 24 * 3600, **flags)

    return {"message": "Tokens renouvelés"}


@router.get("/me", response_model=UserResponse)
async def get_me(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Non authentifié")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            raise HTTPException(status_code=401, detail="Token invalide")
        user_id = int(sub)
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    return UserResponse(
        id=int(str(user.id)), email=str(user.email), full_name=str(user.full_name or ""),
        role=str(user.role or "user"), department=str(user.department or ""),
        status=str(user.status or "active")
    )


# ── SSO / OIDC endpoints ──────────────────────────────────────────

@router.get("/sso/login")
async def sso_login():
    """Initiate SSO login — redirect to OIDC provider (Microsoft Entra ID / Azure AD)."""
    if not SSO_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="SSO non configuré. Contactez votre administrateur pour activer SSO_CLIENT_ID, SSO_CLIENT_SECRET et SSO_TENANT_ID."
        )
    from urllib.parse import urlencode

    # CSRF protection: generate a state value, persist it in a short-lived
    # cookie, and verify it on the callback.
    state = secrets.token_urlsafe(24)

    # Microsoft Azure AD / Generic OIDC authorization URL
    params = {
        "client_id": SSO_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": SSO_REDIRECT_URI,
        "scope": "openid profile email",
        "state": state,
        "response_mode": "query",
    }
    auth_url = (
        f"https://login.microsoftonline.com/{SSO_TENANT_ID}/oauth2/v2.0/authorize?"
        + urlencode(params)
    )

    redirect = RedirectResponse(url=auth_url)
    redirect.set_cookie(
        "sso_state", state,
        max_age=600,               # 10 minutes to complete login
        httponly=True,
        samesite="lax",
        secure=ENV == "production",
    )
    return redirect


@router.get("/sso/callback")
async def sso_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Handle OIDC callback — validate state, exchange code, provision user, set cookies."""
    if not SSO_ENABLED:
        raise HTTPException(status_code=503, detail="SSO non configuré")

    # Provider-reported error (e.g. user cancelled consent)
    if error:
        raise HTTPException(status_code=401, detail=f"Authentification SSO refusée: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Code d'autorisation SSO manquant")

    # CSRF: the state returned by the provider must match the one we issued.
    expected_state = request.cookies.get("sso_state")
    if not expected_state or not state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="État SSO invalide (possible tentative CSRF)")

    try:
        import httpx
        token_url = f"https://login.microsoftonline.com/{SSO_TENANT_ID}/oauth2/v2.0/token"
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(token_url, data={
                "client_id": SSO_CLIENT_ID,
                "client_secret": SSO_CLIENT_SECRET,
                "code": code,
                "redirect_uri": SSO_REDIRECT_URI,
                "grant_type": "authorization_code",
            })
        if token_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Échec de l'échange de code SSO")

        token_data = token_resp.json()
        id_token = token_data.get("id_token", "")

        # Decode id_token without verification (already validated by provider)
        import base64
        import json as _json
        parts = id_token.split(".")
        if len(parts) < 2:
            raise ValueError("Invalid id_token")
        padding = 4 - len(parts[1]) % 4
        claims = _json.loads(base64.urlsafe_b64decode(parts[1] + "=" * padding))

        email = claims.get("email") or claims.get("preferred_username", "")
        full_name = claims.get("name", email)

        if not email:
            raise HTTPException(status_code=400, detail="Impossible d'obtenir l'email depuis le provider SSO")

        # Create or retrieve user
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                email=email,
                full_name=full_name,
                hashed_password=pwd_context.hash(secrets.token_urlsafe(32)),
                role="user",
                status="active",
                department="",
            )
            db.add(user)
        user.last_login = datetime.now(timezone.utc)  # type: ignore[assignment]
        await db.commit()
        await db.refresh(user)

        flags = _cookie_flags()
        ttl_min = runtime_settings.session_timeout_minutes()
        access_token = create_token({"sub": str(user.id), "role": user.role or "user"}, timedelta(minutes=ttl_min))
        refresh_token_val = create_token({"sub": str(user.id), "type": "refresh"}, timedelta(days=7))

        # Cookies MUST be set on the response object we actually return.
        # Redirect the browser to the frontend SPA, not the backend host.
        redirect = RedirectResponse(url=f"{FRONTEND_URL}/chat")
        redirect.set_cookie("access_token", access_token, max_age=ttl_min * 60, **flags)
        redirect.set_cookie("refresh_token", refresh_token_val, max_age=7 * 24 * 3600, **flags)
        redirect.delete_cookie("sso_state")
        return redirect

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Erreur lors de l'authentification SSO")


# ── Password Reset ────────────────────────────────────────────────

@router.post("/forgot-password")
@limiter.limit("3/hour")
async def forgot_password(request: Request, req: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Generate a password reset token. Always returns 200 to prevent email enumeration."""
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if user:
        # Invalidate any existing tokens for this user
        existing_tokens = (await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        )).scalars().all()
        for t in existing_tokens:
            await db.delete(t)

        reset_token = PasswordResetToken(
            token=secrets.token_urlsafe(32),
            user_id=int(str(user.id)),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(reset_token)
        await db.commit()

        # Send email if SMTP is configured, otherwise log token (dev mode)
        try:
            from app.services.email_service import email_service
            await email_service.send_password_reset(str(user.email), reset_token.token)
        except Exception:
            # In development, log the token to allow testing without SMTP
            import logging
            logging.getLogger(__name__).warning(
                "SMTP not configured — reset token for %s: %s", user.email, reset_token.token
            )

    return {"message": "Si cet email existe, un lien de réinitialisation a été envoyé."}


@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Reset password using a valid token."""
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token == req.token)
    )
    reset_token = result.scalar_one_or_none()

    if not reset_token:
        raise HTTPException(status_code=400, detail="Token invalide ou expiré")

    if reset_token.used:
        raise HTTPException(status_code=400, detail="Ce token a déjà été utilisé")

    expires_at = reset_token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Token expiré")

    user_result = await db.execute(select(User).where(User.id == reset_token.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Utilisateur non trouvé")

    # Enforce the live password policy (admin Settings → Sécurité)
    policy_error = runtime_settings.validate_password(req.new_password)
    if policy_error:
        raise HTTPException(status_code=400, detail=policy_error)

    user.hashed_password = pwd_context.hash(req.new_password)  # type: ignore[assignment]
    reset_token.used = True  # type: ignore[assignment]
    await db.commit()

    return {"message": "Mot de passe réinitialisé avec succès"}
