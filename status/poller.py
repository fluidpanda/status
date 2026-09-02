import asyncio
import logging
from datetime import datetime, timezone

import paramiko

from .config import settings
from .mikrotik_client import RouterOSError, poll_face
from .models import NetworkSnapshot, NodeStatus

logger = logging.getLogger(__name__)

_snapshot: NetworkSnapshot | None = None
_lock = asyncio.Lock()

_EXPECTED_POLL_ERRORS = (OSError, paramiko.SSHException, RouterOSError)


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
            observed_at = datetime.now(timezone.utc)
            previous_nodes = _snapshot.nodes if _snapshot is not None else None
            _apply_recovery_timestamps(previous_nodes, nodes, observed_at)
            _snapshot = NetworkSnapshot(
                nodes=nodes,
                updated_at=observed_at,
                stale=False,
            )
        except _EXPECTED_POLL_ERRORS:
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


def _apply_recovery_timestamps(
        previous: list[NodeStatus] | None, current: list[NodeStatus], observed_at: datetime
) -> None:
    """
    Stamps each currently-available node with the last time it was
    observed transitioning from unavailable to available. A node
    that's stayed up since the previous poll just carries its
    existing timestamp forward, not reset every cycle. A node that's
    down right now gets none - nothing to show while it's red, and
    the badge naturally reappears with a fresh time on its next
    actual recovery.
    """
    previous_by_name = {n.name: n for n in previous} if previous else {}
    for node in current:
        if not node.available:
            continue
        prev = previous_by_name.get(node.name)
        if prev is None:
            node.recovered_at = None
        elif not prev.available:
            node.recovered_at = observed_at
        else:
            node.recovered_at = prev.recovered_at
