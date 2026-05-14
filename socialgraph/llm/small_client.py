from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


def _msg_preview(messages: list[dict], max_chars: int = 300) -> str:
    """Return a short preview of the last user message for log context."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            return content[:max_chars] + ("…" if len(content) > max_chars else "")
    return ""


class BatchLLMClient:
    """Async vLLM batch chat completions client."""

    def __init__(self, batch_url: str, model: str, timeout: float = 580.0) -> None:
        self._url = batch_url
        self._model = model
        self._timeout = timeout

    async def batch_chat(
        self,
        messages_list: list[list[dict]],
        response_format: dict | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> list[Any | None]:
        if not messages_list:
            return []
        payload: dict = {
            "model": self._model,
            "messages": messages_list,
            "temperature": temperature,
            # Required for Qwen3 — disables internal chain-of-thought tokens
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        batch_size = len(messages_list)
        logger.debug(
            "llm.batch_request",
            provider="vllm",
            model=self._model,
            batch_size=batch_size,
            structured=response_format is not None,
            prompt_preview=_msg_preview(messages_list[0]) if messages_list else None,
        )
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        latency_ms = round((time.monotonic() - t0) * 1000)
        usage = data.get("usage") or {}
        choices = data.get("choices", [])

        results: list[Any | None] = []
        for i, choice in enumerate(choices):
            content = (choice.get("message") or {}).get("content")
            if content is None:
                results.append(None)
                continue
            if response_format is not None:
                results.append(self._repair_json(content, i))
            else:
                results.append(content)

        success_count = sum(1 for r in results if r is not None)
        logger.info(
            "llm.batch_response",
            provider="vllm",
            model=self._model,
            batch_size=batch_size,
            latency_ms=latency_ms,
            success_count=success_count,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
        if results:
            first = results[0]
            preview = (json.dumps(first) if isinstance(first, dict) else str(first))[:300]
            logger.debug(
                "llm.batch_response_content",
                provider="vllm",
                model=self._model,
                first_output_preview=preview + ("…" if len(str(first)) > 300 else ""),
            )
        return results

    async def single_chat(
        self,
        messages: list[dict],
        response_format: dict | None = None,
        temperature: float = 0.0,
    ) -> Any | None:
        results = await self.batch_chat([messages], response_format, temperature)
        return results[0] if results else None

    @staticmethod
    def _repair_json(raw: str, index: int) -> dict | None:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Strip trailing commas before } or ]
        cleaned = re.sub(r",\s*}", "}", re.sub(r",\s*]", "]", raw.strip()))
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        # Extract first {...} block
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end])
            except json.JSONDecodeError:
                pass
        logger.error("json_repair_failed", choice_index=index, preview=raw[:200])
        return None
