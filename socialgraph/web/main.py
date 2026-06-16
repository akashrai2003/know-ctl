"""FastAPI application for Social Graph web dashboard."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.config.settings import Settings
from socialgraph.web import service
from socialgraph.web.deps import get_db, get_settings, init_globals

logger = structlog.get_logger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Factory: create and configure the FastAPI app."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
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

    # ── API Routes ────────────────────────────────────────────────────────

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
        return await service.list_posts(db, topic=topic, author=author, q=q, limit=limit, offset=offset)

    @app.get("/api/posts/{urn:path}")
    async def api_post_detail(
        urn: str,
        db: AsyncSession = Depends(get_db),
        settings: Settings = Depends(get_settings),
    ):
        detail = await service.get_post_detail(db, urn, settings=settings)
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
