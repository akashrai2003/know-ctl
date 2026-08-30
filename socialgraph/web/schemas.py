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


# ── Settings / Config ─────────────────────────────────────────────────────────


class SettingsOut(BaseModel):
    """All settings with secret values masked."""

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    vllm_base_url: str = ""
    vllm_model: str = ""
    vllm_api_key: str = ""
    embedding_model: str = ""
    embedding_device: str = "cuda"
    linkedin_email: str = ""
    linkedin_password: str = ""
    linkedin_cookie: str = ""
    batch_size: str = "10"
    llm_timeout: str = "580.0"
    max_comments: str = "5"
    schedule_interval_hours: str = "6.0"
    db_path: str = ""
    workspace_dir: str = ""
    obsidian_vault_path: str = ""
    log_level: str = "INFO"
    web_port: str = "8080"


class SettingsIn(BaseModel):
    """Bulk settings update payload."""

    groq_api_key: str | None = None
    groq_model: str | None = None
    vllm_base_url: str | None = None
    vllm_model: str | None = None
    vllm_api_key: str | None = None
    embedding_model: str | None = None
    embedding_device: str | None = None
    linkedin_email: str | None = None
    linkedin_password: str | None = None
    linkedin_cookie: str | None = None
    batch_size: str | None = None
    llm_timeout: str | None = None
    max_comments: str | None = None
    schedule_interval_hours: str | None = None
    db_path: str | None = None
    workspace_dir: str | None = None
    obsidian_vault_path: str | None = None
    log_level: str | None = None
    web_port: str | None = None


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    latency_ms: float | None = None


class IsConfiguredOut(BaseModel):
    configured: bool
    has_groq: bool
    has_vllm: bool
    has_linkedin: bool


# ── Pipeline ──────────────────────────────────────────────────────────────────


class PipelineRunRequest(BaseModel):
    start_from: str | None = None
    only_stage: str | None = None
    live: bool = False
    json_filename: str | None = None  # filename inside workspace dir


class PipelineStatusOut(BaseModel):
    state: str  # idle | running | completed | failed
    started_at: str | None = None
    completed_at: str | None = None
    last_result: dict | None = None
    log_count: int = 0
