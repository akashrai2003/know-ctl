from __future__ import annotations

import json
import time

import openai
import structlog

logger = structlog.get_logger(__name__)

# Groq error codes that mean "try the next model"
_RATE_LIMIT_CODES = {429, 503, 529}


def _msg_preview(messages: list[dict], max_chars: int = 300) -> str:
    """Return a short preview of the last user message for log context."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            return content[:max_chars] + ("…" if len(content) > max_chars else "")
    return ""


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
                    output_preview=content[:300] + ("…" if content and len(content) > 300 else "") if content else None,
                )
                if response_format:
                    return json.loads(content)
                return content
            except openai.RateLimitError as exc:
                latency_ms = round((time.monotonic() - t0) * 1000)
                logger.warning("groq.rate_limit", model=model, latency_ms=latency_ms, error=str(exc))
                last_exc = exc
            except openai.APIStatusError as exc:
                latency_ms = round((time.monotonic() - t0) * 1000)
                if exc.status_code in _RATE_LIMIT_CODES:
                    logger.warning("groq.quota_error", model=model, status=exc.status_code, latency_ms=latency_ms)
                    last_exc = exc
                else:
                    logger.error("groq.complete_failed", model=model, latency_ms=latency_ms, error=str(exc))
                    return None
            except Exception as exc:
                latency_ms = round((time.monotonic() - t0) * 1000)
                logger.error("groq.complete_failed", model=model, latency_ms=latency_ms, error=str(exc))
                return None
        logger.error("groq.all_models_failed", models=self._models, error=str(last_exc))
        return None
