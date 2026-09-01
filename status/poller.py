import asyncio
import logging
from datetime import datetime, timezone

from .config import settings
from .mikrotik_client import poll_face
from .models import NetworkSnapshot

logger = logging.getLogger(__name__)

_snapshot: NetworkSnapshot | None = None
_lock = asyncio.Lock()


def get_snapshot() -> NetworkSnapshot | None:
    """
    Read-only access for request handlers - never touches SSH.
    None only until the very first poll completes after startup.
    """
    return _snapshot


async def refresh() -> NetworkSnapshot:
    """
    Actually polls face (via the shared lock) and updates the
    in-memory snapshot. On failure, keeps the last good snapshot but
    marks it stale rather than wiping it out.
    """
    global _snapshot
    async with _lock:
        try:
            nodes = await asyncio.to_thread(poll_face)
            _snapshot = NetworkSnapshot(
                nodes=nodes,
                updated_at=datetime.now(timezone.utc),
                stale=False,
            )
        except Exception:
            logger.exception("Failed to poll face")
            if _snapshot is not None:
                _snapshot = _snapshot.model_copy(update={"stale": True})
            else:
                _snapshot = NetworkSnapshot(
                    nodes=[], updated_at=datetime.now(timezone.utc), stale=True
                )
        return _snapshot


async def background_loop() -> None:
    while True:
        await refresh()
        await asyncio.sleep(settings.poll_interval_seconds)
