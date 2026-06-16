"""Semantic search utilities: cosine similarity, query embedding, nearest neighbors."""
from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING

import httpx
import structlog
from sqlalchemy import select

if TYPE_CHECKING:
    from socialgraph.storage.models import Post

logger = structlog.get_logger(__name__)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two equal-length float vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


async def embed_query(
    query: str,
    base_url: str,
    model: str,
    local_model_name: str = "Qwen/Qwen3-Embedding-0.6B",
    local_device: str = "cuda",
) -> list[float]:
    """Embed a single query string via the vLLM endpoint, falling back to local SentenceTransformer if needed."""
    if base_url:
        try:
            url = f"{base_url.rstrip('/')}/v1/embeddings"
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json={"model": model, "input": [query]})
                resp.raise_for_status()
                data = resp.json()
            return data["data"][0]["embedding"]
        except Exception as exc:
            logger.warning(
                "embed_query.remote_failed",
                error=str(exc),
                msg="falling back to local model",
            )

    vectors = await embed_texts_local([query], local_model_name, local_device)
    return vectors[0]


_local_model = None


def get_local_model(model_name: str, device: str):
    """Lazy-load and cache the local SentenceTransformer model."""
    global _local_model
    if _local_model is None:
        import torch
        from sentence_transformers import SentenceTransformer

        resolved_device = device
        if device == "cuda" and not torch.cuda.is_available():
            logger.warning(
                "local_embedding.cuda_unavailable_falling_back_to_cpu",
                requested=device,
            )
            resolved_device = "cpu"

        logger.info(
            "local_embedding.loading_model",
            model_name=model_name,
            device=resolved_device,
        )
        _local_model = SentenceTransformer(
            model_name,
            device=resolved_device,
            trust_remote_code=True,
        )
    return _local_model


async def embed_texts_local(
    texts: list[str], model_name: str, device: str
) -> list[list[float]]:
    """Generate embeddings locally on a separate thread via asyncio.to_thread."""
    import asyncio

    def _encode() -> list[list[float]]:
        model = get_local_model(model_name, device)
        embeddings = model.encode(texts)
        if hasattr(embeddings, "tolist"):
            return embeddings.tolist()
        return [list(emb) for emb in embeddings]

    return await asyncio.to_thread(_encode)


def find_similar(
    target_vector: list[float],
    embeddings: list[tuple[int, list[float]]],  # (post_id, vector)
    top_k: int = 10,
    exclude_post_id: int | None = None,
) -> list[tuple[int, float]]:
    """Return top-k (post_id, score) pairs by cosine similarity, descending."""
    scored = [
        (post_id, cosine_similarity(target_vector, vec))
        for post_id, vec in embeddings
        if post_id != exclude_post_id
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


async def load_embeddings(session) -> list[tuple[int, list[float]]]:  # type: ignore[type-arg]
    """Load all post embeddings from DB as (post_id, vector) tuples."""
    from socialgraph.storage.models import Embedding
    rows = await session.scalars(select(Embedding))
    result = []
    for row in rows:
        try:
            vec = json.loads(row.vector_json)
            result.append((row.post_id, vec))
        except (json.JSONDecodeError, ValueError):
            pass
    return result


async def keyword_search(session, query: str, limit: int = 10) -> list[Post]:
    """Simple LIKE-based full-text fallback when embeddings are unavailable."""
    from socialgraph.storage.models import Post
    pattern = f"%{query}%"
    result = await session.scalars(
        select(Post)
        .where(Post.content.like(pattern) | Post.title.like(pattern))
        .limit(limit)
    )
    return list(result.all())
