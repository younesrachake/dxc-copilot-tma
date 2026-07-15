"""Slack connector — Web API (chat.postMessage, search.messages)."""
from app.connectors.base import ConfigField, Connector, Tool
from app.connectors.http import ConnectorError, request

API = "https://slack.com/api"


def _headers(cfg: dict) -> dict:
    return {"Authorization": f"Bearer {cfg['bot_token']}", "Content-Type": "application/json; charset=utf-8"}


async def _post_message(cfg: dict, args: dict) -> dict:
    channel = args.get("channel") or cfg.get("default_channel", "")
    data = await request("POST", f"{API}/chat.postMessage", headers=_headers(cfg),
                         json={"channel": channel, "text": args["text"][:3000]})
    if not data.get("ok"):
        raise ConnectorError(f"Slack: {data.get('error', 'échec de publication')}")
    return {"channel": channel, "ts": data.get("ts", ""), "status": "Publié"}


async def _search(cfg: dict, args: dict) -> dict:
    # search.messages requires a user token; degrade gracefully if unsupported
    data = await request("GET", f"{API}/search.messages",
                         headers={"Authorization": f"Bearer {cfg['bot_token']}"},
                         params={"query": args["query"], "count": 5})
    if not data.get("ok"):
        raise ConnectorError(f"Slack: {data.get('error', 'recherche indisponible')}")
    matches = (data.get("messages") or {}).get("matches", [])
    return {"count": len(matches),
            "messages": [{"text": m.get("text", "")[:200], "channel": (m.get("channel") or {}).get("name", ""),
                          "permalink": m.get("permalink", "")} for m in matches]}


class SlackConnector(Connector):
    key = "slack"
    name = "Slack"
    icon = "message-circle"
    description = "Publier des alertes et résumés d'incidents dans Slack."
    config_fields = [
        ConfigField("bot_token", "Jeton bot (xoxb-…)", "password"),
        ConfigField("default_channel", "Canal par défaut", "text", "#incidents", required=False),
    ]
    tools = [
        Tool("post_slack_message", "Publie un message dans un canal Slack.", "write",
             {"text": {"type": "string", "description": "Contenu du message"},
              "channel": {"type": "string", "description": "Canal (optionnel, défaut configuré)"}},
             ["text"], _post_message,
             summarize=lambda a: f"Publier dans Slack {a.get('channel', '(canal par défaut)')} : « {a.get('text', '')[:70]} »"),
        Tool("search_slack", "Recherche des messages Slack.", "read",
             {"query": {"type": "string"}}, ["query"], _search),
    ]

    def is_configured(self, cfg: dict) -> bool:
        return bool((cfg or {}).get("bot_token"))

    async def test_connection(self, cfg: dict) -> dict:
        try:
            data = await request("GET", f"{API}/auth.test",
                                 headers={"Authorization": f"Bearer {cfg['bot_token']}"})
            if not data.get("ok"):
                return {"ok": False, "detail": f"Slack: {data.get('error')}"}
            return {"ok": True, "detail": f"Connecté à l'espace {data.get('team', '')}."}
        except ConnectorError as e:
            return {"ok": False, "detail": str(e)}
