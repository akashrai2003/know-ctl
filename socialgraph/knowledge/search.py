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


async def embed_texts_local(texts: list[str], model_name: str, device: str) -> list[list[float]]:
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
    if not target_vector or not embeddings:
        return []

    try:
        import numpy as np

        target = np.array(target_vector, dtype=np.float32)
        target_norm = np.linalg.norm(target)
        if target_norm == 0:
            return []
        target = target / target_norm

        post_ids = []
        vecs = []
        for pid, vec in embeddings:
            if pid != exclude_post_id and len(vec) == len(target_vector):
                post_ids.append(pid)
                vecs.append(vec)

        if not vecs:
            return []

        matrix = np.array(vecs, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1e-10
        matrix = matrix / norms

        sims = np.dot(matrix, target)

        if len(sims) <= top_k:
            top_indices = np.argsort(-sims)
        else:
            top_indices = np.argpartition(-sims, top_k)[:top_k]
            top_indices = top_indices[np.argsort(-sims[top_indices])]

        return [(post_ids[i], float(sims[i])) for i in top_indices]
    except Exception:
        scored = [
            (post_id, cosine_similarity(target_vector, vec))
            for post_id, vec in embeddings
            if post_id != exclude_post_id
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def build_similarity_map(
    embeddings: list[tuple[int, list[float]]],
    top_k: int = 5,
    min_score: float = 0.85,
) -> dict[int, list[tuple[int, float]]]:
    """Pre-compute top-k similar post pairs for all embeddings using vectorized matrix math."""
    if len(embeddings) < 2:
        return {}

    try:
        import numpy as np

        post_ids = np.array([pid for pid, _ in embeddings])
        vec_matrix = np.array([vec for _, vec in embeddings], dtype=np.float32)

        norms = np.linalg.norm(vec_matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1e-10
        norm_matrix = vec_matrix / norms

        sim_matrix = np.dot(norm_matrix, norm_matrix.T)

        result: dict[int, list[tuple[int, float]]] = {}
        for i, pid in enumerate(post_ids):
            sims = sim_matrix[i].copy()
            sims[i] = -1.0  # exclude self
            if len(sims) <= top_k:
                top_idx = np.argsort(-sims)
            else:
                top_idx = np.argpartition(-sims, top_k)[:top_k]
                top_idx = top_idx[np.argsort(-sims[top_idx])]

            matches = [(int(post_ids[j]), float(sims[j])) for j in top_idx if sims[j] >= min_score]
            if matches:
                result[int(pid)] = matches
        return result
    except Exception as exc:
        logger.warning("build_similarity_map.matrix_failed", error=str(exc))
        res = {}
        for pid, vec in embeddings:
            sims = find_similar(vec, embeddings, top_k=top_k, exclude_post_id=pid)
            filtered = [(other_id, score) for other_id, score in sims if score >= min_score]
            if filtered:
                res[pid] = filtered
        return res



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
        select(Post).where(Post.content.like(pattern) | Post.title.like(pattern)).limit(limit)
    )
    return list(result.all())
