"""
In-process event hub — realtime fan-out to admin SSE subscribers.

Single-process pub/sub: chat activity publishes events, the admin dashboard
subscribes via GET /api/admin/events. With multiple backend replicas each
replica only sees its own events (documented limitation — move to Redis
pub/sub if the backend ever scales out).
"""
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_subscribers: set[asyncio.Queue] = set()
_MAX_QUEUE = 100


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def publish(event: dict) -> None:
    """Fire-and-forget broadcast. Slow/full subscribers are skipped."""
    event = {**event, "at": datetime.now(timezone.utc).isoformat()}
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # Subscriber is not draining — drop the event for it
            pass
