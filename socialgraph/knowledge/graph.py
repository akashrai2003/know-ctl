from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NodeData:
    node_id: str
    node_type: str
    label: str
    meta: dict = field(default_factory=dict)


@dataclass
class EdgeData:
    source: str
    target: str
    relation: str
    confidence_score: float = 1.0
    confidence_tag: str = "EXTRACTED"


class GraphBuilder:
    """Assembles graph nodes and edges from pipeline outputs."""

    def __init__(self) -> None:
        self._nodes: dict[str, NodeData] = {}
        self._edges: dict[tuple, EdgeData] = {}

    def add_node(self, node: NodeData) -> None:
        self._nodes[node.node_id] = node

    def add_edge(self, edge: EdgeData) -> None:
        key = (edge.source, edge.target, edge.relation)
        if key not in self._edges:
            self._edges[key] = edge

    def upsert_post_node(self, urn: str, author: str | None, content: str) -> None:
        from socialgraph.knowledge.obsidian import _urn_tail

        node_id = f"post_{_urn_tail(urn)}"
        self.add_node(
            NodeData(
                node_id=node_id,
                node_type="post",
                label=author or "Unknown",
                meta={"urn": urn, "content_preview": content[:100]},
            )
        )

    def upsert_topic_node(self, name: str, description: str = "") -> None:
        from socialgraph.knowledge.obsidian import _slug

        node_id = _slug(name)
        self.add_node(
            NodeData(
                node_id=node_id, node_type="topic", label=name, meta={"description": description}
            )
        )

    def link_post_to_topic(
        self, urn: str, topic_name: str, confidence_score: float, confidence_tag: str
    ) -> None:
        from socialgraph.knowledge.obsidian import _slug, _urn_tail

        post_node_id = f"post_{_urn_tail(urn)}"
        topic_node_id = _slug(topic_name)
        self.add_edge(
            EdgeData(
                source=post_node_id,
                target=topic_node_id,
                relation="conceptually_related_to",
                confidence_score=confidence_score,
                confidence_tag=confidence_tag,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "id": n.node_id,
                    "type": n.node_type,
                    "label": n.label,
                    "meta": n.meta,
                }
                for n in self._nodes.values()
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "relation": e.relation,
                    "confidence_score": e.confidence_score,
                    "confidence_tag": e.confidence_tag,
                }
                for e in self._edges.values()
            ],
        }

    def dump_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
