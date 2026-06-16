"""Factory functions for constructing LLM clients from Settings."""

from __future__ import annotations

from socialgraph.config.settings import Settings
from socialgraph.llm.large_client import GroqClient
from socialgraph.llm.router import LLMRouter
from socialgraph.llm.small_client import BatchLLMClient


def build_router(settings: Settings) -> LLMRouter:
    """Construct an :class:`LLMRouter` wired to the configured vLLM and Groq backends.

    Args:
        settings: Application settings providing API URLs, keys, and model names.

    Returns:
        A fully initialised LLM router.
    """
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
