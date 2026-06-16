from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class TopicDefinition:
    name: str
    description: str = ""
    aliases: list[str] | None = None

    def __post_init__(self) -> None:
        if self.aliases is None:
            self.aliases = []


class Taxonomy:
    """In-memory topic taxonomy loaded from topic_taxonomy.json."""

    def __init__(self, topics: list[TopicDefinition]) -> None:
        self._topics = topics
        # Build alias → canonical name index
        self._alias_index: dict[str, str] = {}
        for t in topics:
            self._alias_index[t.name.lower()] = t.name
            for alias in t.aliases or []:
                self._alias_index[alias.lower()] = t.name

    @classmethod
    def from_file(cls, path: Path) -> Taxonomy:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        topics = [
            TopicDefinition(
                name=item["name"],
                description=item.get("description", ""),
                aliases=item.get("aliases", []),
            )
            for item in data.get("topics", [])
        ]
        logger.info("taxonomy.loaded", count=len(topics))
        return cls(topics)

    @property
    def topic_names(self) -> list[str]:
        return [t.name for t in self._topics]

    def resolve(self, raw_name: str) -> str | None:
        """Resolve a raw topic name to canonical name, or None if no match."""
        # Try exact match first
        hit = self._alias_index.get(raw_name.lower())
        if hit:
            return hit
        # Model sometimes returns "TopicName: description" — strip the suffix
        if ":" in raw_name:
            stripped = raw_name.split(":", 1)[0].strip()
            hit = self._alias_index.get(stripped.lower())
            if hit:
                return hit
        return None

    def add_topic(self, topic: TopicDefinition) -> None:
        self._topics.append(topic)
        self._alias_index[topic.name.lower()] = topic.name
        for alias in topic.aliases or []:
            self._alias_index[alias.lower()] = topic.name

    def save(self, path: Path) -> None:
        data = {
            "topics": [
                {"name": t.name, "description": t.description, "aliases": t.aliases}
                for t in self._topics
            ]
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def as_prompt_list(self) -> str:
        """Format topics for LLM prompt — names only, no descriptions."""
        return "\n".join(f"- {t.name}" for t in self._topics)
