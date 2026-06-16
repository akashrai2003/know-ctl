"""Shared pytest fixtures for social-graph tests."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.config.settings import Settings
from socialgraph.storage.db import build_session_factory, create_all_tables, get_session


@pytest.fixture
def sample_posts_json(tmp_path: Path) -> Path:
    """Fixture to generate a temporary JSON file with sample posts."""
    posts = [
        {
            "urn": f"urn:li:activity:{1000 + i}",
            "author": f"Author {i}",
            "content": f"Post {i} about AI and machine learning tools.",
            "subtitle": f"Role {i}",
            "date": "1d",
            "source_url": f"https://linkedin.com/posts/activity-{1000 + i}",
        }
        for i in range(5)
    ]
    p = tmp_path / "posts.json"
    p.write_text(json.dumps(posts, indent=2), encoding="utf-8")
    return p


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Fixture to generate test settings pointed to a temporary workspace."""
    settings = Settings(
        db_path=tmp_path / ".socialgraph" / "test.db",
        workspace_dir=tmp_path / ".socialgraph",
        obsidian_vault_path=tmp_path / "vault",
        vllm_base_url="http://localhost:9999",
        groq_api_key="test-key",
    )
    settings.ensure_workspace()
    return settings


@pytest.fixture
async def db_session(test_settings: Settings) -> AsyncGenerator[AsyncSession, None]:
    """Fixture that builds the database schema and yields an async session."""
    await create_all_tables(test_settings.db_path)
    factory = build_session_factory(test_settings.db_path)
    async with get_session(factory) as session:
        yield session
