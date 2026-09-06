"""Rank LinkedIn comments by information value.

Fetch many comments, keep the ones that add knowledge, drop applause and pitches.
"""

from __future__ import annotations

import re
from typing import Any

from socialgraph.storage.enums import CommentKind

NOISE_KIND = CommentKind.NOISE.value
USEFUL_KINDS = frozenset(
    {CommentKind.INSIGHT.value, CommentKind.QUESTION.value, CommentKind.RESOURCE.value}
)

_NOISE_EXACT = frozenset(
    {
        "nice",
        "nice.",
        "nice one",
        "nice one.",
        "thanks",
        "thanks.",
        "thank you",
        "thank you.",
        "thanks for sharing",
        "thanks for sharing.",
        "great share",
        "great share.",
        "great post",
        "great post.",
        "good read",
        "good read.",
        "well said",
        "well said.",
        "well put",
        "well put.",
        "following",
        "congrats",
        "congratulations",
        "interesting",
        "love this",
        "so true",
        "exactly",
        "agreed",
        "agree",
        "awesome",
        "amazing",
        "helpful",
        "useful",
        "good one",
        "cool",
        "this",
        "true",
        "great",
    }
)

_NOISE_PREFIX = re.compile(
    r"^(thanks?( you)?( for sharing)?[.!]?"
    r"|thank you[.!]?"
    r"|great (share|post|read|stuff)[.!]?"
    r"|nice one[.!]?"
    r"|well (said|put)[.!]?"
    r"|love this[.!]?"
    r"|so true[.!]?"
    r"|this is (gold|great|awesome)[.!]?)",
    re.IGNORECASE,
)

_PROMO = re.compile(
    r"(if you.?re looking to|our platform|check out my|visit my |"
    r"book a (call|demo)|sign up|try it (for )?free|\bdm me\b|"
    r"we (can )?help you|their platform supports|in short:|"
    r"hipaa compliant|live chat escalation)",
    re.IGNORECASE,
)

_KNOWLEDGE_URL = re.compile(
    r"(github\.com|arxiv\.org|huggingface\.co|readthedocs|"
    r"docs\.|wikipedia\.org|\.md(?:$|\s|#)|raw\.githubusercontent)",
    re.IGNORECASE,
)

_TECH = re.compile(
    r"\b(gpu|llm|kv.?cache|batch(?:ing|es)?|prefill|decode|quantiz\w*|"
    r"vllm|inference|throughput|latency|tokens?|cuda|triton|tensor|"
    r"kubernetes|rag|embedding|transformer|moe|speculative|disaggregat\w*|"
    r"prefix cache|int8|int4|vram)\b",
    re.IGNORECASE,
)

_NUMBER = re.compile(
    r"(\d+(?:\.\d+)?\s*%|\d+\s*(ms|gb|tb|[kmb]|tokens?|million)|"
    r"\b\d{2,}\b)",
    re.IGNORECASE,
)

_EMOJI_ONLY = re.compile(r"^[\W_\d]+$", re.UNICODE)


def rank_comment(text: str, has_external_url: bool = False) -> tuple[str, float]:
    """Return (kind, usefulness_score) for a comment body."""
    raw = (text or "").strip()
    if not raw:
        return NOISE_KIND, 0.0

    compact = re.sub(r"\s+", " ", raw)
    lower = compact.lower().rstrip("!.")

    if lower in _NOISE_EXACT:
        return NOISE_KIND, 0.0
    if len(compact) < 48 and _NOISE_PREFIX.match(compact):
        return NOISE_KIND, 0.0
    if len(compact) < 12 or _EMOJI_ONLY.match(compact):
        return NOISE_KIND, 0.0

    knowledge_url = bool(_KNOWLEDGE_URL.search(compact))
    promo = bool(_PROMO.search(compact))
    if promo and not knowledge_url:
        return NOISE_KIND, 0.1

    score = 0.0
    if has_external_url or knowledge_url:
        score += 2.5
    if "?" in compact:
        score += 2.0
    if _NUMBER.search(compact):
        score += 2.0
    if _TECH.search(compact):
        score += 1.5
    if len(compact) > 220:
        score += 2.0
    elif len(compact) > 110:
        score += 1.0
    elif len(compact) < 40:
        score -= 2.0

    if score < 1.5:
        return NOISE_KIND, max(score, 0.0)

    if knowledge_url or (has_external_url and not promo):
        return CommentKind.RESOURCE.value, score
    if "?" in compact:
        return CommentKind.QUESTION.value, score
    return CommentKind.INSIGHT.value, score


def needs_llm_review(text: str, kind: str, score: float) -> bool:
    """Use the local model only where heuristics are genuinely uncertain."""
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if len(compact) < 40 or score >= 3.0:
        return False
    return not (kind == NOISE_KIND and (_NOISE_PREFIX.match(compact) or _PROMO.search(compact)))


def is_useful_kind(kind: str | None) -> bool:
    return kind in USEFUL_KINDS


def effective_kind(comment: Any) -> str:
    stored = getattr(comment, "kind", None)
    if stored:
        return stored
    return rank_comment(
        getattr(comment, "text", "") or "",
        bool(getattr(comment, "has_external_url", False)),
    )[0]


def is_useful_comment(comment: Any) -> bool:
    return is_useful_kind(effective_kind(comment))


def useful_comments(comments: list[Any] | None, limit: int = 12) -> list[Any]:
    if not comments:
        return []
    ranked: list[tuple[float, Any]] = []
    for comment in comments:
        kind = effective_kind(comment)
        if not is_useful_kind(kind):
            continue
        stored = float(getattr(comment, "usefulness_score", 0) or 0)
        if stored <= 0:
            _, stored = rank_comment(
                getattr(comment, "text", "") or "",
                bool(getattr(comment, "has_external_url", False)),
            )
        ranked.append((stored, comment))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [c for _, c in ranked[:limit]]
