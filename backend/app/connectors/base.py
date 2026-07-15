"""
Connector base classes — the contract every integration implements.

A Connector declares:
  - key/name/icon/description         (identity, shown in Settings)
  - config_fields                     (what the admin must provide)
  - is_configured(cfg)                (are required fields present?)
  - test_connection(cfg)              (a live ping, for the "Test" button)
  - tools                             (agent tools this connector exposes)

A Tool declares its schema (name/description/params) plus a `kind`:
  - "read"  → executed inline during the agent loop (safe, no side effects)
  - "write" → NOT executed by the agent; it proposes a confirmation card that
              the user must approve, then runs via POST /api/integrations/execute
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConfigField:
    key: str
    label: str
    type: str = "text"          # text | password | url | number
    placeholder: str = ""
    required: bool = True
    help: str = ""


@dataclass
class Tool:
    name: str
    description: str
    kind: Literal["read", "write"]
    parameters: dict            # JSON-schema properties object
    required: list[str]
    # handler(cfg, args) -> dict. For read tools the dict is fed back to the LLM;
    # for write tools it's the executed result (only called after confirmation).
    handler: Callable[[dict, dict], Awaitable[dict]]
    # Human summary of a proposed write, shown on the confirmation card.
    summarize: Optional[Callable[[dict], str]] = None

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                },
            },
        }


class Connector:
    key: str = ""
    name: str = ""
    icon: str = ""              # lucide icon name for the UI
    description: str = ""
    config_fields: list[ConfigField] = []
    tools: list[Tool] = []

    def is_configured(self, cfg: dict) -> bool:
        return all((cfg or {}).get(f.key) for f in self.config_fields if f.required)

    async def test_connection(self, cfg: dict) -> dict:
        """Return {"ok": bool, "detail": str}. Override with a real ping."""
        return {"ok": self.is_configured(cfg), "detail": "Configuration présente." if self.is_configured(cfg) else "Configuration incomplète."}

    def public_config(self, cfg: dict) -> dict:
        """Config for the UI — secrets masked."""
        out = {}
        for f in self.config_fields:
            val = (cfg or {}).get(f.key, "")
            if f.type == "password" and val:
                out[f.key] = "••••••••"
            else:
                out[f.key] = val
        return out
