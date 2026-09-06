"""Background pipeline runner with real-time SSE log streaming.

Manages a single asyncio Task that executes the pipeline, captures its
structured log output, and serves it to the web UI via Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class RunState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineRunner:
    """Singleton that manages one pipeline run at a time."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._state: RunState = RunState.IDLE
        self._log_buffer: deque[dict] = deque(maxlen=500)
        self._log_waiters: list[asyncio.Queue] = []
        self._last_result: dict[str, Any] | None = None
        self._started_at: datetime | None = None
        self._completed_at: datetime | None = None

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == RunState.RUNNING

    def status(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "completed_at": self._completed_at.isoformat() if self._completed_at else None,
            "last_result": self._last_result,
            "log_count": len(self._log_buffer),
        }

    def _push_log(self, entry: dict) -> None:
        """Append a log entry and notify all SSE waiters."""
        self._log_buffer.append(entry)
        for q in self._log_waiters:
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(entry)

    def _emit(self, level: str, event: str, **kwargs: Any) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "event": event,
            **kwargs,
        }
        self._push_log(entry)

    async def start(
        self,
        settings: Any,
        session_factory: Any,
        start_from: str | None = None,
        only_stage: str | None = None,
        json_file: Path | None = None,
        live: bool = False,
    ) -> bool:
        """Start a pipeline run in the background.

        Returns True if started, False if already running.
        """
        if self._state == RunState.RUNNING:
            return False

        self._state = RunState.RUNNING
        self._started_at = datetime.now(timezone.utc)
        self._completed_at = None
        self._last_result = None
        self._log_buffer.clear()

        self._emit("info", "pipeline.starting", start_from=start_from, only_stage=only_stage)

        self._task = asyncio.create_task(
            self._run(settings, session_factory, start_from, only_stage, json_file, live)
        )
        return True

    async def _run(
        self,
        settings: Any,
        session_factory: Any,
        start_from: str | None,
        only_stage: str | None,
        json_file: Path | None,
        live: bool,
    ) -> None:
        try:
            from socialgraph.agents.base import Agent
            from socialgraph.agents.classify_agent import ClassifyAgent
            from socialgraph.agents.comment_agent import CommentAgent
            from socialgraph.agents.comment_enrich_agent import CommentEnrichAgent
            from socialgraph.agents.comment_rank_agent import CommentRankAgent
            from socialgraph.agents.embed_agent import EmbedAgent
            from socialgraph.agents.enrich_agent import EnrichAgent
            from socialgraph.agents.graph_build_agent import GraphBuildAgent
            from socialgraph.agents.ingest_agent import IngestAgent
            from socialgraph.agents.insight_agent import InsightAgent
            from socialgraph.agents.semantic_edge_agent import SemanticEdgeAgent
            from socialgraph.agents.subtopic_agent import SubtopicAgent
            from socialgraph.agents.vault_write_agent import VaultWriteAgent
            from socialgraph.knowledge.taxonomy import Taxonomy
            from socialgraph.llm.factory import build_router
            from socialgraph.pipeline.orchestrator import PipelineOrchestrator

            # Build taxonomy if available
            taxonomy = None
            if settings.taxonomy_path.exists():
                taxonomy = Taxonomy.from_file(settings.taxonomy_path)
                self._emit("info", "taxonomy.loaded", path=str(settings.taxonomy_path))
            else:
                self._emit("warning", "taxonomy.missing", path=str(settings.taxonomy_path))

            # Build LLM router
            router = None
            if settings.groq_api_key or settings.vllm_base_url or settings.vllm_batch_url:
                router = build_router(settings)
                self._emit("info", "router.ready")
            else:
                self._emit("warning", "router.skipped", reason="no LLM provider configured")

            # Use default JSON file path if none provided
            if json_file is None:
                json_file = Path("linkedin_saved_posts.json")
                # Also check the workspace dir
                workspace_json = settings.workspace_dir / "linkedin_saved_posts.json"
                if not json_file.exists() and workspace_json.exists():
                    json_file = workspace_json

            agents: dict[str, Agent] = {
                "ingest": IngestAgent(
                    json_path=json_file if (not live and json_file.exists()) else None,
                    live_mode=live,
                ),
                "comments": CommentAgent(max_per_post=settings.max_comments),
                "rank_comments": CommentRankAgent(router=router),
                "comment_enrich": CommentEnrichAgent(router=router),
                "enrich": EnrichAgent(router=router),
                "embed": EmbedAgent(batch_size=settings.batch_size),
                "semantic_edges": SemanticEdgeAgent(),
                "graph_build": GraphBuildAgent(),
                "vault_write": VaultWriteAgent(),
            }
            if router:
                agents["subtopic"] = SubtopicAgent(router=router)
                if router.groq_client is not None:
                    agents["insights"] = InsightAgent(router=router)
                if taxonomy:
                    agents["classify"] = ClassifyAgent(router, taxonomy)

            orchestrator = PipelineOrchestrator(
                agents=agents, settings=settings, session_factory=session_factory
            )

            self._emit("info", "pipeline.run_starting")
            result = await orchestrator.run(start_from=start_from, only_stage=only_stage)

            stage_results = []
            for s in result.stages:
                stage_results.append(
                    {
                        "stage": s.stage,
                        "processed": s.processed,
                        "skipped": s.skipped,
                        "failed": s.failed,
                    }
                )
                self._emit(
                    "info",
                    "pipeline.stage_done",
                    stage=s.stage,
                    processed=s.processed,
                    skipped=s.skipped,
                    failed=s.failed,
                )

            self._last_result = {
                "run_id": result.run_id,
                "status": result.status,
                "stages": stage_results,
            }
            self._state = RunState.COMPLETED
            self._emit(
                "info",
                "pipeline.completed",
                run_id=result.run_id,
                status=result.status,
            )

        except asyncio.CancelledError:
            self._state = RunState.FAILED
            self._emit("warning", "pipeline.cancelled")
        except Exception as exc:
            self._state = RunState.FAILED
            self._emit("error", "pipeline.failed", error=str(exc))
            logger.exception("pipeline_runner.error", error=str(exc))
        finally:
            self._completed_at = datetime.now(timezone.utc)
            # Send a sentinel so SSE clients know the stream ended
            self._push_log({"ts": datetime.now(timezone.utc).isoformat(), "event": "__done__"})

    async def stream_logs(self, from_index: int = 0) -> AsyncIterator[str]:
        """Yield SSE-formatted log events.

        Yields buffered logs first (from *from_index*), then live events until
        the pipeline finishes.
        """
        # Drain buffered entries first
        buffered = list(self._log_buffer)
        for entry in buffered[from_index:]:
            yield f"data: {json.dumps(entry)}\n\n"
            if entry.get("event") == "__done__":
                return

        # If pipeline already done, stop
        if self._state not in (RunState.RUNNING,):
            return

        # Subscribe to live events
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._log_waiters.append(q)
        try:
            while True:
                try:
                    entry = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {json.dumps(entry)}\n\n"
                    if entry.get("event") == "__done__":
                        break
                except asyncio.TimeoutError:
                    # Send a keepalive comment
                    yield ": keepalive\n\n"
        finally:
            with contextlib.suppress(ValueError):
                self._log_waiters.remove(q)

    def get_logs(self, from_index: int = 0) -> list[dict]:
        """Return buffered log entries from *from_index*."""
        return list(self._log_buffer)[from_index:]

    def cancel(self) -> bool:
        """Cancel a running pipeline. Returns True if there was something to cancel."""
        if self._task and not self._task.done():
            self._task.cancel()
            return True
        return False


# Module-level singleton
_runner: PipelineRunner | None = None


def get_runner() -> PipelineRunner:
    global _runner
    if _runner is None:
        _runner = PipelineRunner()
    return _runner
