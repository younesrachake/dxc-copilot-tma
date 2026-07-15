"""Shared async HTTP helper for connectors — one place for timeouts + errors."""
import logging

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0


class ConnectorError(Exception):
    """Raised when an external call fails; message is user-safe (French)."""


async def request(method: str, url: str, *, expect_json: bool = True, **kwargs) -> dict:
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, url, **kwargs)
    except httpx.TimeoutException:
        raise ConnectorError("Délai dépassé en contactant le service externe.")
    except httpx.HTTPError as e:
        raise ConnectorError(f"Erreur réseau: {type(e).__name__}")
    if resp.status_code >= 400:
        detail = ""
        try:
            body = resp.json()
            detail = str(body.get("error") or body.get("message") or body)[:200]
        except Exception:
            detail = resp.text[:200]
        raise ConnectorError(f"Erreur {resp.status_code}: {detail}")
    if not expect_json:
        return {"status": resp.status_code, "text": resp.text}
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "text": resp.text}
