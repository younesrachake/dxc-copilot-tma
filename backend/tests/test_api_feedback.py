"""Feedback API tests."""
import pytest


@pytest.mark.asyncio
async def test_feedback_requires_auth(client):
    resp = await client.post("/api/feedback", json={"message_id": 1, "rating": "up"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_feedback_persists(user_client, fake_rag):
    # Create a real bot message to rate
    chat = (await user_client.post("/api/chat", data={"message": "question pour feedback"})).json()
    sid = chat["session_id"]
    msgs = (await user_client.get(f"/api/chat/sessions/{sid}/messages")).json()
    bot_msg = next(m for m in msgs if m["sender"] == "bot")

    resp = await user_client.post(
        "/api/feedback",
        json={"message_id": bot_msg["id"], "rating": "negative", "reason": "Réponse incomplète"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
