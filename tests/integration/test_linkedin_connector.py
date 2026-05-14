"""Integration test: LinkedIn JSON connector."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from socialgraph.connectors.linkedin import LinkedInJSONConnector, find_posts, urn_to_url


@pytest.fixture
def sample_json(tmp_path: Path) -> Path:
    data = [
        {
            "urn": "urn:li:activity:7458137957485699072",
            "author": "Test User",
            "subtitle": "Engineer",
            "date": "2d",
            "content": "This is a test post about AI and Kubernetes deployment strategies.",
        },
        {
            "urn": "urn:li:activity:9999999999999999999",
            "author": "Another User",
            "content": "Another post about open source tools.",
        },
    ]
    p = tmp_path / "posts.json"
    p.write_text(json.dumps(data))
    return p


@pytest.mark.asyncio
async def test_load_from_json(sample_json: Path):
    connector = LinkedInJSONConnector(sample_json)
    posts = await connector.fetch_saved_posts()
    assert len(posts) == 2
    assert posts[0].urn == "urn:li:activity:7458137957485699072"
    assert posts[0].author == "Test User"
    assert posts[0].platform == "linkedin"


@pytest.mark.asyncio
async def test_missing_urn_skipped(tmp_path: Path):
    data = [{"content": "no urn here"}, {"urn": "urn:li:activity:123", "content": "has urn"}]
    p = tmp_path / "posts.json"
    p.write_text(json.dumps(data))
    connector = LinkedInJSONConnector(p)
    posts = await connector.fetch_saved_posts()
    assert len(posts) == 1
    assert posts[0].urn == "urn:li:activity:123"


def test_urn_to_url():
    urn = "urn:li:activity:7458137957485699072"
    url = urn_to_url(urn)
    assert url == "https://www.linkedin.com/feed/update/urn:li:activity:7458137957485699072/"


def test_find_posts_nested():
    obj = {
        "data": {
            "elements": [
                {
                    "summary": {"text": "Post content here"},
                    "title": {"text": "Author Name"},
                    "trackingUrn": "urn:li:activity:12345",
                }
            ]
        }
    }
    posts = find_posts(obj)
    assert len(posts) == 1
    assert posts[0]["urn"] == "urn:li:activity:12345"
    assert posts[0]["content"] == "Post content here"


def test_find_posts_terminates_on_empty():
    """Ensure find_posts doesn't hang on empty responses."""
    result = find_posts({})
    assert result == []
    result = find_posts([])
    assert result == []
    result = find_posts(None)
    assert result == []
