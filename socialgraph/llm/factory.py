"""Factory functions for constructing LLM clients from Settings."""

from __future__ import annotations

from socialgraph.config.settings import Settings
from socialgraph.llm.large_client import GroqClient
from socialgraph.llm.router import LLMRouter
from socialgraph.llm.small_client import BatchLLMClient, HybridLLMClient


def build_router(settings: Settings) -> LLMRouter:
    """Construct an :class:`LLMRouter` wired to the configured vLLM and Groq backends.

    Uses :class:`HybridLLMClient` when a vLLM base URL is configured — it
    auto-detects whether the server supports the ``/v1/chat/completions/batch``
    endpoint and falls back to concurrent individual calls if not (e.g. llama.cpp,
    Ollama, LM Studio).

    Falls back to the legacy :class:`BatchLLMClient` if only a batch URL is set
    (backward-compatible with existing .env setups).

    Args:
        settings: Application settings providing API URLs, keys, and model names.

    Returns:
        A fully initialised LLM router.
    """
    # Prefer HybridLLMClient when a base URL is available (covers llama.cpp etc.)
    if settings.vllm_base_url:
        batch: BatchLLMClient | HybridLLMClient = HybridLLMClient(
            base_url=settings.vllm_base_url,
            model=settings.vllm_model,
            api_key=settings.vllm_api_key or "sk-placeholder",
            timeout=settings.llm_timeout,
            concurrency=settings.batch_size,
        )
    elif settings.vllm_batch_url:
        # Legacy: batch URL configured directly
        batch = BatchLLMClient(
            batch_url=settings.vllm_batch_url,
            model=settings.vllm_model,
            timeout=settings.llm_timeout,
        )
    else:
        # No local model — use a dummy BatchLLMClient pointing nowhere
        # (Groq will handle all tasks via LLMRouter fallback)
        batch = BatchLLMClient(
            batch_url="http://localhost:8000/v1/chat/completions/batch",
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
