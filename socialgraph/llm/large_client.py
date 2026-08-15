from __future__ import annotations

import json
import time

import openai
import structlog

from socialgraph.utils import msg_preview as _msg_preview

logger = structlog.get_logger(__name__)

# Groq error codes that mean "try the next model"
_RATE_LIMIT_CODES = {429, 503, 529}


class GroqClient:
    """Synchronous Groq client with automatic model fallback on rate limits."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.groq.com/openai/v1",
        fallback_models: list[str] | None = None,
    ) -> None:
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self._models = [model] + (fallback_models or [])

    @property
    def _model(self) -> str:
        return self._models[0]

    def complete(
        self,
        messages: list[dict],
        response_format: dict | None = None,
        temperature: float = 0.0,
    ) -> str | dict | None:
        """Perform a synchronous chat completion request using the Groq API.

        Attempts fallback to alternative models if rate limits or status errors occur.

        Args:
            messages: List of chat messages representing the prompt.
            response_format: Optional OpenAI-compatible response format dictionary.
            temperature: Sampling temperature (defaults to 0.0).

        Returns:
            The parsed JSON response if response_format is provided, the string
            content if unstructured, or None if the request failed across all models.
        """
        last_exc: Exception | None = None
        logger.debug(
            "llm.request",
            provider="groq",
            model=self._model,
            messages_count=len(messages),
            prompt_preview=_msg_preview(messages),
            structured=response_format is not None,
        )
        for model in self._models:
            kwargs: dict = {"model": model, "messages": messages, "temperature": temperature}
            if response_format:
                kwargs["response_format"] = response_format
                if "qwen" in model.lower():
                    kwargs["extra_body"] = {"reasoning_effort": "none"}
            t0 = time.monotonic()
            try:
                resp = self._client.chat.completions.create(**kwargs)
                latency_ms = round((time.monotonic() - t0) * 1000)
                content = resp.choices[0].message.content
                usage = resp.usage
                if model != self._models[0]:
                    logger.info("groq.fallback_succeeded", model=model)
                logger.info(
                    "llm.response",
                    provider="groq",
                    model=model,
                    latency_ms=latency_ms,
                    prompt_tokens=usage.prompt_tokens if usage else None,
                    completion_tokens=usage.completion_tokens if usage else None,
                    total_tokens=usage.total_tokens if usage else None,
                )
                logger.debug(
                    "llm.response_content",
                    provider="groq",
                    model=model,
                    output_preview=content[:300] + ("…" if content and len(content) > 300 else "")
                    if content
                    else None,
                )
                if response_format:
                    clean_content = content.strip()
                    if clean_content.startswith("```"):
                        clean_content = clean_content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                    return json.loads(clean_content)
                return content
            except openai.RateLimitError as exc:
                latency_ms = round((time.monotonic() - t0) * 1000)
                logger.warning(
                    "groq.rate_limit", model=model, latency_ms=latency_ms, error=str(exc)
                )
                last_exc = exc
            except openai.APIStatusError as exc:
                latency_ms = round((time.monotonic() - t0) * 1000)
                logger.warning(
                    "groq.model_error",
                    model=model,
                    status=exc.status_code,
                    latency_ms=latency_ms,
                    error=str(exc),
                )
                last_exc = exc
            except Exception as exc:
                latency_ms = round((time.monotonic() - t0) * 1000)
                logger.warning(
                    "groq.model_failed", model=model, latency_ms=latency_ms, error=str(exc)
                )
                last_exc = exc
        logger.error("groq.all_models_failed", models=self._models, error=str(last_exc))
        return None
