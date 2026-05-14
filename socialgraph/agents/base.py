from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.config.settings import Settings


@dataclass
class StageContext:
    run_id: str
    settings: Settings
    db: AsyncSession
    stage: str
    batch_ids: list[int] | None = None  # None → process all pending


@dataclass
class StageOutput:
    stage: str
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    meta: dict = field(default_factory=dict)


@runtime_checkable
class Agent(Protocol):
    name: str

    async def run(self, ctx: StageContext) -> StageOutput: ...
