"""PagerDuty connector — Events API v2 (trigger) + REST (on-calls)."""
from app.connectors.base import ConfigField, Connector, Tool
from app.connectors.http import ConnectorError, request

EVENTS_API = "https://events.pagerduty.com/v2/enqueue"
REST_API = "https://api.pagerduty.com"

_SEVERITY = {"Critique": "critical", "Haute": "error", "Moyenne": "warning", "Basse": "info"}


async def _trigger(cfg: dict, args: dict) -> dict:
    payload = {
        "routing_key": cfg["routing_key"],
        "event_action": "trigger",
        "payload": {
            "summary": args["summary"][:1024],
            "source": args.get("source", "DXC Copilot"),
            "severity": _SEVERITY.get(args.get("priority", "Haute"), "error"),
        },
    }
    data = await request("POST", EVENTS_API, json=payload)
    if data.get("status") != "success":
        raise ConnectorError(f"PagerDuty: {data.get('message', 'échec du déclenchement')}")
    return {"dedup_key": data.get("dedup_key", ""), "status": "Alerte déclenchée"}


async def _oncalls(cfg: dict, args: dict) -> dict:
    if not cfg.get("api_token"):
        raise ConnectorError("Jeton API REST requis pour lister les astreintes.")
    data = await request("GET", f"{REST_API}/oncalls",
                         headers={"Authorization": f"Token token={cfg['api_token']}",
                                  "Accept": "application/vnd.pagerduty+json;version=2"},
                         params={"limit": 5})
    oncalls = []
    for oc in data.get("oncalls", []):
        oncalls.append({
            "user": (oc.get("user") or {}).get("summary", ""),
            "escalation_level": oc.get("escalation_level"),
            "schedule": (oc.get("schedule") or {}).get("summary", ""),
        })
    return {"count": len(oncalls), "oncalls": oncalls}


class PagerDutyConnector(Connector):
    key = "pagerduty"
    name = "PagerDuty"
    icon = "zap"
    description = "Déclencher des alertes on-call et consulter les astreintes."
    config_fields = [
        ConfigField("routing_key", "Clé de routage (Events API)", "password"),
        ConfigField("api_token", "Jeton API REST", "password", required=False,
                    help="Optionnel — nécessaire pour lister les astreintes."),
    ]
    tools = [
        Tool("trigger_pagerduty_incident", "Déclenche une alerte PagerDuty pour l'équipe on-call.", "write",
             {"summary": {"type": "string"},
              "priority": {"type": "string", "enum": ["Critique", "Haute", "Moyenne", "Basse"]}},
             ["summary"], _trigger,
             summarize=lambda a: f"Déclencher une alerte PagerDuty ({a.get('priority', 'Haute')}) : « {a.get('summary', '')[:70]} »"),
        Tool("list_pagerduty_oncalls", "Liste les personnes actuellement d'astreinte.", "read",
             {}, [], _oncalls),
    ]

    def is_configured(self, cfg: dict) -> bool:
        return bool((cfg or {}).get("routing_key"))

    async def test_connection(self, cfg: dict) -> dict:
        if cfg.get("api_token"):
            try:
                await request("GET", f"{REST_API}/abilities",
                              headers={"Authorization": f"Token token={cfg['api_token']}",
                                       "Accept": "application/vnd.pagerduty+json;version=2"})
                return {"ok": True, "detail": "Jeton API REST valide."}
            except ConnectorError as e:
                return {"ok": False, "detail": str(e)}
        # Only a routing key — can't ping without sending an event
        return {"ok": bool(cfg.get("routing_key")),
                "detail": "Clé de routage présente (test réel via déclenchement d'alerte)."}
