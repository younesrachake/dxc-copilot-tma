"""Connector framework + integration API tests."""
import pytest

from app.connectors import registry


def test_all_connectors_load_with_tools():
    conns = registry.all()
    keys = {c.key for c in conns}
    assert keys == {"jira", "servicenow", "slack", "confluence", "github", "teams", "pagerduty"}
    assert sum(len(c.tools) for c in conns) >= 14
    # Every tool is read or write with a handler
    for c in conns:
        for t in c.tools:
            assert t.kind in ("read", "write")
            assert callable(t.handler)


def test_is_configured_requires_fields():
    jira = registry.get("jira")
    assert not jira.is_configured({})
    assert not jira.is_configured({"base_url": "x"})
    assert jira.is_configured({"base_url": "x", "email": "e", "api_token": "t", "project": "p"})


@pytest.mark.asyncio
async def test_enable_configure_exposes_agent_tools(admin_client):
    # Configure + enable Jira via the admin API
    resp = await admin_client.put("/api/admin/integrations/jira", json={
        "enabled": True, "base_url": "https://x.atlassian.net",
        "email": "a@b.com", "api_token": "secret", "project": "TMA",
    })
    assert resp.status_code == 200
    assert resp.json()["configured"] is True

    # Status list masks the secret and marks it enabled
    resp = await admin_client.get("/api/admin/integrations")
    jira = next(c for c in resp.json()["connectors"] if c["key"] == "jira")
    assert jira["enabled"] and jira["configured"]
    assert jira["config"]["api_token"] == "••••••••"
    tool_names = {t["name"] for t in jira["tools"]}
    assert "create_jira_issue" in tool_names


@pytest.mark.asyncio
async def test_integrations_require_admin(user_client, client):
    assert (await client.get("/api/admin/integrations")).status_code == 401
    assert (await user_client.get("/api/admin/integrations")).status_code == 403


@pytest.mark.asyncio
async def test_execute_rejects_unconfigured_tool(user_client):
    # Nothing enabled → the tool isn't registered → clear error, not a crash
    resp = await user_client.post("/api/integrations/execute",
                                  json={"tool": "post_slack_message", "args": {"text": "hi"}})
    assert resp.status_code == 400
