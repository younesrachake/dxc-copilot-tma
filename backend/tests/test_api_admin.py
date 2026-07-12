"""Admin API tests — RBAC, dashboards, RAG settings, insights."""
import pytest


@pytest.mark.asyncio
async def test_admin_endpoints_require_auth(client):
    for path in ("/api/admin/users", "/api/admin/dashboard", "/api/admin/routing-thresholds"):
        resp = await client.get(path)
        assert resp.status_code == 401, path


@pytest.mark.asyncio
async def test_admin_endpoints_reject_regular_user(user_client):
    resp = await user_client.get("/api/admin/users")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_list_users(admin_client):
    resp = await admin_client.get("/api/admin/users")
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    assert "admin@test.local" in emails


@pytest.mark.asyncio
async def test_dashboard_returns_real_counts(admin_client):
    resp = await admin_client.get("/api/admin/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_users"] >= 2
    assert isinstance(body["total_messages"], int)


@pytest.mark.asyncio
async def test_rag_settings_roundtrip(admin_client):
    # Read current config
    resp = await admin_client.get("/api/admin/routing-thresholds")
    assert resp.status_code == 200
    assert "t_low" in resp.json()["current"]

    # Apply new thresholds
    resp = await admin_client.post(
        "/api/admin/routing-thresholds", json={"t_low": 0.3, "t_high": 0.7}
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["t_low"] == 0.3

    # Restore defaults
    resp = await admin_client.post(
        "/api/admin/routing-thresholds", json={"t_low": 0.35, "t_high": 0.75}
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rag_settings_validation(admin_client):
    # t_low >= t_high must be rejected
    resp = await admin_client.post(
        "/api/admin/routing-thresholds", json={"t_low": 0.8, "t_high": 0.5}
    )
    assert resp.status_code == 400
    # Out-of-range values rejected
    resp = await admin_client.post("/api/admin/routing-thresholds", json={"t_low": 1.5})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_insight_reports_empty_state(admin_client):
    resp = await admin_client.get("/api/admin/knowledge-gaps")
    assert resp.status_code == 200
    assert "clusters" in resp.json()

    resp = await admin_client.get("/api/admin/incident-clusters")
    assert resp.status_code == 200
    assert "clusters" in resp.json()


@pytest.mark.asyncio
async def test_healthz_public(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
