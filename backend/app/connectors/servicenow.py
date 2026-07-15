"""ServiceNow connector — Table API (create incident, get incident)."""
import base64

from app.connectors.base import ConfigField, Connector, Tool
from app.connectors.http import ConnectorError, request

# ServiceNow urgency/impact 1=High 2=Medium 3=Low
_URGENCY = {"Critique": "1", "Haute": "1", "Moyenne": "2", "Basse": "3"}


def _auth_headers(cfg: dict) -> dict:
    token = f"{cfg['username']}:{cfg['password']}".encode()
    return {
        "Authorization": f"Basic {base64.b64encode(token).decode()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _base(cfg: dict) -> str:
    inst = cfg["instance"].rstrip("/")
    if not inst.startswith("http"):
        inst = f"https://{inst}"
    return inst


async def _create_incident(cfg: dict, args: dict) -> dict:
    urgency = _URGENCY.get(args.get("priority", "Moyenne"), "2")
    payload = {
        "short_description": args["summary"][:160],
        "description": args.get("description", args["summary"])[:4000],
        "urgency": urgency,
        "impact": urgency,
        "category": args.get("category", "software"),
    }
    data = await request("POST", f"{_base(cfg)}/api/now/table/incident",
                         headers=_auth_headers(cfg), json=payload)
    rec = data.get("result", {})
    number = rec.get("number", "")
    return {
        "number": number,
        "sys_id": rec.get("sys_id", ""),
        "url": f"{_base(cfg)}/nav_to.do?uri=incident.do?sys_id={rec.get('sys_id', '')}",
        "status": "Nouveau",
    }


async def _get_incident(cfg: dict, args: dict) -> dict:
    number = args["number"]
    data = await request(
        "GET",
        f"{_base(cfg)}/api/now/table/incident?sysparm_query=number={number}&sysparm_limit=1",
        headers=_auth_headers(cfg),
    )
    results = data.get("result", [])
    if not results:
        return {"number": number, "status": "Introuvable"}
    rec = results[0]
    state_map = {"1": "Nouveau", "2": "En cours", "3": "En attente", "6": "Résolu", "7": "Fermé"}
    return {
        "number": number,
        "status": state_map.get(str(rec.get("state")), rec.get("state", "?")),
        "short_description": rec.get("short_description", ""),
        "url": f"{_base(cfg)}/nav_to.do?uri=incident.do?sys_id={rec.get('sys_id', '')}",
    }


class ServiceNowConnector(Connector):
    key = "servicenow"
    name = "ServiceNow"
    icon = "server"
    description = "Créer et suivre des incidents ITSM dans ServiceNow."
    config_fields = [
        ConfigField("instance", "Instance", "text", "dxc.service-now.com"),
        ConfigField("username", "Utilisateur", "text", "integration.user"),
        ConfigField("password", "Mot de passe", "password"),
    ]
    tools = [
        Tool("create_servicenow_incident", "Crée un incident ITSM dans ServiceNow.", "write",
             {"summary": {"type": "string"}, "description": {"type": "string"},
              "priority": {"type": "string", "enum": ["Critique", "Haute", "Moyenne", "Basse"]}},
             ["summary"], _create_incident,
             summarize=lambda a: f"Créer un incident ServiceNow : « {a.get('summary', '')[:80]} »"),
        Tool("get_servicenow_incident", "Récupère le statut d'un incident ServiceNow.", "read",
             {"number": {"type": "string", "description": "Numéro, ex: INC0012345"}},
             ["number"], _get_incident),
    ]

    async def test_connection(self, cfg: dict) -> dict:
        try:
            await request("GET", f"{_base(cfg)}/api/now/table/incident?sysparm_limit=1",
                          headers=_auth_headers(cfg))
            return {"ok": True, "detail": f"Connecté à {cfg.get('instance')}."}
        except ConnectorError as e:
            return {"ok": False, "detail": str(e)}
