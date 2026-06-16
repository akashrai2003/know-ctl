from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.config.settings import Settings
from socialgraph.storage.models import Post


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


def primary_topic(post: Post) -> str | None:
    """Return the name of the topic with the highest confidence_score for this post.

    Ties are broken alphabetically by topic name.
    """
    if not post.post_topics:
        return None
    # Sort descending by confidence_score and ascending by topic name
    sorted_pts = sorted(post.post_topics, key=lambda pt: (-pt.confidence_score, pt.topic.name))
    return sorted_pts[0].topic.name
