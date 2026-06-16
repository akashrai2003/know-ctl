"""FastAPI dependency injection for Social Graph web server."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from socialgraph.config.settings import Settings
from socialgraph.storage.db import build_session_factory

# ── Singletons (set during lifespan) ──────────────────────────────────────────

_settings: Settings | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_globals(settings: Settings) -> None:
    """Initialize module-level singletons. Called once at app startup."""
    global _settings, _session_factory
    _settings = settings
    _session_factory = build_session_factory(settings.db_path)


def get_settings() -> Settings:
    assert _settings is not None, "Settings not initialised — call init_globals first"
    return _settings


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a DB session per request, auto-commit on success, rollback on error."""
    assert _session_factory is not None, "DB not initialised — call init_globals first"
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
