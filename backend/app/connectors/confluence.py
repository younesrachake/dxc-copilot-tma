"""Confluence connector — Cloud REST API (search pages, read page)."""
import base64
import re

from app.connectors.base import ConfigField, Connector, Tool
from app.connectors.http import ConnectorError, request


def _headers(cfg: dict) -> dict:
    token = f"{cfg['email']}:{cfg['api_token']}".encode()
    return {"Authorization": f"Basic {base64.b64encode(token).decode()}", "Accept": "application/json"}


def _base(cfg: dict) -> str:
    return cfg["base_url"].rstrip("/")


def _strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


async def _search(cfg: dict, args: dict) -> dict:
    space = cfg.get("space", "")
    cql = f'text ~ "{args["query"]}"'
    if space:
        cql = f'space = "{space}" AND {cql}'
    data = await request("GET", f"{_base(cfg)}/wiki/rest/api/content/search",
                         headers=_headers(cfg), params={"cql": cql, "limit": 5})
    results = []
    for r in data.get("results", []):
        results.append({
            "id": r.get("id"),
            "title": r.get("title", ""),
            "url": f"{_base(cfg)}/wiki{(r.get('_links') or {}).get('webui', '')}",
        })
    return {"count": len(results), "pages": results}


async def _get_page(cfg: dict, args: dict) -> dict:
    pid = args["page_id"]
    data = await request("GET", f"{_base(cfg)}/wiki/rest/api/content/{pid}?expand=body.storage",
                         headers=_headers(cfg))
    body = ((data.get("body") or {}).get("storage") or {}).get("value", "")
    return {
        "id": pid,
        "title": data.get("title", ""),
        "content": _strip_html(body)[:2000],
        "url": f"{_base(cfg)}/wiki{(data.get('_links') or {}).get('webui', '')}",
    }


class ConfluenceConnector(Connector):
    key = "confluence"
    name = "Confluence"
    icon = "file-text"
    description = "Rechercher et lire des pages de documentation Confluence."
    config_fields = [
        ConfigField("base_url", "URL Confluence", "url", "https://votre-org.atlassian.net"),
        ConfigField("email", "Email", "text", "compte@dxc.com"),
        ConfigField("api_token", "Jeton API", "password"),
        ConfigField("space", "Espace (clé)", "text", "COPILOT", required=False),
    ]
    tools = [
        Tool("search_confluence", "Recherche des pages dans Confluence.", "read",
             {"query": {"type": "string"}}, ["query"], _search),
        Tool("get_confluence_page", "Lit le contenu d'une page Confluence.", "read",
             {"page_id": {"type": "string"}}, ["page_id"], _get_page),
    ]

    async def test_connection(self, cfg: dict) -> dict:
        try:
            await request("GET", f"{_base(cfg)}/wiki/rest/api/space?limit=1", headers=_headers(cfg))
            return {"ok": True, "detail": "Connexion Confluence réussie."}
        except ConnectorError as e:
            return {"ok": False, "detail": str(e)}
