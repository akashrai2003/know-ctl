"""Unit tests for local embedding fallback and semantic edge node matching."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from socialgraph.agents.base import StageContext
from socialgraph.agents.embed_agent import EmbedAgent
from socialgraph.agents.semantic_edge_agent import SemanticEdgeAgent
from socialgraph.knowledge.search import embed_query
from socialgraph.storage.models import GraphNode, Post


@pytest.mark.asyncio
@patch("socialgraph.knowledge.search.embed_texts_local")
async def test_embed_query_falls_back_to_local(mock_embed_local):
    mock_embed_local.return_value = [[0.1, 0.2, 0.3]]
    qvec = await embed_query(
        "hello", base_url="", model="foo", local_model_name="qwen", local_device="cpu"
    )
    assert qvec == [0.1, 0.2, 0.3]
    mock_embed_local.assert_called_once_with(["hello"], "qwen", "cpu")


@pytest.mark.asyncio
@patch("socialgraph.knowledge.search.embed_texts_local")
async def test_embed_agent_run_local_fallback(mock_embed_local):
    mock_embed_local.return_value = [[0.5, 0.6], [0.7, 0.8]]

    # Mock context, db, settings
    ctx = MagicMock(spec=StageContext)
    ctx.db = AsyncMock()
    ctx.settings = MagicMock()
    ctx.settings.vllm_base_url = ""
    ctx.settings.vllm_model = "vllm-model"
    ctx.settings.embedding_model = "qwen-0.6b"
    ctx.settings.embedding_device = "cpu"

    # Mock posts
    p1 = Post(id=1, urn="urn:li:activity:111", title="Title 1", content="Content 1")
    p2 = Post(id=2, urn="urn:li:activity:222", title="Title 2", content="Content 2")

    # Mock repo
    repo_mock = MagicMock()
    repo_mock.get_posts_without_embeddings = AsyncMock(return_value=[p1, p2])
    repo_mock.upsert_embedding = AsyncMock()

    with patch("socialgraph.agents.embed_agent.Repo", return_value=repo_mock):
        agent = EmbedAgent(batch_size=2)
        out = await agent.run(ctx)

        assert out.processed == 2
        assert out.failed == 0
        repo_mock.upsert_embedding.assert_any_call(
            post_id=1, vector_json=json.dumps([0.5, 0.6]), model="qwen-0.6b", dim=2
        )
        repo_mock.upsert_embedding.assert_any_call(
            post_id=2, vector_json=json.dumps([0.7, 0.8]), model="qwen-0.6b", dim=2
        )


@pytest.mark.asyncio
async def test_semantic_edge_agent_node_id_tail_match():
    # Mock context, db
    ctx = MagicMock(spec=StageContext)
    ctx.db = AsyncMock()

    # Set up mock data
    p1 = Post(id=1, urn="urn:li:activity:12345", title="Title 1", content="Content 1")
    p2 = Post(id=2, urn="urn:li:activity:67890", title="Title 2", content="Content 2")

    # Embeddings loaded from DB
    embeddings = [
        (1, [1.0, 0.0]),
        (2, [1.0, 0.0]),  # identical cosine similarity = 1.0 >= 0.85
    ]

    # GraphNode matches post_{urn_tail}
    n1 = GraphNode(id=10, node_id="post_12345", node_type="post", label="Author 1")
    n2 = GraphNode(id=11, node_id="post_67890", node_type="post", label="Author 2")

    # load_embeddings mock
    async def mock_load_embeddings(_db):
        return embeddings

    # Scalars queries mock
    mock_scalars = MagicMock()
    mock_scalars.all.side_effect = [
        [n1, n2],  # GraphNodes
        [p1, p2],  # Posts
    ]
    ctx.db.scalars = AsyncMock(return_value=mock_scalars)

    # Mock Repo
    repo_mock = MagicMock()
    repo_mock.upsert_graph_edge = AsyncMock()

    with (
        patch(
            "socialgraph.agents.semantic_edge_agent.load_embeddings",
            side_effect=mock_load_embeddings,
        ),
        patch("socialgraph.agents.semantic_edge_agent.Repo", return_value=repo_mock),
    ):
        agent = SemanticEdgeAgent(threshold=0.8)
        out = await agent.run(ctx)

        # Verification
        assert out.processed > 0
        # Verify it created an edge using GraphNode DB IDs (10 and 11)
        repo_mock.upsert_graph_edge.assert_any_call(
            source_node_id=10,
            target_node_id=11,
            relation="similar",
            confidence_score=1.0,
            confidence_tag="EMBEDDING",
        )
