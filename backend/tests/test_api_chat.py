"""Chat API tests — pipeline with mocked LLM/RAG, sessions, isolation."""
import pytest


@pytest.mark.asyncio
async def test_chat_requires_auth(client):
    resp = await client.post("/api/chat", data={"message": "bonjour"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_chat_happy_path_with_kb(user_client, fake_llm, fake_rag):
    resp = await user_client.post("/api/chat", data={"message": "Comment redémarrer un service ?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"]
    assert "Réponse simulée" in body["reply"]
    # fake_rag returns score 0.88 → kb_primary → sources exposed + [1] mapped
    assert body["sources"] == ["tma-restart"]
    assert body["citations"] == [{
        "index": 1, "source": "tma-restart",
        "snippet": "Procédure de redémarrage: systemctl restart <service>.",
    }]
    assert body["cached"] is False


@pytest.mark.asyncio
async def test_chat_fallback_mode_without_llm(user_client, fake_rag):
    # llm_service unavailable (no API keys in tests) → structured fallback reply
    resp = await user_client.post("/api/chat", data={"message": "Comment redémarrer un service ?"})
    assert resp.status_code == 200
    assert resp.json()["reply"]  # graceful degradation, never a 5xx


@pytest.mark.asyncio
async def test_chat_jira_keyword_returns_draft(user_client, fake_rag):
    resp = await user_client.post(
        "/api/chat", data={"message": "crée un ticket jira pour une erreur critique en production"}
    )
    assert resp.status_code == 200
    ticket = resp.json()["jira_ticket"]
    assert ticket is not None
    assert ticket["project"] == "TMA"
    assert ticket["priority"] == "Critique"


@pytest.mark.asyncio
async def test_chat_passes_conversation_history_to_llm(user_client, fake_rag, monkeypatch):
    """Second turn of a session must include the first exchange as history."""
    from app.services.llm_service import llm_service
    captured = {}

    async def capture_generate(*args, **kwargs):
        captured["history"] = kwargs.get("history")
        return "Réponse avec contexte."

    monkeypatch.setattr(llm_service, "_available", True)
    monkeypatch.setattr(llm_service, "generate_response", capture_generate)

    first = (await user_client.post(
        "/api/chat", data={"message": "quelle est la procédure de sauvegarde ?"}
    )).json()
    assert captured["history"] is None  # first turn: no history

    await user_client.post(
        "/api/chat",
        data={"message": "et pour la restauration ?", "session_id": first["session_id"]},
    )
    history = captured["history"]
    assert history is not None and len(history) == 2
    assert history[0]["role"] == "user"
    assert "sauvegarde" in history[0]["content"]
    assert history[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_chat_reuses_session(user_client, fake_rag):
    first = (await user_client.post("/api/chat", data={"message": "première question"})).json()
    sid = first["session_id"]
    second = (await user_client.post(
        "/api/chat", data={"message": "seconde question", "session_id": sid}
    )).json()
    assert second["session_id"] == sid

    msgs = (await user_client.get(f"/api/chat/sessions/{sid}/messages")).json()
    senders = [m["sender"] for m in msgs]
    assert senders == ["user", "bot", "user", "bot"]


@pytest.mark.asyncio
async def test_session_isolation_between_users(user_client, admin_client, fake_rag):
    sid = (await user_client.post("/api/chat", data={"message": "message privé"})).json()["session_id"]
    # Another user must not read or post into this session
    resp = await admin_client.get(f"/api/chat/sessions/{sid}/messages")
    assert resp.status_code == 404
    resp = await admin_client.post("/api/chat", data={"message": "intrusion", "session_id": sid})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_session(user_client, fake_rag):
    sid = (await user_client.post("/api/chat", data={"message": "à supprimer"})).json()["session_id"]
    resp = await user_client.delete(f"/api/chat/sessions/{sid}")
    assert resp.status_code == 200
    resp = await user_client.get(f"/api/chat/sessions/{sid}/messages")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_conversation_search_degrades_gracefully(user_client):
    # Vector index disabled in tests → endpoint must return empty, not error
    resp = await user_client.get("/api/chat/search", params={"q": "redis"})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


@pytest.mark.asyncio
async def test_chat_stream_emits_tokens_and_done(user_client, fake_rag, monkeypatch):
    from app.services.llm_service import llm_service

    async def fake_stream(*args, **kwargs):
        for piece in ["Bonjour", " monde"]:
            yield piece

    monkeypatch.setattr(llm_service, "_available", True)
    monkeypatch.setattr(llm_service, "generate_response_stream", fake_stream)

    events = []
    async with user_client.stream(
        "POST", "/api/chat/stream", data={"message": "question de test streaming"}
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                events.append(line[7:])
    assert "token" in events
    assert events[-1] == "done"
    assert "meta" in events
