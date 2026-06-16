"""Incremental pipeline for social-graph.

Runs all pipeline stages sequentially, only processing posts not yet completed at each stage.
"""

from __future__ import annotations

from typing import Any

import structlog

from socialgraph.agents.base import StageContext
from socialgraph.agents.classify_agent import ClassifyAgent
from socialgraph.agents.comment_agent import CommentAgent
from socialgraph.agents.comment_enrich_agent import CommentEnrichAgent
from socialgraph.agents.embed_agent import EmbedAgent
from socialgraph.agents.enrich_agent import EnrichAgent
from socialgraph.agents.graph_build_agent import GraphBuildAgent
from socialgraph.agents.ingest_agent import IngestAgent
from socialgraph.agents.semantic_edge_agent import SemanticEdgeAgent
from socialgraph.agents.subtopic_agent import SubtopicAgent
from socialgraph.agents.vault_write_agent import VaultWriteAgent
from socialgraph.config.settings import Settings
from socialgraph.storage.db import build_session_factory, get_session

logger = structlog.get_logger(__name__)


def _get_router(settings: Settings):
    from socialgraph.llm.large_client import GroqClient
    from socialgraph.llm.router import LLMRouter
    from socialgraph.llm.small_client import BatchLLMClient

    batch = BatchLLMClient(
        batch_url=settings.vllm_batch_url,
        model=settings.vllm_model,
        timeout=settings.llm_timeout,
    )
    groq = None
    if settings.groq_api_key:
        groq = GroqClient(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            base_url=settings.groq_base_url,
            fallback_models=settings.groq_fallback_models,
        )
    return LLMRouter(batch, groq)


def _get_taxonomy(settings: Settings):
    from socialgraph.knowledge.taxonomy import Taxonomy

    if settings.taxonomy_path.exists():
        return Taxonomy.from_file(settings.taxonomy_path)
    return None


async def run_incremental_pipeline(settings: Settings) -> dict[str, Any]:
    """Run all pipeline stages in sequence.

    Each stage operates incrementally by querying the database for only the unprocessed posts.
    """
    logger.info("incremental_pipeline.start")
    factory = build_session_factory(settings.db_path)

    # 1. Ingest stage (live mode)
    logger.info("incremental_pipeline.stage", stage="ingest")
    async with get_session(factory) as session:
        ctx = StageContext(run_id="scheduler-ingest", settings=settings, db=session, stage="ingest")
        ingest_agent = IngestAgent(live_mode=True)
        ingest_out = await ingest_agent.run(ctx)

    posts_ingested = ingest_out.processed
    logger.info("incremental_pipeline.stage_done", stage="ingest", processed=posts_ingested)

    # 2. Comments stage
    logger.info("incremental_pipeline.stage", stage="comments")
    async with get_session(factory) as session:
        ctx = StageContext(
            run_id="scheduler-comments", settings=settings, db=session, stage="comments"
        )
        comment_agent = CommentAgent(max_per_post=settings.max_comments)
        await comment_agent.run(ctx)

    # Load shared LLM router and taxonomy
    router = _get_router(settings)
    taxonomy = _get_taxonomy(settings)

    # 3. Comment enrichment stage
    logger.info("incremental_pipeline.stage", stage="comment_enrich")
    async with get_session(factory) as session:
        ctx = StageContext(
            run_id="scheduler-comment-enrich", settings=settings, db=session, stage="comment_enrich"
        )
        comment_enrich_agent = CommentEnrichAgent(router=router)
        await comment_enrich_agent.run(ctx)

    # 4. Post external URL enrichment stage
    logger.info("incremental_pipeline.stage", stage="enrich")
    async with get_session(factory) as session:
        ctx = StageContext(run_id="scheduler-enrich", settings=settings, db=session, stage="enrich")
        enrich_agent = EnrichAgent(router=router)
        await enrich_agent.run(ctx)

    # 5. Topic classification stage
    logger.info("incremental_pipeline.stage", stage="classify")
    if taxonomy:
        async with get_session(factory) as session:
            ctx = StageContext(
                run_id="scheduler-classify", settings=settings, db=session, stage="classify"
            )
            classify_agent = ClassifyAgent(router=router, taxonomy=taxonomy)
            await classify_agent.run(ctx)
    else:
        logger.warning("incremental_pipeline.skip_classify", reason="taxonomy file not found")

    # 6. Embedding generation stage
    logger.info("incremental_pipeline.stage", stage="embed")
    async with get_session(factory) as session:
        ctx = StageContext(run_id="scheduler-embed", settings=settings, db=session, stage="embed")
        embed_agent = EmbedAgent(batch_size=settings.batch_size)
        await embed_agent.run(ctx)

    # 7. Subtopic generation stage
    logger.info("incremental_pipeline.stage", stage="subtopic")
    async with get_session(factory) as session:
        ctx = StageContext(
            run_id="scheduler-subtopic", settings=settings, db=session, stage="subtopic"
        )
        subtopic_agent = SubtopicAgent(router=router)
        await subtopic_agent.run(ctx)

    # 8. Semantic similarity edges stage
    logger.info("incremental_pipeline.stage", stage="semantic_edges")
    async with get_session(factory) as session:
        ctx = StageContext(
            run_id="scheduler-semantic_edges", settings=settings, db=session, stage="semantic_edges"
        )
        semantic_edge_agent = SemanticEdgeAgent()
        await semantic_edge_agent.run(ctx)

    # 9. Knowledge graph building stage
    logger.info("incremental_pipeline.stage", stage="graph_build")
    async with get_session(factory) as session:
        ctx = StageContext(
            run_id="scheduler-graph_build", settings=settings, db=session, stage="graph_build"
        )
        graph_build_agent = GraphBuildAgent()
        await graph_build_agent.run(ctx)

    # 10. Obsidian vault writing stage
    logger.info("incremental_pipeline.stage", stage="vault_write")
    async with get_session(factory) as session:
        ctx = StageContext(
            run_id="scheduler-vault_write", settings=settings, db=session, stage="vault_write"
        )
        vault_write_agent = VaultWriteAgent()
        await vault_write_agent.run(ctx)

    logger.info("incremental_pipeline.complete", posts_ingested=posts_ingested)
    return {
        "status": "success",
        "posts_processed": posts_ingested,
    }
