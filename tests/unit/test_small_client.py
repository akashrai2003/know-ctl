"""Unit tests for BatchLLMClient and JSON repair utility."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from socialgraph.llm.small_client import BatchLLMClient


def test_repair_json() -> None:
    # 1. Valid JSON
    assert BatchLLMClient._repair_json('{"key": "value"}', 0) == {"key": "value"}

    # 2. Trailing commas
    assert BatchLLMClient._repair_json('{"key": "value",}', 0) == {"key": "value"}
    assert BatchLLMClient._repair_json('{"arr": [1, 2, ,]}', 0) is None  # invalid, double comma
    assert BatchLLMClient._repair_json('{"arr": [1, 2,]}', 0) == {"arr": [1, 2]}

    # 3. Block extraction
    assert BatchLLMClient._repair_json('some text {\n"foo": "bar"\n} other text', 0) == {
        "foo": "bar"
    }

    # 4. Invalid JSON
    assert BatchLLMClient._repair_json("not json", 0) is None
    assert BatchLLMClient._repair_json("", 0) is None


@pytest.mark.asyncio
async def test_batch_chat_empty() -> None:
    client = BatchLLMClient("http://vllm/batch", "model-name")
    assert await client.batch_chat([]) == []


@pytest.mark.asyncio
async def test_batch_chat_success(httpx_mock: HTTPXMock) -> None:
    client = BatchLLMClient("http://vllm/batch", "model-name")

    response_data = {
        "choices": [
            {"message": {"content": '{"result": "ok"}'}},
            {"message": {"content": "raw text output"}},
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }

    httpx_mock.add_response(
        url="http://vllm/batch",
        json=response_data,
    )

    # 1. Structured/response format (JSON parsing/repair)
    results = await client.batch_chat(
        messages_list=[[{"role": "user", "content": "hi"}], [{"role": "user", "content": "bye"}]],
        response_format={"type": "json_object"},
    )
    assert len(results) == 2
    assert results[0] == {"result": "ok"}
    assert results[1] is None  # "raw text output" is not valid json

    # 2. Raw text mode
    httpx_mock.add_response(
        url="http://vllm/batch",
        json=response_data,
    )
    results_raw = await client.batch_chat(
        messages_list=[[{"role": "user", "content": "hi"}], [{"role": "user", "content": "bye"}]],
    )
    assert results_raw == ['{"result": "ok"}', "raw text output"]


@pytest.mark.asyncio
async def test_single_chat(httpx_mock: HTTPXMock) -> None:
    client = BatchLLMClient("http://vllm/batch", "model-name")

    httpx_mock.add_response(
        url="http://vllm/batch",
        json={
            "choices": [{"message": {"content": "single output"}}],
        },
    )

    res = await client.single_chat([{"role": "user", "content": "hi"}])
    assert res == "single output"
