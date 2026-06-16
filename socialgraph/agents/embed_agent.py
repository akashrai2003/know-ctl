"""Embed agent: generate and store vLLM text embeddings for all posts."""

from __future__ import annotations

import json

import httpx
import structlog

from socialgraph.agents.base import StageContext, StageOutput
from socialgraph.storage.repo import Repo

logger = structlog.get_logger(__name__)

BATCH_SIZE = 32
EMBED_TIMEOUT = 120.0


class EmbedAgent:
    name = "embed"

    def __init__(self, batch_size: int = BATCH_SIZE) -> None:
        self._batch_size = batch_size

    async def run(self, ctx: StageContext) -> StageOutput:
        from socialgraph.knowledge.search import embed_texts_local

        repo = Repo(ctx.db)
        posts = await repo.get_posts_without_embeddings()

        if not posts:
            return StageOutput(
                stage=self.name, skipped=1, meta={"reason": "all posts already embedded"}
            )

        base_url = ctx.settings.vllm_base_url.rstrip("/") if ctx.settings.vllm_base_url else ""
        model = ctx.settings.vllm_model

        local_model = ctx.settings.embedding_model
        local_device = ctx.settings.embedding_device

        logger.info(
            "embed.start",
            total=len(posts),
            vllm_url=f"{base_url}/v1/embeddings" if base_url else None,
            local_model=local_model,
            local_device=local_device,
        )
        processed = failed = 0
        use_local_fallback = not bool(base_url)

        for i in range(0, len(posts), self._batch_size):
            batch = posts[i : i + self._batch_size]
            texts = [f"{p.title or ''}\n{p.content[:1000]}".strip() for p in batch]

            vectors = None
            used_model = model

            if not use_local_fallback:
                try:
                    async with httpx.AsyncClient(timeout=EMBED_TIMEOUT) as client:
                        resp = await client.post(
                            f"{base_url}/v1/embeddings",
                            json={"model": model, "input": texts},
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        embeddings_data = data.get("data", [])
                        if len(embeddings_data) != len(batch):
                            raise ValueError(
                                f"Expected {len(batch)} embeddings, got {len(embeddings_data)}"
                            )
                        vectors = [emb_obj.get("embedding", []) for emb_obj in embeddings_data]
                except Exception as exc:
                    logger.warning("embed.remote_failed_switching_to_local", error=str(exc))
                    use_local_fallback = True

            if use_local_fallback or vectors is None:
                try:
                    vectors = await embed_texts_local(texts, local_model, local_device)
                    used_model = local_model
                except Exception as exc:
                    logger.error("embed.local_batch_failed", batch_start=i, error=str(exc))
                    failed += len(batch)
                    continue

            # Store the embeddings
            try:
                for post, vector in zip(batch, vectors, strict=False):
                    await repo.upsert_embedding(
                        post_id=post.id,
                        vector_json=json.dumps(vector),
                        model=used_model,
                        dim=len(vector),
                    )
                    processed += 1
                await ctx.db.commit()
                logger.info(
                    "embed.batch_done",
                    batch_end=i + len(batch),
                    total=len(posts),
                )
            except Exception as exc:
                logger.error("embed.db_write_failed", batch_start=i, error=str(exc))
                failed += len(batch)

        logger.info("embed.complete", processed=processed, failed=failed)
        return StageOutput(stage=self.name, processed=processed, failed=failed)
