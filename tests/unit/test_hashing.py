"""Unit tests for the pipeline hashing utility."""

from __future__ import annotations

from socialgraph.pipeline.hashing import compute_input_hash


def test_compute_input_hash_deterministic() -> None:
    # Hash must be identical for identical inputs
    h1 = compute_input_hash("enrich", [1, 2, 3], "llama-70b", 1)
    h2 = compute_input_hash("enrich", [1, 2, 3], "llama-70b", 1)
    assert h1 == h2


def test_compute_input_hash_sensitive_to_inputs() -> None:
    h1 = compute_input_hash("enrich", [1, 2, 3], "llama-70b", 1)

    # Change stage name
    assert h1 != compute_input_hash("classify", [1, 2, 3], "llama-70b", 1)

    # Change input ids
    assert h1 != compute_input_hash("enrich", [1, 2, 4], "llama-70b", 1)

    # Change model id
    assert h1 != compute_input_hash("enrich", [1, 2, 3], "llama-8b", 1)

    # Change version
    assert h1 != compute_input_hash("enrich", [1, 2, 3], "llama-70b", 2)


def test_compute_input_hash_sorting() -> None:
    # Order of inputs should not affect the hash because it sorts input_ids
    h1 = compute_input_hash("enrich", [3, 2, 1], "llama-70b", 1)
    h2 = compute_input_hash("enrich", [1, 2, 3], "llama-70b", 1)
    assert h1 == h2
