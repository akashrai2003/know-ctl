"""FastAPI application for Social Graph web dashboard."""

from __future__ import annotations

import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.config.settings import Settings
from socialgraph.web import service
from socialgraph.web.deps import get_db, get_settings, init_globals
from socialgraph.web.pipeline_runner import get_runner
from socialgraph.web.schemas import (
    ConnectionTestResult,
    IsConfiguredOut,
    PipelineRunRequest,
    PipelineStatusOut,
    SettingsIn,
    SettingsOut,
)

logger = structlog.get_logger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Factory: create and configure the FastAPI app."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        s = settings or Settings()
        init_globals(s)
        logger.info("web.startup", port=s.web_port)
        yield
        logger.info("web.shutdown")

    app = FastAPI(
        title="Social Graph",
        description="LinkedIn knowledge graph dashboard",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Dashboard API ──────────────────────────────────────────────────────

    @app.get("/api/stats")
    async def api_stats(db: AsyncSession = Depends(get_db)):
        return await service.get_stats(db)

    @app.get("/api/topics")
    async def api_topics(db: AsyncSession = Depends(get_db)):
        return await service.list_topics(db)

    @app.get("/api/topics/{slug}")
    async def api_topic_detail(slug: str, db: AsyncSession = Depends(get_db)):
        detail = await service.get_topic_detail(db, slug)
        if not detail:
            return {"error": f"Topic '{slug}' not found"}
        return detail

    @app.get("/api/posts")
    async def api_posts(
        topic: str | None = Query(None),
        author: str | None = Query(None),
        q: str | None = Query(None),
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
        db: AsyncSession = Depends(get_db),
    ):
        return await service.list_posts(
            db, topic=topic, author=author, q=q, limit=limit, offset=offset
        )

    @app.get("/api/posts/{urn:path}")
    async def api_post_detail(
        urn: str,
        db: AsyncSession = Depends(get_db),
    ):
        detail = await service.get_post_detail(db, urn)
        if not detail:
            return {"error": f"Post '{urn}' not found"}
        return detail

    @app.get("/api/authors")
    async def api_authors(
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        db: AsyncSession = Depends(get_db),
    ):
        return await service.list_authors(db, limit=limit, offset=offset)

    @app.get("/api/authors/{slug}")
    async def api_author_detail(slug: str, db: AsyncSession = Depends(get_db)):
        detail = await service.get_author_detail(db, slug)
        if not detail:
            return {"error": f"Author '{slug}' not found"}
        return detail

    @app.get("/api/search")
    async def api_search(
        q: str = Query(..., min_length=1),
        topic: str | None = Query(None),
        limit: int = Query(20, ge=1, le=100),
        db: AsyncSession = Depends(get_db),
        settings: Settings = Depends(get_settings),
    ):
        return await service.semantic_search(db, q, settings, topic=topic, limit=limit)

    @app.get("/api/graph")
    async def api_graph(db: AsyncSession = Depends(get_db)):
        return await service.get_graph_data(db)

    # ── Settings API ───────────────────────────────────────────────────────

    @app.get("/api/settings/is-configured", response_model=IsConfiguredOut)
    async def api_is_configured(db: AsyncSession = Depends(get_db)):
        """Check if the app has been configured (for onboarding wizard)."""
        from socialgraph.storage.config_store import ConfigStore

        store = ConfigStore(db)
        groq_key = await store.get("groq_api_key", "")
        vllm_url = await store.get("vllm_base_url", "")
        linkedin = await store.get("linkedin_email", "") or await store.get("linkedin_cookie", "")
        configured = bool(groq_key and groq_key.strip())
        return IsConfiguredOut(
            configured=configured,
            has_groq=bool(groq_key),
            has_vllm=bool(vllm_url),
            has_linkedin=bool(linkedin),
        )

    @app.get("/api/settings", response_model=SettingsOut)
    async def api_get_settings(db: AsyncSession = Depends(get_db)):
        """Return all settings (secret values masked with ***)."""
        from socialgraph.storage.config_store import ConfigStore

        store = ConfigStore(db)
        raw = await store.get_all()
        # Fill in any keys missing from DB with Settings defaults
        defaults = get_settings()
        return SettingsOut(
            groq_api_key=raw.get("groq_api_key", ""),
            groq_model=raw.get("groq_model", defaults.groq_model),
            vllm_base_url=raw.get("vllm_base_url", defaults.vllm_base_url),
            vllm_model=raw.get("vllm_model", defaults.vllm_model),
            vllm_api_key=raw.get("vllm_api_key", ""),
            embedding_model=raw.get("embedding_model", defaults.embedding_model),
            embedding_device=raw.get("embedding_device", defaults.embedding_device),
            linkedin_email=raw.get("linkedin_email", ""),
            linkedin_password=raw.get("linkedin_password", ""),
            linkedin_cookie=raw.get("linkedin_cookie", ""),
            batch_size=raw.get("batch_size", str(defaults.batch_size)),
            llm_timeout=raw.get("llm_timeout", str(defaults.llm_timeout)),
            max_comments=raw.get("max_comments", str(defaults.max_comments)),
            schedule_interval_hours=raw.get(
                "schedule_interval_hours", str(defaults.schedule_interval_hours)
            ),
            db_path=raw.get("db_path", str(defaults.db_path)),
            workspace_dir=raw.get("workspace_dir", str(defaults.workspace_dir)),
            obsidian_vault_path=raw.get("obsidian_vault_path", str(defaults.obsidian_vault_path)),
            log_level=raw.get("log_level", defaults.log_level),
            web_port=raw.get("web_port", str(defaults.web_port)),
        )

    @app.put("/api/settings")
    async def api_update_settings(payload: SettingsIn, db: AsyncSession = Depends(get_db)):
        """Bulk-update settings. Only non-None fields are written."""
        from socialgraph.storage.config_store import ConfigStore

        store = ConfigStore(db)
        updates = payload.model_dump(exclude_none=True)
        for k, v in updates.items():
            if v is not None:
                await store.set(k, str(v))
        await db.commit()
        return {"ok": True, "updated": list(updates.keys())}

    @app.post("/api/settings/test-groq", response_model=ConnectionTestResult)
    async def api_test_groq(db: AsyncSession = Depends(get_db)):
        """Test Groq API connectivity using the stored key."""
        from socialgraph.storage.config_store import ConfigStore

        store = ConfigStore(db)
        key = await store.get("groq_api_key", "")
        if not key:
            return ConnectionTestResult(ok=False, message="No Groq API key configured")

        try:
            import httpx

            t0 = time.monotonic()
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
            latency = (time.monotonic() - t0) * 1000
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                return ConnectionTestResult(
                    ok=True,
                    message=f"Connected ✓ — {len(models)} models available",
                    latency_ms=round(latency, 1),
                )
            else:
                return ConnectionTestResult(
                    ok=False,
                    message=f"API returned HTTP {resp.status_code}: {resp.text[:200]}",
                    latency_ms=round(latency, 1),
                )
        except Exception as exc:
            return ConnectionTestResult(ok=False, message=f"Connection failed: {exc}")

    @app.post("/api/settings/test-vllm", response_model=ConnectionTestResult)
    async def api_test_vllm(db: AsyncSession = Depends(get_db)):
        """Test vLLM / local model server connectivity and check for batch endpoint."""
        from socialgraph.storage.config_store import ConfigStore

        store = ConfigStore(db)
        base_url = (await store.get("vllm_base_url", "")).rstrip("/")
        if not base_url:
            return ConnectionTestResult(ok=False, message="No vLLM base URL configured")

        try:
            import httpx

            t0 = time.monotonic()
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try health endpoint
                for path in ["/health", "/v1/models"]:
                    try:
                        resp = await client.get(f"{base_url}{path}")
                        if resp.status_code in (200, 404):
                            break
                    except Exception:
                        continue

                latency = (time.monotonic() - t0) * 1000

                # Check if batch endpoint exists
                has_batch = False
                try:
                    batch_resp = await client.get(f"{base_url}/v1/chat/completions/batch")
                    has_batch = batch_resp.status_code != 404
                except Exception:
                    pass

            mode = "batch + async" if has_batch else "async-only (no /batch endpoint, will use concurrent calls)"
            return ConnectionTestResult(
                ok=True,
                message=f"Connected ✓ — mode: {mode}",
                latency_ms=round(latency, 1),
            )
        except Exception as exc:
            return ConnectionTestResult(ok=False, message=f"Connection failed: {exc}")

    # ── File Upload ────────────────────────────────────────────────────────

    @app.post("/api/upload/linkedin-json")
    async def api_upload_linkedin_json(
        file: UploadFile = File(...),
        settings: Settings = Depends(get_settings),
    ):
        """Upload a LinkedIn saved posts JSON export file."""
        if not file.filename or not file.filename.endswith(".json"):
            return {"ok": False, "error": "Please upload a .json file"}

        dest = settings.workspace_dir / "linkedin_saved_posts.json"
        settings.workspace_dir.mkdir(parents=True, exist_ok=True)

        try:
            with dest.open("wb") as f:
                shutil.copyfileobj(file.file, f)
            size_kb = dest.stat().st_size // 1024
            return {"ok": True, "path": str(dest), "size_kb": size_kb}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ── Pipeline API ───────────────────────────────────────────────────────

    @app.get("/api/pipeline/status", response_model=PipelineStatusOut)
    async def api_pipeline_status():
        """Return current pipeline run state."""
        runner = get_runner()
        return PipelineStatusOut(**runner.status())

    @app.post("/api/pipeline/run")
    async def api_pipeline_run(
        payload: PipelineRunRequest,
        _db: AsyncSession = Depends(get_db),
        settings: Settings = Depends(get_settings),
    ):
        """Start a pipeline run in the background (merges DB settings first)."""
        runner = get_runner()
        if runner.is_running:
            return {"ok": False, "error": "Pipeline is already running"}

        # Merge DB settings into a fresh Settings instance for this run
        merged_settings = await Settings.from_db(settings.db_path)
        merged_settings.ensure_workspace()

        # Determine JSON file path
        json_file = None
        if payload.json_filename:
            json_file = merged_settings.workspace_dir / payload.json_filename
        else:
            workspace_json = merged_settings.workspace_dir / "linkedin_saved_posts.json"
            local_json = Path("linkedin_saved_posts.json")
            if workspace_json.exists():
                json_file = workspace_json
            elif local_json.exists():
                json_file = local_json

        # Build session factory
        from socialgraph.storage.db import build_session_factory

        session_factory = build_session_factory(merged_settings.db_path)

        started = await runner.start(
            settings=merged_settings,
            session_factory=session_factory,
            start_from=payload.start_from,
            only_stage=payload.only_stage,
            json_file=json_file,
            live=payload.live,
        )

        if started:
            return {"ok": True, "message": "Pipeline started"}
        else:
            return {"ok": False, "error": "Pipeline is already running"}

    @app.post("/api/pipeline/cancel")
    async def api_pipeline_cancel():
        """Cancel a running pipeline."""
        runner = get_runner()
        cancelled = runner.cancel()
        return {"ok": True, "cancelled": cancelled}

    @app.get("/api/pipeline/logs")
    async def api_pipeline_logs(from_index: int = Query(0, ge=0)):
        """SSE endpoint — stream live pipeline log entries."""
        runner = get_runner()

        async def event_stream():
            async for chunk in runner.stream_logs(from_index=from_index):
                yield chunk

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/pipeline/logs/snapshot")
    async def api_pipeline_logs_snapshot(from_index: int = Query(0, ge=0)):
        """Return buffered logs as JSON (for polling fallback)."""
        runner = get_runner()
        return {"logs": runner.get_logs(from_index=from_index)}

    # ── Static files & SPA fallback ───────────────────────────────────────

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """Serve index.html for all non-API routes (SPA fallback)."""
            file_path = STATIC_DIR / full_path
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(STATIC_DIR / "index.html")

    return app
