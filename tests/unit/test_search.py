"""Unit tests for semantic search and keyword search functions."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.knowledge.search import (
    cosine_similarity,
    embed_query,
    find_similar,
    keyword_search,
    load_embeddings,
)
from socialgraph.storage.models import Embedding, Post


def test_cosine_similarity() -> None:
    # Identical vectors
    assert abs(cosine_similarity([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-6
    # Orthogonal vectors
    assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0]) - 0.0) < 1e-6
    # Opposite vectors
    assert abs(cosine_similarity([1.0, 0.0], [-1.0, 0.0]) - (-1.0)) < 1e-6
    # Empty or mismatched lengths
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0
    # Zero magnitude
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_find_similar() -> None:
    embeddings = [
        (1, [1.0, 0.0]),
        (2, [0.0, 1.0]),
        (3, [0.707, 0.707]),
    ]
    # target is close to [1.0, 0.0]
    top = find_similar([1.0, 0.1], embeddings, top_k=2)
    assert len(top) == 2
    # First should be post_id 1
    assert top[0][0] == 1
    # Second should be post_id 3 (diagonal/angle 45 deg)
    assert top[1][0] == 3

    # Exclude post_id 1
    top_excl = find_similar([1.0, 0.1], embeddings, top_k=2, exclude_post_id=1)
    assert len(top_excl) == 2
    assert top_excl[0][0] == 3


@pytest.mark.asyncio
async def test_load_embeddings(db_session: AsyncSession) -> None:
    post1 = Post(urn="urn:li:activity:1", platform="linkedin", content="foo")
    post2 = Post(urn="urn:li:activity:2", platform="linkedin", content="bar")
    db_session.add_all([post1, post2])
    await db_session.flush()

    emb1 = Embedding(post_id=post1.id, vector_json="[1.0, 2.0]")
    emb2 = Embedding(post_id=post2.id, vector_json="invalid-json")
    db_session.add_all([emb1, emb2])
    await db_session.flush()

    embs = await load_embeddings(db_session)
    assert len(embs) == 1
    assert embs[0][0] == post1.id
    assert embs[0][1] == [1.0, 2.0]


@pytest.mark.asyncio
async def test_keyword_search(db_session: AsyncSession) -> None:
    post1 = Post(
        urn="urn:li:activity:1", platform="linkedin", content="hello world", title="Greetings"
    )
    post2 = Post(urn="urn:li:activity:2", platform="linkedin", content="bye bye", title="Farewell")
    db_session.add_all([post1, post2])
    await db_session.flush()

    res = await keyword_search(db_session, "world")
    assert len(res) == 1
    assert res[0].urn == "urn:li:activity:1"

    res_title = await keyword_search(db_session, "Fare")
    assert len(res_title) == 1
    assert res_title[0].urn == "urn:li:activity:2"


@pytest.mark.asyncio
async def test_embed_query_remote_success(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/embeddings",
        json={"data": [{"embedding": [0.1, 0.2, 0.3]}]},
    )

    vector = await embed_query(
        query="test query",
        base_url="http://localhost:8000",
        model="some-model",
    )
    assert vector == [0.1, 0.2, 0.3]
