"""Unit tests for the FastAPI web API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from socialgraph.config.settings import Settings
from socialgraph.web.main import create_app


@pytest.fixture
def client():
    settings = Settings(web_port=8888)
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_api_stats(client):
    with patch("socialgraph.web.service.get_stats", new_callable=AsyncMock) as mock:
        mock.return_value = {
            "total_posts": 5,
            "total_topics": 2,
            "total_authors": 3,
            "total_embeddings": 4,
            "total_external_links": 1,
            "total_comments": 10,
            "top_topics": [],
            "top_authors": [],
            "last_pipeline_run": None,
        }
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        assert resp.json()["total_posts"] == 5


def test_api_topics(client):
    with patch("socialgraph.web.service.list_topics", new_callable=AsyncMock) as mock:
        mock.return_value = [
            {"name": "AI", "description": "Artificial Intelligence", "post_count": 3, "slug": "ai"}
        ]
        resp = client.get("/api/topics")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["slug"] == "ai"


def test_api_topic_detail(client):
    with patch("socialgraph.web.service.get_topic_detail", new_callable=AsyncMock) as mock:
        mock.return_value = {
            "name": "AI",
            "slug": "ai",
            "description": "Artificial Intelligence",
            "post_count": 3,
            "subtopics": ["LLMs"],
            "top_authors": [],
            "trend": [],
            "posts": [],
        }
        resp = client.get("/api/topics/ai")
        assert resp.status_code == 200
        assert resp.json()["name"] == "AI"

        # Test not found
        mock.return_value = None
        resp = client.get("/api/topics/unknown")
        assert resp.status_code == 200
        assert "error" in resp.json()


def test_api_posts(client):
    with patch("socialgraph.web.service.list_posts", new_callable=AsyncMock) as mock:
        mock.return_value = [
            {
                "id": 1,
                "urn": "urn:li:activity:123",
                "platform": "linkedin",
                "author": "Alice",
                "subtitle": "engineer",
                "date_raw": "1d",
                "title": "Title",
                "summary": "Summary",
                "source_url": "http://Alice",
                "topics": ["AI"],
            }
        ]
        resp = client.get("/api/posts?limit=10&offset=0")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["author"] == "Alice"


def test_api_post_detail(client):
    with patch("socialgraph.web.service.get_post_detail", new_callable=AsyncMock) as mock:
        mock.return_value = {
            "id": 1,
            "urn": "urn:li:activity:123",
            "platform": "linkedin",
            "author": "Alice",
            "subtitle": "engineer",
            "date_raw": "1d",
            "title": "Title",
            "summary": "Summary",
            "content": "Full content",
            "source_url": "http://Alice",
            "topics": ["AI"],
            "external_links": [],
            "comments": [],
            "similar_posts": [],
        }
        resp = client.get("/api/posts/urn:li:activity:123")
        assert resp.status_code == 200
        assert resp.json()["urn"] == "urn:li:activity:123"

        mock.return_value = None
        resp = client.get("/api/posts/urn:li:activity:999")
        assert resp.status_code == 200
        assert "error" in resp.json()


def test_api_authors(client):
    with patch("socialgraph.web.service.list_authors", new_callable=AsyncMock) as mock:
        mock.return_value = [
            {
                "name": "Alice",
                "slug": "alice",
                "subtitle": "engineer",
                "platform": "linkedin",
                "post_count": 5,
            }
        ]
        resp = client.get("/api/authors")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "Alice"


def test_api_author_detail(client):
    with patch("socialgraph.web.service.get_author_detail", new_callable=AsyncMock) as mock:
        mock.return_value = {
            "name": "Alice",
            "slug": "alice",
            "subtitle": "engineer",
            "platform": "linkedin",
            "post_count": 5,
            "top_topics": [],
            "posts": [],
        }
        resp = client.get("/api/authors/alice")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Alice"

        mock.return_value = None
        resp = client.get("/api/authors/unknown")
        assert resp.status_code == 200
        assert "error" in resp.json()


def test_api_search(client):
    with patch("socialgraph.web.service.semantic_search", new_callable=AsyncMock) as mock:
        mock.return_value = [
            {
                "id": 1,
                "urn": "urn:li:activity:123",
                "author": "Alice",
                "title": "Title",
                "source_url": "http://Alice",
                "score": 0.95,
                "topics": ["AI"],
            }
        ]
        resp = client.get("/api/search?q=transformers")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["score"] == 0.95


def test_api_graph(client):
    with patch("socialgraph.web.service.get_graph_data", new_callable=AsyncMock) as mock:
        mock.return_value = {
            "nodes": [
                {"id": "topic_ai", "label": "AI", "type": "topic", "size": 1, "color": "#6366f1"}
            ],
            "links": [],
        }
        resp = client.get("/api/graph")
        assert resp.status_code == 200
        assert len(resp.json()["nodes"]) == 1
