"""Unit tests for obsidian note rendering."""

from __future__ import annotations

from datetime import datetime

from socialgraph.knowledge.obsidian import (
    render_author_note,
    render_post_note,
    render_recent_posts,
    render_topic_note,
)


def test_post_note_contains_urn():
    content = render_post_note(
        urn="urn:li:activity:1234567890",
        platform="linkedin",
        author="Test Author",
        subtitle="Engineer at ACME",
        date_raw="1d",
        content="This is the post content",
        source_url="https://www.linkedin.com/feed/update/urn:li:activity:1234567890/",
        topic_names=["AI/ML", "Open Source"],
        external_links=[],
        comments_notable=False,
        community="ai_core",
        confidence="EXTRACTED",
        created_at=datetime(2025, 1, 1),
    )
    assert "urn:li:activity:1234567890" in content
    assert "Test Author" in content
    assert "AI/ML" in content


def test_post_note_no_injection():
    """Adversarial author name must not break YAML frontmatter."""
    content = render_post_note(
        urn="urn:li:activity:999",
        platform="linkedin",
        author="Evil\nauthor_override: injected",
        subtitle=None,
        date_raw=None,
        content="Normal content",
        source_url=None,
        topic_names=[],
        external_links=[],
        comments_notable=False,
        community=None,
        confidence="EXTRACTED",
        created_at=datetime(2025, 1, 1),
    )
    # Frontmatter section (between --- markers) must not contain a bare newline in any value
    fm_end = content.index("---", 3)
    frontmatter = content[:fm_end]
    # "author_override" must NOT appear as a bare YAML key
    assert "\nauthor_override:" not in frontmatter


def test_topic_note_contains_posts():
    content = render_topic_note(
        name="Local LLMs",
        description="Self-hosted LLMs",
        subtopic_groups={
            "": [
                {
                    "urn": "urn:li:activity:111",
                    "author": "Jane",
                    "content": "Some post about llama.cpp",
                },
            ]
        },
        related_topics=["Edge AI"],
    )
    assert "Local LLMs" in content
    assert "Jane" in content
    assert "Edge AI" in content


def test_topic_note_post_count():
    content = render_topic_note(
        name="Kubernetes",
        description="Container orchestration",
        subtopic_groups={
            "": [{"urn": f"urn:li:activity:{i}", "author": "A", "content": "k8s"} for i in range(5)]
        },
        related_topics=[],
    )
    assert "5 posts" in content


def test_topic_note_links_to_subtopic_note():
    content = render_topic_note(
        name="AI Infrastructure",
        description="Serving systems",
        subtopic_groups={
            "GPU Optimization": [{"urn": "urn:li:activity:7501683033209516033", "content": "CUDA"}]
        },
        related_topics=[],
    )
    assert "[[ai_infrastructure__gpu_optimization|GPU Optimization]] — 1 posts" in content


def test_recent_posts_are_grouped_by_decoded_publication_date_newest_first():
    content = render_recent_posts(
        [
            {
                "urn": "urn:li:activity:7499856654121795584",
                "author": "Older Author",
                "title": "Older inference post",
                "date_raw": "5d •  ",
                "primary_topic": "Large Language Models",
            },
            {
                "urn": "urn:li:activity:7501683033209516033",
                "author": "Newest Author",
                "title": "Newest model post",
                "date_raw": "Reposted from Someone • 15h •  ",
                "primary_topic": "Model Optimization",
            },
        ],
        generated_at=datetime(2026, 9, 7),
    )
    assert "## 2026-09-04" in content
    assert "(15h at last sync)" in content
    assert "[[model_optimization|Model Optimization]]" in content
    assert content.index("Newest model post") < content.index("Older inference post")


def test_render_author_note():
    content = render_author_note(
        name="Jane Doe",
        _author_slug="jane_doe",
        subtitle="Software Architect",
        platform="linkedin",
        post_count=2,
        topics_with_counts=[("AI/ML", 2)],
        posts=[
            {
                "urn": "urn:li:activity:001",
                "title": "First post",
                "date_raw": "1d",
                "content": "hello ml",
            },
            {
                "urn": "urn:li:activity:002",
                "title": "Second post",
                "date_raw": "2d",
                "content": "more ml",
            },
        ],
    )
    assert "Jane Doe" in content
    assert "Software Architect" in content
    assert "First post" in content
    assert "Second post" in content
    assert "[[ai_ml|AI/ML]] (2 posts)" in content
