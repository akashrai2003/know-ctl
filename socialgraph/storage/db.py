from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from socialgraph.storage.models import Base


def build_engine(db_path: Path) -> AsyncEngine:
    db_url = f"sqlite+aiosqlite:///{db_path}"
    return create_async_engine(db_url, echo=False, future=True)


def build_session_factory(db_path: Path) -> async_sessionmaker[AsyncSession]:
    engine = build_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def create_all_tables(db_path: Path) -> None:
    """Create all tables (used in tests and `sg init`). Prefer Alembic in production."""
    engine = build_engine(db_path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


@asynccontextmanager
async def get_session(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
