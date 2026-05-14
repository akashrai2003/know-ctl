---
name: llm-routing
description: Dual-model LLM routing for social-graph. Small model = self-hosted Qwen3.5-9B-FP8 via vLLM batch endpoint (ngrok). Large model = Groq via OpenAI SDK. Covers TaskComplexity enum, routing table, BatchLLMClient pattern, Groq client, escalation rules, and cost discipline.
origin: social-graph
---

# LLM Routing

Use this skill when adding new LLM-powered tasks. Route to the correct model tier based on volume, criticality, and reasoning depth required.

## Two-Tier Architecture

| Tier | Model | Endpoint | When to Use |
|------|-------|----------|-------------|
| **SMALL** | `Qwen3.5-9B-FP8` | vLLM via ngrok `/v1/chat/completions/batch` | High-volume, repetitive, structured extraction |
| **LARGE** | Groq model | `https://api.groq.com/openai/v1` | Critical decisions, taxonomy, graph structure, cross-post synthesis |

Both use the **OpenAI Python SDK** pointed at different `base_url` values. No LiteLLM needed.

---

## TaskComplexity Routing Table

```python
class TaskComplexity(StrEnum):
    SMALL_BATCH  = "small_batch"   # vLLM batch endpoint — 10 messages per call
    SMALL_SINGLE = "small_single"  # vLLM single completion
    LARGE        = "large"         # Groq — once-per-run or critical path

ROUTING_TABLE: dict[str, TaskComplexity] = {
    # Small batch (high volume, repetitive)
    "extract_raw_topics":    TaskComplexity.SMALL_BATCH,
    "classify_post_topics":  TaskComplexity.SMALL_BATCH,
    "parse_link_metadata":   TaskComplexity.SMALL_BATCH,
    "summarize_content":     TaskComplexity.SMALL_BATCH,
    # Small single (moderate volume)
    "extract_url_content":   TaskComplexity.SMALL_SINGLE,
    "classify_comment":      TaskComplexity.SMALL_SINGLE,
    # Large (once-per-run / architecture decisions)
    "synthesize_taxonomy":   TaskComplexity.LARGE,
    "build_graph_structure": TaskComplexity.LARGE,
    "expand_taxonomy":       TaskComplexity.LARGE,
    "synthesize_insights":   TaskComplexity.LARGE,
}
```

---

## BatchLLMClient (Small Model)

```python
# socialgraph/llm/small_client.py
class BatchLLMClient:
    """Async client for vLLM batch chat completions endpoint."""

    def __init__(self, url: str, model: str, timeout: float = 580.0):
        self._url = url
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
            "chat_template_kwargs": {"enable_thinking": False},  # required for Qwen3
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices", [])
        results = []
        for i, choice in enumerate(choices):
            content = (choice.get("message") or {}).get("content")
            if content is None:
                results.append(None)
                continue
            if response_format is not None:
                results.append(self._parse_json(content, i))
            else:
                results.append(content)
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
    def _parse_json(raw: str, index: int) -> dict | None:
        """Parse JSON from LLM response with repair fallback."""
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Strip trailing commas
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
        logger.error(f"JSON repair failed for choice[{index}]")
        return None
```

### Key constraints for vLLM / Qwen3.5:
- Always include `"chat_template_kwargs": {"enable_thinking": False}` — without this Qwen3 outputs `<think>` blocks that break JSON parsing
- `temperature=0.0` for structured extraction tasks
- `BATCH_SIZE=10` per batch call (configurable via `SG_BATCH_SIZE`)
- Timeout: 580 seconds (just under common 10-minute proxy limits)

---

## GroqClient (Large Model)

```python
# socialgraph/llm/large_client.py
import openai

class GroqClient:
    """OpenAI SDK pointed at Groq's OpenAI-compatible endpoint."""

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.groq.com/openai/v1"):
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def complete(
        self,
        messages: list[dict],
        response_format: dict | None = None,
        temperature: float = 0.0,
    ) -> str | dict:
        kwargs: dict = {"model": self._model, "messages": messages, "temperature": temperature}
        if response_format:
            kwargs["response_format"] = response_format
        resp = self._client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content
        if response_format:
            return json.loads(content)
        return content
```

### Groq usage notes:
- Groq uses OpenAI-compatible API: `base_url="https://api.groq.com/openai/v1"`
- Auth: `api_key=GROQ_API_KEY` env var
- Recommended models: `llama-3.3-70b-versatile` (high quality), `llama-3.1-8b-instant` (fast/cheap fallback)
- No `chat_template_kwargs` needed (standard OpenAI format)
- Groq has generous free tier but rate limits — use only for `LARGE` tasks

---

## LLM Router

```python
# socialgraph/llm/router.py
class LLMRouter:
    def __init__(self, batch_client: BatchLLMClient, groq_client: GroqClient):
        self._batch = batch_client
        self._groq = groq_client

    def get_client(self, task: str) -> BatchLLMClient | GroqClient:
        complexity = ROUTING_TABLE.get(task, TaskComplexity.SMALL_SINGLE)
        if complexity == TaskComplexity.LARGE:
            return self._groq
        return self._batch

    def is_batch_task(self, task: str) -> bool:
        return ROUTING_TABLE.get(task) == TaskComplexity.SMALL_BATCH
```

---

## Escalation Rules

1. If `BatchLLMClient.batch_chat()` returns `None` for a slot after 3 retries → escalate that single item to Groq
2. If Groq returns `None` → log error, mark post as `status="failed"`, continue pipeline
3. If vLLM endpoint is unreachable (connection error) → fall back to Groq for the entire batch, log as a warning
4. Never silently skip — every escalation is logged with `structlog` including task name, post URN, and reason

---

## Cost Discipline

Track per pipeline run in `PipelineRun.stage_counts_json`:

```json
{
  "llm_calls": {
    "small_batch_calls": 152,
    "small_batch_items": 1508,
    "large_calls": 3,
    "escalations": 12
  }
}
```

Rules:
- Escalate model tier **only** when lower tier fails with a clear reasoning gap
- Never use Groq for per-post classification — the volume is too high
- Log token estimates: vLLM returns `usage` in response; capture it

---

## JSON Response Format Pattern

For structured outputs from either model, always use:

```python
response_format = {
    "type": "json_schema",
    "json_schema": {
        "name": "TopicClassification",
        "schema": {
            "type": "object",
            "properties": {
                "topics": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"}
            },
            "required": ["topics", "confidence"],
            "additionalProperties": False
        }
    }
}
```

Validate with Pydantic after parsing, not before — LLM output validation is a boundary check.
