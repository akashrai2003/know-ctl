"""Enumerations for status tracking and pipeline stages.

Centralises the string constants used across the storage and pipeline layers
so that typos are caught at import-time rather than silently breaking queries.
"""

from __future__ import annotations

import enum


class PostStatus(str, enum.Enum):
    """Processing status of a post in the pipeline."""

    PENDING = "pending"
    INGESTED = "ingested"
    ENRICHED = "enriched"
    CLASSIFIED = "classified"
    GRAPHED = "graphed"
    OK = "ok"
    FAILED = "failed"


class FetchStatus(str, enum.Enum):
    """Fetch status for external links."""

    PENDING = "pending"
    FETCHING = "fetching"
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineStage(str, enum.Enum):
    """Ordered pipeline stages."""

    INGEST = "ingest"
    COMMENTS = "comments"
    COMMENT_ENRICH = "comment_enrich"
    ENRICH = "enrich"
    CLASSIFY = "classify"
    EMBED = "embed"
    SUBTOPIC = "subtopic"
    SEMANTIC_EDGES = "semantic_edges"
    GRAPH_BUILD = "graph_build"
    VAULT_WRITE = "vault_write"


class ConfidenceTag(str, enum.Enum):
    """Confidence tag for classification and graph edges."""

    EXTRACTED = "EXTRACTED"
    INFERRED = "INFERRED"
    EMBEDDING = "EMBEDDING"
