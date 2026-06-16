"""Unit tests for storage and pipeline enums."""

from __future__ import annotations

from socialgraph.storage.enums import ConfidenceTag, FetchStatus, PipelineStage, PostStatus


def test_enum_values() -> None:
    # PostStatus
    assert PostStatus.PENDING.value == "pending"
    assert PostStatus.INGESTED.value == "ingested"
    assert PostStatus.OK.value == "ok"

    # FetchStatus
    assert FetchStatus.PENDING.value == "pending"
    assert FetchStatus.SKIPPED.value == "skipped"

    # PipelineStage
    assert PipelineStage.INGEST.value == "ingest"
    assert PipelineStage.VAULT_WRITE.value == "vault_write"

    # ConfidenceTag
    assert ConfidenceTag.EXTRACTED.value == "EXTRACTED"
    assert ConfidenceTag.INFERRED.value == "INFERRED"
