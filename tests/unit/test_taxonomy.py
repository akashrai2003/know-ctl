"""Unit tests for taxonomy module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from socialgraph.knowledge.taxonomy import Taxonomy, TopicDefinition


@pytest.fixture
def taxonomy(tmp_path: Path) -> Taxonomy:
    data = {
        "topics": [
            {"name": "Local LLMs", "description": "Self-hosted models", "aliases": ["local models", "self-hosted llms"]},
            {"name": "Kubernetes", "description": "Container orchestration", "aliases": ["k8s"]},
        ]
    }
    p = tmp_path / "taxonomy.json"
    p.write_text(json.dumps(data))
    return Taxonomy.from_file(p)


def test_topic_names(taxonomy: Taxonomy):
    assert "Local LLMs" in taxonomy.topic_names
    assert "Kubernetes" in taxonomy.topic_names


def test_resolve_exact(taxonomy: Taxonomy):
    assert taxonomy.resolve("Local LLMs") == "Local LLMs"


def test_resolve_alias(taxonomy: Taxonomy):
    assert taxonomy.resolve("k8s") == "Kubernetes"
    assert taxonomy.resolve("local models") == "Local LLMs"


def test_resolve_case_insensitive(taxonomy: Taxonomy):
    assert taxonomy.resolve("LOCAL LLMS") == "Local LLMs"
    assert taxonomy.resolve("K8S") == "Kubernetes"


def test_resolve_unknown_returns_none(taxonomy: Taxonomy):
    assert taxonomy.resolve("something completely unknown") is None


def test_add_topic(taxonomy: Taxonomy):
    taxonomy.add_topic(TopicDefinition(name="Edge AI", description="AI on edge devices", aliases=["tinyml"]))
    assert "Edge AI" in taxonomy.topic_names
    assert taxonomy.resolve("tinyml") == "Edge AI"


def test_save_and_reload(taxonomy: Taxonomy, tmp_path: Path):
    out = tmp_path / "out.json"
    taxonomy.save(out)
    reloaded = Taxonomy.from_file(out)
    assert set(reloaded.topic_names) == set(taxonomy.topic_names)
