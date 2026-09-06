from __future__ import annotations

from socialgraph.compat import StrEnum
from socialgraph.llm.large_client import GroqClient
from socialgraph.llm.small_client import BatchLLMClient, GroqBatchClient, HybridLLMClient

BatchClient = BatchLLMClient | HybridLLMClient | GroqBatchClient


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
    "rank_comments": TaskComplexity.SMALL_BATCH,
    # Small single — moderate volume
    "extract_url_content": TaskComplexity.SMALL_SINGLE,
    "classify_comment": TaskComplexity.SMALL_SINGLE,
    # Large — reasoning over post + article + thread
    "synthesize_taxonomy": TaskComplexity.LARGE,
    "build_graph_structure": TaskComplexity.LARGE,
    "expand_taxonomy": TaskComplexity.LARGE,
    "synthesize_insights": TaskComplexity.LARGE,
}


class LLMRouter:
    """Routes LLM tasks to appropriate client backends based on task complexity."""

    def __init__(self, batch_client: BatchClient, groq_client: GroqClient | None) -> None:
        """Initialize the router with batch and large model clients.

        Args:
            batch_client: Client for vLLM batch requests.
            groq_client: Optional client for Groq API requests.
        """
        self._batch = batch_client
        self._groq = groq_client

    def get_client(self, task: str) -> BatchClient | GroqClient:
        """Retrieve the appropriate LLM client for a given task.

        Args:
            task: Task identifier matching a ROUTING_TABLE entry.

        Returns:
            The recommended LLM client instance.
        """
        complexity = ROUTING_TABLE.get(task, TaskComplexity.SMALL_SINGLE)
        if complexity == TaskComplexity.LARGE and self._groq is not None:
            return self._groq
        return self._batch

    def is_batch_task(self, task: str) -> bool:
        """Determine if a task should be processed in batch mode.

        Args:
            task: Task identifier.

        Returns:
            True if the task is classified as SMALL_BATCH, else False.
        """
        return ROUTING_TABLE.get(task) == TaskComplexity.SMALL_BATCH

    @property
    def batch_client(self) -> BatchClient:
        """Get the underlying batch LLM client.

        Returns:
            The BatchLLMClient instance.
        """
        return self._batch

    @property
    def groq_client(self) -> GroqClient | None:
        """Get the underlying large LLM (Groq) client.

        Returns:
            The GroqClient instance, or None if not configured.
        """
        return self._groq
