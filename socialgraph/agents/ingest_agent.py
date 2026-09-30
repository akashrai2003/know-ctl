"""Ingest agent: unified dispatcher routing ingestion to platform-specific agents."""

from __future__ import annotations

from pathlib import Path

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.agents.linkedin_ingest_agent import LinkedInIngestAgent
from socialgraph.agents.reddit_ingest_agent import RedditIngestAgent


class IngestAgent:
    """Unified ingest agent routing to platform-specific ingest implementations."""

    name = "ingest"

    def __init__(
        self,
        json_path: Path | None = None,
        live_mode: bool = False,
        platform: str = "linkedin",
    ) -> None:
        self._json_path = json_path
        self._live_mode = live_mode
        self._platform = platform

    async def run(self, ctx: StageContext) -> StageOutput:
        if self._platform == "reddit":
            agent = RedditIngestAgent()
            return await agent.run(ctx)
        agent = LinkedInIngestAgent(
            json_path=self._json_path,
            live_mode=self._live_mode,
        )
        return await agent.run(ctx)
