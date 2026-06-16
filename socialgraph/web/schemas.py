"""Pydantic response models for the REST API."""

from __future__ import annotations

from pydantic import BaseModel


class TopicOut(BaseModel):
    name: str
    description: str = ""
    post_count: int = 0
    slug: str = ""


class TopicDetailOut(BaseModel):
    name: str
    slug: str
    description: str = ""
    post_count: int = 0
    subtopics: list[str] = []
    top_authors: list[dict] = []
    trend: list[dict] = []
    posts: list[dict] = []


class PostOut(BaseModel):
    id: int
    urn: str
    platform: str = "linkedin"
    author: str | None = None
    subtitle: str | None = None
    date_raw: str | None = None
    title: str | None = None
    summary: str | None = None
    source_url: str | None = None
    topics: list[str] = []
    score: float | None = None  # semantic search score


class PostDetailOut(BaseModel):
    id: int
    urn: str
    platform: str = "linkedin"
    author: str | None = None
    subtitle: str | None = None
    date_raw: str | None = None
    title: str | None = None
    summary: str | None = None
    content: str = ""
    source_url: str | None = None
    topics: list[str] = []
    external_links: list[dict] = []
    comments: list[dict] = []
    similar_posts: list[dict] = []


class AuthorOut(BaseModel):
    name: str
    slug: str
    subtitle: str | None = None
    platform: str = "linkedin"
    post_count: int = 0


class AuthorDetailOut(BaseModel):
    name: str
    slug: str
    subtitle: str | None = None
    platform: str = "linkedin"
    post_count: int = 0
    top_topics: list[dict] = []
    posts: list[dict] = []


class SearchResult(BaseModel):
    id: int
    urn: str
    author: str | None = None
    title: str | None = None
    source_url: str | None = None
    score: float = 0.0
    topics: list[str] = []


class GraphNode(BaseModel):
    id: str
    label: str
    type: str  # "topic" or "post"
    size: int = 1
    color: str = "#555"
    topic: str | None = None  # which topic this post belongs to


class GraphLink(BaseModel):
    source: str
    target: str
    weight: float = 1.0
    relation: str = ""


class GraphData(BaseModel):
    nodes: list[GraphNode] = []
    links: list[GraphLink] = []


class StatsOut(BaseModel):
    total_posts: int = 0
    total_topics: int = 0
    total_authors: int = 0
    total_embeddings: int = 0
    total_external_links: int = 0
    total_comments: int = 0
    top_topics: list[dict] = []
    top_authors: list[dict] = []
    last_pipeline_run: dict | None = None
