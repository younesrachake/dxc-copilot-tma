"""
Test fixtures — hermetic FastAPI app with a throwaway SQLite DB.

Environment MUST be configured before any `app.*` import:
  - DISABLE_LOCAL_ML / DISABLE_CHROMA make the AI services fall back to their
    pure-python paths (no model downloads, no vector store on disk)
  - DATABASE_URL points at a per-session temp SQLite file
Lifespan is not run by httpx's ASGITransport, so DB init/seeding happens here.
"""
import asyncio
import os
import pathlib
import tempfile

_TMP = tempfile.mkdtemp(prefix="dxc_test_")
os.environ["DISABLE_LOCAL_ML"] = "1"
os.environ["DISABLE_CHROMA"] = "1"
os.environ["KNOWLEDGE_BASE_DIR"] = str(pathlib.Path(_TMP, "kb"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{pathlib.Path(_TMP, 'test.db').as_posix()}"
os.environ["JWT_SECRET"] = "test_secret_key_with_at_least_32_characters"
os.environ["ENV"] = "development"
os.environ["LOG_DIR"] = str(pathlib.Path(_TMP, "logs"))

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from passlib.context import CryptContext
from sqlalchemy import select

from app.main import app                      # noqa: E402
from app.core.database import init_db, async_session  # noqa: E402
from app.models.db import User               # noqa: E402

ADMIN_EMAIL = "admin@test.local"
USER_EMAIL = "user@test.local"
PASSWORD = "TestPassword12345!"

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Rate limiting off — the suite logs in far more than 10 times/minute
app.state.limiter.enabled = False


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _database():
    await init_db()
    async with async_session() as db:
        existing = (await db.execute(select(User).where(User.email == ADMIN_EMAIL))).scalar_one_or_none()
        if not existing:
            hashed = _pwd.hash(PASSWORD)
            db.add_all([
                User(email=ADMIN_EMAIL, full_name="Test Admin", hashed_password=hashed,
                     role="admin", department="IT", status="active"),
                User(email=USER_EMAIL, full_name="Test User", hashed_password=hashed,
                     role="user", department="Support", status="active"),
            ])
            await db.commit()


def _new_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest_asyncio.fixture
async def client():
    async with _new_client() as c:
        yield c


async def _login(c: AsyncClient, email: str) -> AsyncClient:
    resp = await c.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, f"login failed for {email}: {resp.text}"
    return c


@pytest_asyncio.fixture
async def admin_client():
    # Own client instance — cookies must not be shared with user_client
    async with _new_client() as c:
        yield await _login(c, ADMIN_EMAIL)


@pytest_asyncio.fixture
async def user_client():
    async with _new_client() as c:
        yield await _login(c, USER_EMAIL)


@pytest.fixture
def fake_llm(monkeypatch):
    """Make the LLM 'available' with a canned deterministic reply."""
    from app.services.llm_service import llm_service

    async def fake_generate(*args, **kwargs):
        return "Réponse simulée basée sur la base de connaissances [1]."

    monkeypatch.setattr(llm_service, "_available", True)
    monkeypatch.setattr(llm_service, "generate_response", fake_generate)
    return llm_service


@pytest.fixture
def fake_rag(monkeypatch):
    """Deterministic KB hits with a strong top score (kb_primary routing)."""
    from app.services.rag_service import rag_service

    async def fake_search(query, n_results=3, rerank=True):
        return (
            ["Procédure de redémarrage: systemctl restart <service>."],
            [0.88],
            ["tma-restart"],
        )

    monkeypatch.setattr(rag_service, "search", fake_search)
    return rag_service
