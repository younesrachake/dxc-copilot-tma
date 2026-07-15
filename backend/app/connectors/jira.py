"""Jira Cloud connector — REST API v3 (create issue, status, search, comment)."""
import base64

from app.connectors.base import ConfigField, Connector, Tool
from app.connectors.http import ConnectorError, request

_PRIORITY_MAP = {
    "Critique": "Highest", "Haute": "High", "Moyenne": "Medium", "Basse": "Low",
}


def _auth_headers(cfg: dict) -> dict:
    token = f"{cfg['email']}:{cfg['api_token']}".encode()
    return {
        "Authorization": f"Basic {base64.b64encode(token).decode()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _base(cfg: dict) -> str:
    return cfg["base_url"].rstrip("/")


async def _create_issue(cfg: dict, args: dict) -> dict:
    summary = args["summary"]
    description = args.get("description", "")
    priority = _PRIORITY_MAP.get(args.get("priority", "Moyenne"), "Medium")
    project = args.get("project") or cfg.get("project", "")
    payload = {
        "fields": {
            "project": {"key": project},
            "summary": summary[:255],
            "issuetype": {"name": args.get("issue_type", "Task")},
            "priority": {"name": priority},
            "description": {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph",
                             "content": [{"type": "text", "text": description[:5000] or summary}]}],
            },
        }
    }
    data = await request("POST", f"{_base(cfg)}/rest/api/3/issue",
                         headers=_auth_headers(cfg), json=payload)
    key = data.get("key", "")
    return {"key": key, "url": f"{_base(cfg)}/browse/{key}", "status": "Créé"}


async def _issue_status(cfg: dict, args: dict) -> dict:
    key = args["issue_key"]
    data = await request("GET", f"{_base(cfg)}/rest/api/3/issue/{key}?fields=status,summary",
                         headers=_auth_headers(cfg))
    fields = data.get("fields", {})
    return {
        "key": key,
        "status": (fields.get("status") or {}).get("name", "Inconnu"),
        "summary": fields.get("summary", ""),
        "url": f"{_base(cfg)}/browse/{key}",
    }


async def _search(cfg: dict, args: dict) -> dict:
    jql = args.get("jql") or f'text ~ "{args.get("query", "")}" ORDER BY updated DESC'
    data = await request("POST", f"{_base(cfg)}/rest/api/3/search",
                         headers=_auth_headers(cfg),
                         json={"jql": jql, "maxResults": 5, "fields": ["summary", "status", "priority"]})
    issues = []
    for it in data.get("issues", []):
        f = it.get("fields", {})
        issues.append({
            "key": it.get("key"),
            "summary": f.get("summary", ""),
            "status": (f.get("status") or {}).get("name", ""),
            "url": f"{_base(cfg)}/browse/{it.get('key')}",
        })
    return {"count": len(issues), "issues": issues}


async def _add_comment(cfg: dict, args: dict) -> dict:
    key = args["issue_key"]
    body = {"body": {"type": "doc", "version": 1,
                     "content": [{"type": "paragraph",
                                  "content": [{"type": "text", "text": args["comment"][:5000]}]}]}}
    await request("POST", f"{_base(cfg)}/rest/api/3/issue/{key}/comment",
                  headers=_auth_headers(cfg), json=body)
    return {"key": key, "url": f"{_base(cfg)}/browse/{key}", "status": "Commentaire ajouté"}


class JiraConnector(Connector):
    key = "jira"
    name = "Jira"
    icon = "ticket"
    description = "Créer et suivre des tickets d'incident dans Jira Cloud."
    config_fields = [
        ConfigField("base_url", "URL Jira", "url", "https://votre-org.atlassian.net"),
        ConfigField("email", "Email", "text", "compte@dxc.com"),
        ConfigField("api_token", "Jeton API", "password", help="Créé depuis id.atlassian.com → sécurité → jetons API"),
        ConfigField("project", "Clé de projet", "text", "TMA"),
    ]
    tools = [
        Tool("create_jira_issue", "Crée un ticket d'incident dans Jira.", "write",
             {"summary": {"type": "string", "description": "Résumé court du ticket"},
              "description": {"type": "string", "description": "Description détaillée"},
              "priority": {"type": "string", "enum": ["Critique", "Haute", "Moyenne", "Basse"]},
              "issue_type": {"type": "string", "description": "Type (Bug, Task, Incident…)"}},
             ["summary"], _create_issue,
             summarize=lambda a: f"Créer un ticket Jira : « {a.get('summary', '')[:80]} » (priorité {a.get('priority', 'Moyenne')})"),
        Tool("get_jira_issue_status", "Récupère le statut d'un ticket Jira existant.", "read",
             {"issue_key": {"type": "string", "description": "Clé du ticket, ex: TMA-123"}},
             ["issue_key"], _issue_status),
        Tool("search_jira", "Recherche des tickets Jira par mots-clés.", "read",
             {"query": {"type": "string", "description": "Mots-clés à rechercher"}},
             ["query"], _search),
        Tool("add_jira_comment", "Ajoute un commentaire à un ticket Jira.", "write",
             {"issue_key": {"type": "string"}, "comment": {"type": "string"}},
             ["issue_key", "comment"], _add_comment,
             summarize=lambda a: f"Ajouter un commentaire au ticket {a.get('issue_key', '')}"),
    ]

    async def test_connection(self, cfg: dict) -> dict:
        try:
            data = await request("GET", f"{_base(cfg)}/rest/api/3/myself", headers=_auth_headers(cfg))
            return {"ok": True, "detail": f"Connecté en tant que {data.get('displayName', cfg.get('email'))}."}
        except ConnectorError as e:
            return {"ok": False, "detail": str(e)}
