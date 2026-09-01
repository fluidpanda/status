from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class NodeStatus(BaseModel):
    name: str
    available: bool
    avg_rtt_ms: float | int | None = None
    role: Literal["primary", "secondary"] | None = None
    active: bool | None = None


class NetworkSnapshot(BaseModel):
    nodes: list[NodeStatus]
    updated_at: datetime
    stale: bool = False
