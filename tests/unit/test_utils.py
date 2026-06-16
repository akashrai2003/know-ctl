"""Unit tests for shared utility functions."""

from __future__ import annotations

from socialgraph.utils import msg_preview, slugify, urn_tail


def test_slugify() -> None:
    # Basic slugification
    assert slugify("Hello World") == "hello_world"
    # Special characters
    assert slugify("AI & Machine Learning!!!") == "ai_machine_learning"
    # Leading/trailing non-alphanumeric chars
    assert slugify("...some_text...") == "some_text"
    # Max length truncation
    assert slugify("a" * 100, max_length=50) == "a" * 50
    # Empty or only symbols
    assert slugify("!!!") == ""


def test_urn_tail() -> None:
    assert urn_tail("urn:li:activity:7458137957485699072") == "7458137957485699072"
    assert urn_tail("urn:li:activity") == "activity"
    assert urn_tail("singlesegment") == "singlesegment"


def test_msg_preview() -> None:
    # Last message is user
    messages = [
        {"role": "system", "content": "You are an assistant."},
        {"role": "user", "content": "How do I build a knowledge graph?"},
    ]
    assert msg_preview(messages) == "How do I build a knowledge graph?"

    # Truncation
    messages_long = [
        {"role": "user", "content": "a" * 500},
    ]
    assert msg_preview(messages_long, max_chars=10) == "aaaaaaaaaa…"

    # Empty list
    assert msg_preview([]) == ""

    # Last message is assistant (will look backwards for last user message)
    messages_assistant = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "World"},
    ]
    assert msg_preview(messages_assistant) == "Hello"
