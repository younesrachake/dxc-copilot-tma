"""Auth API tests — login, cookies, /me, refresh, logout."""
import pytest

from tests.conftest import ADMIN_EMAIL, USER_EMAIL, PASSWORD


@pytest.mark.asyncio
async def test_login_success_sets_cookies(client):
    resp = await client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == ADMIN_EMAIL
    cookies = resp.headers.get_list("set-cookie")
    assert any("access_token=" in c and "HttpOnly" in c for c in cookies)
    assert any("refresh_token=" in c for c in cookies)


@pytest.mark.asyncio
async def test_login_wrong_password_401(client):
    resp = await client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "WrongPassword123!"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email_401_no_enumeration(client):
    resp = await client.post("/api/auth/login", json={"email": "ghost@test.local", "password": PASSWORD})
    assert resp.status_code == 401
    # Same error message as wrong password — prevents user enumeration
    assert resp.json()["detail"] == "Email ou mot de passe incorrect"


@pytest.mark.asyncio
async def test_me_requires_auth(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_profile(user_client):
    resp = await user_client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == USER_EMAIL
    assert body["role"] == "user"


@pytest.mark.asyncio
async def test_refresh_rotates_tokens(user_client):
    resp = await user_client.post("/api/auth/refresh")
    assert resp.status_code == 200
    assert any("access_token=" in c for c in resp.headers.get_list("set-cookie"))


@pytest.mark.asyncio
async def test_refresh_without_cookie_401(client):
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_forgot_password_never_reveals_existence(client):
    for email in (ADMIN_EMAIL, "nobody@test.local"):
        resp = await client.post("/api/auth/forgot-password", json={"email": email})
        assert resp.status_code == 200
        assert "Si cet email existe" in resp.json()["message"]
