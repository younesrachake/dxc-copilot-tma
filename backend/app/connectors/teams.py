"""Microsoft Teams connector — Incoming Webhook (post adaptive MessageCard)."""
from app.connectors.base import ConfigField, Connector, Tool
from app.connectors.http import ConnectorError, request

_THEME = {"Critique": "E34948", "Haute": "EDA100", "Moyenne": "5F259F", "Basse": "8A8886"}


async def _post_message(cfg: dict, args: dict) -> dict:
    title = args.get("title", "DXC Copilot")
    text = args["text"]
    color = _THEME.get(args.get("severity", "Moyenne"), "5F259F")
    card = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": color,
        "summary": title,
        "sections": [{"activityTitle": title, "text": text[:4000]}],
    }
    await request("POST", cfg["webhook_url"], json=card, expect_json=False)
    return {"status": "Publié dans Teams", "title": title}


class TeamsConnector(Connector):
    key = "teams"
    name = "Microsoft Teams"
    icon = "message-circle"
    description = "Publier des cartes d'incident dans un canal Teams via webhook."
    config_fields = [
        ConfigField("webhook_url", "URL du webhook entrant", "url",
                    "https://outlook.office.com/webhook/…"),
    ]
    tools = [
        Tool("post_teams_message", "Publie une carte d'incident dans Teams.", "write",
             {"title": {"type": "string"}, "text": {"type": "string"},
              "severity": {"type": "string", "enum": ["Critique", "Haute", "Moyenne", "Basse"]}},
             ["text"], _post_message,
             summarize=lambda a: f"Publier dans Teams : « {a.get('title') or a.get('text', '')[:70]} »"),
    ]

    def is_configured(self, cfg: dict) -> bool:
        return bool((cfg or {}).get("webhook_url"))

    async def test_connection(self, cfg: dict) -> dict:
        try:
            await _post_message(cfg, {"title": "DXC Copilot — test",
                                      "text": "Connexion Teams vérifiée ✅", "severity": "Basse"})
            return {"ok": True, "detail": "Message de test envoyé dans Teams."}
        except ConnectorError as e:
            return {"ok": False, "detail": str(e)}
