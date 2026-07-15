"""GitHub connector — REST API (search issues, create issue)."""
from app.connectors.base import ConfigField, Connector, Tool
from app.connectors.http import ConnectorError, request

API = "https://api.github.com"


def _headers(cfg: dict) -> dict:
    return {
        "Authorization": f"Bearer {cfg['token']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _search_issues(cfg: dict, args: dict) -> dict:
    org = cfg.get("org", "")
    scope = f"org:{org} " if org else ""
    q = f"{scope}{args['query']} in:title,body type:issue"
    data = await request("GET", f"{API}/search/issues", headers=_headers(cfg),
                         params={"q": q, "per_page": 5})
    items = []
    for it in data.get("items", []):
        items.append({
            "number": it.get("number"),
            "title": it.get("title", ""),
            "state": it.get("state", ""),
            "repo": (it.get("repository_url", "").split("/repos/")[-1]),
            "url": it.get("html_url", ""),
        })
    return {"count": len(items), "issues": items}


async def _create_issue(cfg: dict, args: dict) -> dict:
    repo = args.get("repo") or cfg.get("default_repo", "")
    if "/" not in repo:
        repo = f"{cfg.get('org', '')}/{repo}"
    data = await request("POST", f"{API}/repos/{repo}/issues", headers=_headers(cfg),
                         json={"title": args["title"][:256], "body": args.get("body", "")[:5000]})
    return {"number": data.get("number"), "url": data.get("html_url", ""), "status": "Créé"}


class GitHubConnector(Connector):
    key = "github"
    name = "GitHub"
    icon = "code"
    description = "Rechercher et créer des issues GitHub liées aux incidents."
    config_fields = [
        ConfigField("token", "Jeton d'accès (PAT)", "password"),
        ConfigField("org", "Organisation", "text", "DXCTechnology", required=False),
        ConfigField("default_repo", "Dépôt par défaut", "text", "owner/repo", required=False),
    ]
    tools = [
        Tool("search_github_issues", "Recherche des issues GitHub.", "read",
             {"query": {"type": "string"}}, ["query"], _search_issues),
        Tool("create_github_issue", "Crée une issue GitHub.", "write",
             {"title": {"type": "string"}, "body": {"type": "string"},
              "repo": {"type": "string", "description": "owner/repo (optionnel si défaut configuré)"}},
             ["title"], _create_issue,
             summarize=lambda a: f"Créer une issue GitHub : « {a.get('title', '')[:80]} »"),
    ]

    def is_configured(self, cfg: dict) -> bool:
        return bool((cfg or {}).get("token"))

    async def test_connection(self, cfg: dict) -> dict:
        try:
            data = await request("GET", f"{API}/user", headers=_headers(cfg))
            return {"ok": True, "detail": f"Connecté en tant que {data.get('login', '')}."}
        except ConnectorError as e:
            return {"ok": False, "detail": str(e)}
