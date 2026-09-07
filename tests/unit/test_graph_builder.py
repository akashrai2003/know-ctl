"""Unit tests for GraphBuilder and GraphBuildAgent."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from socialgraph.agents.base import StageContext
from socialgraph.agents.graph_build_agent import GraphBuildAgent
from socialgraph.knowledge.graph import GraphBuilder
from socialgraph.storage.enums import PostStatus
from socialgraph.storage.models import GraphEdge, GraphNode, Post, PostTopic, Topic


def test_graph_builder_operations() -> None:
    builder = GraphBuilder()

    # test upsert_post_node and upsert_topic_node
    builder.upsert_post_node("urn:li:activity:123456", "Alice", "Hello Python world!")
    builder.upsert_topic_node("Python Programming", "All about Python")

    # test link_post_to_topic
    builder.link_post_to_topic("urn:li:activity:123456", "Python Programming", 0.98, "high")

    data = builder.to_dict()
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1

    nodes_by_id = {n["id"]: n for n in data["nodes"]}
    assert "post_123456" in nodes_by_id
    assert nodes_by_id["post_123456"]["label"] == "Alice"
    assert nodes_by_id["post_123456"]["meta"]["urn"] == "urn:li:activity:123456"

    assert "python_programming" in nodes_by_id
    assert nodes_by_id["python_programming"]["meta"]["description"] == "All about Python"

    edge = data["edges"][0]
    assert edge["source"] == "post_123456"
    assert edge["target"] == "python_programming"
    assert edge["confidence_score"] == 0.98

    # test dump_json
    json_str = builder.dump_json()
    parsed = json.loads(json_str)
    assert parsed["nodes"][0]["id"] == data["nodes"][0]["id"]


@pytest.mark.asyncio
async def test_graph_build_agent_run(db_session: AsyncSession, test_settings) -> None:
    # Set up test database content
    post = Post(
        urn="urn:li:activity:1001",
        platform="linkedin",
        author="Bob",
        content="AI agents are great.",
        status=PostStatus.CLASSIFIED.value,
    )
    topic = Topic(name="AI Agents", description="Artificial Intelligence agents")
    db_session.add_all([post, topic])
    await db_session.flush()

    # link post to topic
    pt = PostTopic(post_id=post.id, topic_id=topic.id, confidence_score=0.9, confidence_tag="high")
    db_session.add(pt)
    await db_session.flush()

    # run agent
    agent = GraphBuildAgent()
    ctx = StageContext(
        run_id="test-run", settings=test_settings, db=db_session, stage="graph_build"
    )
    out = await agent.run(ctx)

    assert out.processed == 1

    # verify post status updated to graphed
    await db_session.refresh(post)
    assert post.status == PostStatus.GRAPHED.value

    # verify graph nodes created in DB
    nodes = (await db_session.scalars(select(GraphNode))).all()
    assert len(nodes) == 2
    node_ids = {n.node_id for n in nodes}
    assert "post_1001" in node_ids
    assert "ai_agents" in node_ids

    # verify graph edge created in DB
    edges = (await db_session.scalars(select(GraphEdge))).all()
    assert len(edges) == 1
    assert edges[0].relation == "conceptually_related_to"
    assert edges[0].confidence_score == 0.9


@pytest.mark.asyncio
async def test_graph_build_replaces_stale_classification_edges(
    db_session: AsyncSession, test_settings
) -> None:
    post = Post(
        urn="urn:li:activity:2002",
        platform="linkedin",
        author="Alice",
        content="CUDA inference",
        status=PostStatus.CLASSIFIED.value,
    )
    current = Topic(name="AI Infrastructure")
    stale = Topic(name="AI Agents")
    db_session.add_all([post, current, stale])
    await db_session.flush()
    db_session.add(PostTopic(post_id=post.id, topic_id=current.id, confidence_score=0.95))
    post_node = GraphNode(node_id="post_2002", node_type="post", label="Alice")
    stale_node = GraphNode(node_id="ai_agents", node_type="topic", label="AI Agents")
    db_session.add_all([post_node, stale_node])
    await db_session.flush()
    db_session.add(
        GraphEdge(
            source_node_id=post_node.id,
            target_node_id=stale_node.id,
            relation="conceptually_related_to",
        )
    )
    await db_session.commit()

    await GraphBuildAgent().run(
        StageContext("test", test_settings, db_session, "graph_build")
    )

    current_node = await db_session.scalar(
        select(GraphNode).where(GraphNode.node_id == "ai_infrastructure")
    )
    edges = list(
        (
            await db_session.execute(
                select(GraphNode.node_id)
                .join(GraphEdge, GraphEdge.target_node_id == GraphNode.id)
                .where(
                    GraphEdge.source_node_id == post_node.id,
                    GraphEdge.relation == "conceptually_related_to",
                )
            )
        ).scalars()
    )
    assert current_node is not None
    assert edges == ["ai_infrastructure"]
