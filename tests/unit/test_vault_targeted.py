"""Tests for single-note vault regeneration."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.agents.base import StageContext
from socialgraph.agents.vault_write_agent import VaultWriteAgent
from socialgraph.storage.models import Author, Post


@pytest.mark.asyncio
async def test_targeted_vault_write_does_not_rebuild_author_table(
    db_session: AsyncSession, test_settings
):
    post = Post(
        urn="urn:li:activity:targeted",
        platform="linkedin",
        author="New Author",
        content="Original source text",
        status="ok",
        insight_json=(
            '{"thesis":"A grounded briefing.","article_takeaways":[],'
            '"community_insights":[],"resources":[],"open_questions":[]}'
        ),
    )
    db_session.add_all([post, Author(name="Existing Author", slug="existing_author", post_count=3)])
    await db_session.commit()

    output = await VaultWriteAgent(urns=[post.urn], rebuild_collections=False).run(
        StageContext("test", test_settings, db_session, "vault_write")
    )

    authors = list((await db_session.scalars(select(Author))).all())
    note_path = test_settings.obsidian_vault_path / "linkedin" / "posts" / "post_targeted.md"
    assert output.processed == 1
    assert output.meta["targeted"] is True
    assert [author.name for author in authors] == ["Existing Author"]
    assert "A grounded briefing." in note_path.read_text(encoding="utf-8")
