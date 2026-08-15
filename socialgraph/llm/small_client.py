from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import httpx
import structlog

from socialgraph.utils import msg_preview as _msg_preview

logger = structlog.get_logger(__name__)


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
        """Perform a batch completion request via the vLLM server.

        Args:
            messages_list: List of lists of chat messages (one list of messages per request).
            response_format: Optional OpenAI-compatible response format dictionary (e.g. for JSON).
            temperature: Sampling temperature (defaults to 0.0).
            max_tokens: Optional limit on the number of generated tokens.

        Returns:
            A list containing parsed responses (dict, string, or None if failed).
        """
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
        """Perform a single completion request wrapped as a size-1 batch request.

        Args:
            messages: List of chat messages representing a single conversation.
            response_format: Optional OpenAI-compatible response format dictionary.
            temperature: Sampling temperature (defaults to 0.0).

        Returns:
            Parsed response (dict or string) or None if failed.
        """
        results = await self.batch_chat([messages], response_format, temperature)
        return results[0] if results else None

    @staticmethod
    def _repair_json(raw: str, index: int) -> dict | None:
        """Attempt to repair common JSON syntax issues from LLM outputs.

        Handles trailing commas and extracts JSON blocks if there is surrounding text.

        Args:
            raw: Raw LLM response string.
            index: Batch choice index (for logging purposes).

        Returns:
            A parsed dictionary, or None if repair attempts failed.
        """
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


# ── Hybrid client: auto-detects batch support ─────────────────────────────────


async def _probe_batch_endpoint(base_url: str, timeout: float = 5.0) -> bool:
    """Return True if the server has a working /v1/chat/completions/batch endpoint."""
    batch_url = f"{base_url.rstrip('/')}/v1/chat/completions/batch"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Send a minimal OPTIONS / HEAD probe; 405 = exists but wrong method, 404 = missing
            resp = await client.get(batch_url)
            return resp.status_code != 404
    except Exception:
        return False


class HybridLLMClient:
    """Smart vLLM client that uses the /batch endpoint when available.

    Falls back to concurrent individual /v1/chat/completions calls for servers
    that don't implement the batch extension (e.g. llama.cpp, Ollama, LM Studio).

    The probe result is cached per-instance so only one request is made.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "sk-placeholder",
        timeout: float = 580.0,
        concurrency: int = 8,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout
        self._concurrency = concurrency
        self._has_batch: bool | None = None  # None = not probed yet

    async def _check_batch(self) -> bool:
        if self._has_batch is None:
            self._has_batch = await _probe_batch_endpoint(self._base_url)
            logger.info(
                "llm.hybrid_probe",
                base_url=self._base_url,
                has_batch=self._has_batch,
                mode="batch" if self._has_batch else "concurrent-async",
            )
        return self._has_batch

    async def batch_chat(
        self,
        messages_list: list[list[dict]],
        response_format: dict | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> list[Any | None]:
        """Route to batch or concurrent-async depending on server capability."""
        if not messages_list:
            return []

        has_batch = await self._check_batch()

        if has_batch:
            batch_url = f"{self._base_url}/v1/chat/completions/batch"
            client = BatchLLMClient(batch_url, self._model, self._timeout)
            return await client.batch_chat(messages_list, response_format, temperature, max_tokens)
        else:
            return await self._concurrent_chat(
                messages_list, response_format, temperature, max_tokens
            )

    async def _concurrent_chat(
        self,
        messages_list: list[list[dict]],
        response_format: dict | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> list[Any | None]:
        """Send individual requests concurrently, respecting self._concurrency limit."""
        completions_url = f"{self._base_url}/v1/chat/completions"
        sem = asyncio.Semaphore(self._concurrency)

        logger.info(
            "llm.concurrent_start",
            provider="local",
            model=self._model,
            count=len(messages_list),
            concurrency=self._concurrency,
        )
        t0 = time.monotonic()

        async def _single(msgs: list[dict], index: int) -> Any | None:
            payload: dict = {
                "model": self._model,
                "messages": msgs,
                "temperature": temperature,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            if response_format:
                payload["response_format"] = response_format
            if max_tokens:
                payload["max_tokens"] = max_tokens

            headers = {"Authorization": f"Bearer {self._api_key}"}
            async with sem:
                try:
                    async with httpx.AsyncClient(timeout=self._timeout) as client:
                        resp = await client.post(completions_url, json=payload, headers=headers)
                        resp.raise_for_status()
                        data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    if response_format:
                        return BatchLLMClient._repair_json(content, index)
                    return content
                except Exception as exc:
                    logger.warning("llm.concurrent_single_failed", index=index, error=str(exc))
                    return None

        tasks = [_single(msgs, i) for i, msgs in enumerate(messages_list)]
        results = await asyncio.gather(*tasks)

        latency_ms = round((time.monotonic() - t0) * 1000)
        success_count = sum(1 for r in results if r is not None)
        logger.info(
            "llm.concurrent_done",
            provider="local",
            model=self._model,
            count=len(messages_list),
            success=success_count,
            latency_ms=latency_ms,
        )
        return list(results)

    async def single_chat(
        self,
        messages: list[dict],
        response_format: dict | None = None,
        temperature: float = 0.0,
    ) -> Any | None:
        """Single completion request."""
        results = await self.batch_chat([messages], response_format, temperature)
        return results[0] if results else None

