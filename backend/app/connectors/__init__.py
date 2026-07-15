"""
Integration connectors — real external systems (Jira, ServiceNow, Slack,
Confluence, GitHub, Teams, PagerDuty) exposed to the AI agent as tools.

Config lives in platform_settings section "integrations", one nested object per
connector key. A connector is only usable when configured; unconfigured
connectors return a clear error rather than a mock.
"""
from app.connectors.registry import registry  # noqa: F401
