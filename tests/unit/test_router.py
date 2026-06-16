"""Unit tests for LLM router."""

from __future__ import annotations

from unittest.mock import MagicMock

from socialgraph.llm.large_client import GroqClient
from socialgraph.llm.router import ROUTING_TABLE, LLMRouter, TaskComplexity
from socialgraph.llm.small_client import BatchLLMClient


def test_routing_table_completeness():
    """Every task in the routing table maps to a valid complexity."""
    for task, complexity in ROUTING_TABLE.items():
        assert isinstance(complexity, TaskComplexity), f"Invalid complexity for task {task!r}"


def test_batch_client_returned_for_small_tasks():
    batch = MagicMock(spec=BatchLLMClient)
    groq = MagicMock(spec=GroqClient)
    router = LLMRouter(batch, groq)
    client = router.get_client("classify_post_topics")
    assert client is batch


def test_groq_returned_for_large_tasks():
    batch = MagicMock(spec=BatchLLMClient)
    groq = MagicMock(spec=GroqClient)
    router = LLMRouter(batch, groq)
    client = router.get_client("synthesize_taxonomy")
    assert client is groq


def test_unknown_task_defaults_to_small():
    batch = MagicMock(spec=BatchLLMClient)
    groq = MagicMock(spec=GroqClient)
    router = LLMRouter(batch, groq)
    client = router.get_client("some_random_unknown_task")
    assert client is batch


def test_is_batch_task():
    batch = MagicMock(spec=BatchLLMClient)
    groq = MagicMock(spec=GroqClient)
    router = LLMRouter(batch, groq)
    assert router.is_batch_task("classify_post_topics") is True
    assert router.is_batch_task("synthesize_taxonomy") is False
    assert router.is_batch_task("unknown") is False
