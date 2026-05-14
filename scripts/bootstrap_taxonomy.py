#!/usr/bin/env python3
"""Bootstrap the topic taxonomy.

Steps:
1. Load linkedin_saved_posts.json, sample every 10th post (~150 posts)
2. Batch to vLLM: extract 3-5 raw topic strings per post
3. Aggregate + count → top-50 raw topics
4. Send to Groq: synthesize 12-20 canonical topics with name, description, aliases
5. Save to topic_taxonomy.json and insert into DB
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from socialgraph.config.settings import Settings
from socialgraph.llm.small_client import BatchLLMClient
from socialgraph.llm.large_client import GroqClient
from socialgraph.llm.prompts import (
    EXTRACT_RAW_TOPICS_SYSTEM,
    EXTRACT_RAW_TOPICS_USER,
    SYNTHESIZE_TAXONOMY_SYSTEM,
    SYNTHESIZE_TAXONOMY_USER,
)
from socialgraph.knowledge.taxonomy import Taxonomy, TopicDefinition
from socialgraph.storage.db import build_session_factory, get_session
from socialgraph.storage.repo import Repo


async def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="linkedin_saved_posts.json", dest="json_path")
    args = parser.parse_args()

    settings = Settings()
    settings.ensure_workspace()

    posts_path = Path(args.json_path)
    if not posts_path.exists():
        print(f"ERROR: {posts_path} not found. Run from the project root.", file=sys.stderr)
        sys.exit(1)

    with open(posts_path, encoding="utf-8") as f:
        all_posts = json.load(f)

    # Sample every 10th post
    sampled = [p for i, p in enumerate(all_posts) if i % 10 == 0]
    print(f"Sampled {len(sampled)} / {len(all_posts)} posts")

    # ── Step 1: Extract raw topics via vLLM batch ─────────────────────────
    batch_client = BatchLLMClient(
        batch_url=settings.vllm_batch_url,
        model=settings.vllm_model,
        timeout=settings.llm_timeout,
    )

    batch_size = settings.batch_size
    raw_topic_lists: list[list[str]] = []

    print(f"Extracting raw topics in batches of {batch_size}...")
    for i in range(0, len(sampled), batch_size):
        batch = sampled[i : i + batch_size]
        messages_list = [
            [
                {"role": "system", "content": EXTRACT_RAW_TOPICS_SYSTEM},
                {"role": "user", "content": EXTRACT_RAW_TOPICS_USER.format(content=p.get("content", "")[:800])},
            ]
            for p in batch
        ]
        results = await batch_client.batch_chat(messages_list)
        for result in results:
            if isinstance(result, list):
                raw_topic_lists.append(result)
            elif isinstance(result, str):
                try:
                    parsed = json.loads(result)
                    if isinstance(parsed, list):
                        raw_topic_lists.append(parsed)
                except json.JSONDecodeError:
                    pass
        print(f"  Batch {i // batch_size + 1}/{(len(sampled) + batch_size - 1) // batch_size} done")

    # ── Step 2: Aggregate → top-50 raw topics ────────────────────────────
    counter: Counter[str] = Counter()
    for topic_list in raw_topic_lists:
        for t in topic_list:
            if isinstance(t, str) and t.strip():
                counter[t.strip()] += 1

    top_50 = counter.most_common(50)
    print(f"\nTop 20 raw topics:")
    for topic, count in top_50[:20]:
        print(f"  {count:3d}x  {topic}")

    # ── Step 3: Synthesize canonical taxonomy via Groq ────────────────────
    groq_client = GroqClient(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        base_url=settings.groq_base_url,
        fallback_models=settings.groq_fallback_models,
    )

    raw_topics_json = json.dumps(
        [{"topic": t, "count": c} for t, c in top_50],
        ensure_ascii=False,
        indent=2,
    )

    print("\nSynthesizing canonical taxonomy via Groq...")
    result = groq_client.complete(
        messages=[
            {"role": "system", "content": SYNTHESIZE_TAXONOMY_SYSTEM},
            {"role": "user", "content": SYNTHESIZE_TAXONOMY_USER.format(raw_topics_json=raw_topics_json)},
        ],
        response_format={"type": "json_object"},
    )

    if not result or not isinstance(result, dict) or "topics" not in result:
        print("ERROR: Groq did not return valid taxonomy JSON.", file=sys.stderr)
        print(f"Response: {result}", file=sys.stderr)
        sys.exit(1)

    topics = result["topics"]
    print(f"\nSynthesized {len(topics)} canonical topics:")
    for t in topics:
        print(f"  - {t['name']}: {t.get('description', '')[:60]}")

    # ── Step 4: Save taxonomy.json ────────────────────────────────────────
    taxonomy_data = {"topics": topics}
    settings.taxonomy_path.write_text(
        json.dumps(taxonomy_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nSaved taxonomy to {settings.taxonomy_path}")

    # ── Step 5: Insert topics into DB ────────────────────────────────────
    factory = build_session_factory(settings.db_path)
    async with get_session(factory) as session:
        repo = Repo(session)
        inserted = 0
        for t in topics:
            topic, created = await repo.get_or_create_topic(t["name"])
            if created:
                topic.description = t.get("description", "")
                topic.aliases = t.get("aliases", [])
                inserted += 1
    print(f"Inserted {inserted} new topics into DB ({settings.db_path})")


if __name__ == "__main__":
    asyncio.run(main())
