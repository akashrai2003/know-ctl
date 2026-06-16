from __future__ import annotations

import sys
from enum import Enum

from socialgraph.llm.large_client import GroqClient
from socialgraph.llm.small_client import BatchLLMClient

if sys.version_info >= (3, 11):  # noqa: UP036
    from enum import StrEnum
else:
    class StrEnum(str, Enum):  # type: ignore[no-redef]  # noqa: UP042
        pass


class TaskComplexity(StrEnum):
    SMALL_BATCH = "small_batch"
    SMALL_SINGLE = "small_single"
    LARGE = "large"


ROUTING_TABLE: dict[str, TaskComplexity] = {
    # Small batch — high volume, repetitive structured extraction
    "extract_raw_topics": TaskComplexity.SMALL_BATCH,
    "classify_post_topics": TaskComplexity.SMALL_BATCH,
    "parse_link_metadata": TaskComplexity.SMALL_BATCH,
    "summarize_content": TaskComplexity.SMALL_BATCH,
    "generate_post_title_subtopic": TaskComplexity.SMALL_BATCH,
    # Small single — moderate volume
    "extract_url_content": TaskComplexity.SMALL_SINGLE,
    "classify_comment": TaskComplexity.SMALL_SINGLE,
    # Large — once-per-run or architectural decisions
    "synthesize_taxonomy": TaskComplexity.LARGE,
    "build_graph_structure": TaskComplexity.LARGE,
    "expand_taxonomy": TaskComplexity.LARGE,
    "synthesize_insights": TaskComplexity.LARGE,
}


class LLMRouter:
    def __init__(self, batch_client: BatchLLMClient, groq_client: GroqClient | None) -> None:
        self._batch = batch_client
        self._groq = groq_client

    def get_client(self, task: str) -> BatchLLMClient | GroqClient:
        complexity = ROUTING_TABLE.get(task, TaskComplexity.SMALL_SINGLE)
        if complexity == TaskComplexity.LARGE and self._groq is not None:
            return self._groq
        return self._batch

    def is_batch_task(self, task: str) -> bool:
        return ROUTING_TABLE.get(task) == TaskComplexity.SMALL_BATCH

    @property
    def batch_client(self) -> BatchLLMClient:
        return self._batch

    @property
    def groq_client(self) -> GroqClient:
        return self._groq
