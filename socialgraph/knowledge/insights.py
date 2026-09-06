"""Structured post briefing produced by InsightAgent."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass
class CommunityInsight:
    author: str = ""
    claim: str = ""
    why_it_matters: str = ""


@dataclass
class InsightResource:
    title: str = ""
    url: str = ""
    value: str = ""


@dataclass
class PostInsight:
    thesis: str = ""
    article_takeaways: list[str] = field(default_factory=list)
    community_insights: list[CommunityInsight] = field(default_factory=list)
    resources: list[InsightResource] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    def is_empty(self) -> bool:
        return not (
            self.thesis
            or self.article_takeaways
            or self.community_insights
            or self.resources
            or self.open_questions
        )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def is_safe_resource_url(value: str) -> bool:
    """Return whether an LLM-produced resource URL is safe to render as a link."""
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except (TypeError, ValueError):
        return False


def parse_insight(raw: Any) -> PostInsight | None:
    if raw is None:
        return None
    if isinstance(raw, PostInsight):
        return raw
    data: Any = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None

    community: list[CommunityInsight] = []
    raw_community = data.get("community_insights")
    for item in raw_community if isinstance(raw_community, list) else []:
        if isinstance(item, dict):
            community.append(
                CommunityInsight(
                    author=str(item.get("author") or ""),
                    claim=str(item.get("claim") or ""),
                    why_it_matters=str(item.get("why_it_matters") or ""),
                )
            )
        elif isinstance(item, str) and item.strip():
            community.append(CommunityInsight(claim=item.strip()))

    resources: list[InsightResource] = []
    raw_resources = data.get("resources")
    for item in raw_resources if isinstance(raw_resources, list) else []:
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
            resources.append(
                InsightResource(
                    title=str(item.get("title") or ""),
                    url=url if is_safe_resource_url(url) else "",
                    value=str(item.get("value") or ""),
                )
            )

    takeaways = _string_list(data.get("article_takeaways"))
    questions = _string_list(data.get("open_questions"))
    insight = PostInsight(
        thesis=str(data.get("thesis") or "").strip(),
        article_takeaways=takeaways,
        community_insights=community,
        resources=resources,
        open_questions=questions,
    )
    return None if insight.is_empty() else insight


def insight_to_dict(raw: Any) -> dict[str, Any] | None:
    """Parse and serialize a briefing into a JSON-safe dictionary."""
    insight = parse_insight(raw)
    return asdict(insight) if insight else None
