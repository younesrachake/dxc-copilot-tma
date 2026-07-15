"""
Connector registry — the single entry point the rest of the app talks to.

Config source of truth: platform_settings section "integrations", shaped as
  { "<connector_key>": { "enabled": bool, ...config fields... }, ... }
"""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import Connector, Tool
from app.connectors.confluence import ConfluenceConnector
from app.connectors.github import GitHubConnector
from app.connectors.jira import JiraConnector
from app.connectors.pagerduty import PagerDutyConnector
from app.connectors.servicenow import ServiceNowConnector
from app.connectors.slack import SlackConnector
from app.connectors.teams import TeamsConnector

logger = logging.getLogger(__name__)


class Registry:
    def __init__(self):
        self._connectors: dict[str, Connector] = {}
        for cls in (JiraConnector, ServiceNowConnector, SlackConnector,
                    ConfluenceConnector, GitHubConnector, TeamsConnector, PagerDutyConnector):
            c = cls()
            self._connectors[c.key] = c

    def all(self) -> list[Connector]:
        return list(self._connectors.values())

    def get(self, key: str) -> Optional[Connector]:
        return self._connectors.get(key)

    async def _settings(self, db: AsyncSession) -> dict:
        from app.services.agent_service import _get_setting
        row = await _get_setting(db, "integrations")
        return (row.data or {}) if row else {}

    def _cfg(self, all_settings: dict, key: str) -> dict:
        return dict(all_settings.get(key) or {})

    async def status(self, db: AsyncSession) -> list[dict]:
        """Per-connector status for the Settings UI."""
        settings = await self._settings(db)
        out = []
        for c in self.all():
            cfg = self._cfg(settings, c.key)
            out.append({
                "key": c.key,
                "name": c.name,
                "icon": c.icon,
                "description": c.description,
                "enabled": bool(cfg.get("enabled")),
                "configured": c.is_configured(cfg),
                "config_fields": [f.__dict__ for f in c.config_fields],
                "config": c.public_config(cfg),
                "tools": [{"name": t.name, "kind": t.kind, "description": t.description} for t in c.tools],
            })
        return out

    async def enabled_connectors(self, db: AsyncSession) -> list[tuple[Connector, dict]]:
        settings = await self._settings(db)
        active = []
        for c in self.all():
            cfg = self._cfg(settings, c.key)
            if cfg.get("enabled") and c.is_configured(cfg):
                active.append((c, cfg))
        return active

    async def agent_tools(self, db: AsyncSession) -> tuple[list[dict], dict]:
        """Returns (openai_tool_schemas, index) for enabled connectors.
        index maps tool_name -> (connector, tool, cfg) for execution/lookup."""
        schemas: list[dict] = []
        index: dict = {}
        for connector, cfg in await self.enabled_connectors(db):
            for tool in connector.tools:
                schemas.append(tool.openai_schema())
                index[tool.name] = (connector, tool, cfg)
        return schemas, index

    async def find_tool(self, db: AsyncSession, tool_name: str) -> Optional[tuple[Connector, Tool, dict]]:
        _, index = await self.agent_tools(db)
        return index.get(tool_name)

    async def test(self, db: AsyncSession, key: str) -> dict:
        c = self.get(key)
        if not c:
            return {"ok": False, "detail": "Connecteur inconnu."}
        settings = await self._settings(db)
        cfg = self._cfg(settings, key)
        if not c.is_configured(cfg):
            return {"ok": False, "detail": "Configuration incomplète — renseignez les champs requis."}
        try:
            return await c.test_connection(cfg)
        except Exception as e:
            logger.warning("Connector %s test failed: %s", key, e)
            return {"ok": False, "detail": f"Échec du test : {e}"}

    async def save_config(self, db: AsyncSession, key: str, data: dict) -> dict:
        """Merge config for one connector (secrets left unchanged when masked)."""
        from app.services.agent_service import _merge_setting
        c = self.get(key)
        if not c:
            raise ValueError("Connecteur inconnu")
        settings = await self._settings(db)
        current = self._cfg(settings, key)
        incoming = {"enabled": bool(data.get("enabled", current.get("enabled", False)))}
        for f in c.config_fields:
            val = data.get(f.key)
            if val is None:
                incoming[f.key] = current.get(f.key, "")
            elif f.type == "password" and set(val) <= {"•"}:
                incoming[f.key] = current.get(f.key, "")  # masked placeholder → keep existing
            else:
                incoming[f.key] = val
        await _merge_setting(db, "integrations", {key: incoming})
        await db.commit()
        return {"key": key, "enabled": incoming["enabled"], "configured": c.is_configured(incoming)}

    async def execute(self, db: AsyncSession, tool_name: str, args: dict) -> dict:
        """Run a tool by name (used by the confirmed-write endpoint and read tools)."""
        found = await self.find_tool(db, tool_name)
        if not found:
            from app.connectors.http import ConnectorError
            raise ConnectorError("Intégration non activée ou non configurée.")
        connector, tool, cfg = found
        return await tool.handler(cfg, args)


registry = Registry()
