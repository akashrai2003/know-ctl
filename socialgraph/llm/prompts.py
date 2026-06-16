"""Prompt templates for LLM tasks."""

from __future__ import annotations

CLASSIFY_POST_TOPICS_SYSTEM = """\
You are a topic classifier for professional social media posts.
Given a post's content and a list of canonical topic names, assign the most relevant topics.
Respond with valid JSON only. No explanation."""

CLASSIFY_POST_TOPICS_USER = """\
Available topics (use ONLY these exact names in your response):
{topics}

Post content:
{content}

Respond with JSON:
{{
  "topics": ["Topic1", "Topic2"],
  "confidence": 0.85
}}

Rules:
- Assign 1-3 topics max
- Use ONLY the exact topic names from the list above (do not include descriptions)
- confidence: 0.0–1.0 reflecting how clearly the post fits the chosen topics
- If nothing fits, return {{"topics": [], "confidence": 0.1}}
"""

EXTRACT_RAW_TOPICS_SYSTEM = """\
You extract topic labels from social media posts.
Respond with a JSON list of 3–5 concise topic strings. No explanation."""

EXTRACT_RAW_TOPICS_USER = """\
Post:
{content}

Return JSON array of 3-5 topic strings, e.g.:
["Kubernetes", "CI/CD", "Platform Engineering"]
"""

SYNTHESIZE_TAXONOMY_SYSTEM = """\
You design topic taxonomies for knowledge bases.
You will receive a list of raw topic strings extracted from ~150 social media posts.
Synthesize a canonical taxonomy of 12–20 topics.
Respond with valid JSON only."""

SYNTHESIZE_TAXONOMY_USER = """\
Raw topics (with approximate frequencies):
{raw_topics_json}

Design a taxonomy of 12–20 canonical topics. Each topic should:
- Be broad enough to group 10+ posts
- Have a clear, professional name
- Not overlap significantly with other topics

Return JSON:
{{
  "topics": [
    {{
      "name": "Local LLMs",
      "description": "Self-hosted language model deployment and inference",
      "aliases": ["local models", "self-hosted LLMs", "on-prem AI"]
    }}
  ]
}}
"""

SUMMARIZE_CONTENT_SYSTEM = """\
You write rich, informative summaries of web content for a professional knowledge base.
Respond with 3–5 sentences covering: what the resource is, its key ideas or findings, \
and why it matters. No headers, no lists, no emojis. Plain prose only."""

SUMMARIZE_CONTENT_USER = """\
Title: {title}
URL: {url}

Content:
{excerpt}

Write a 3–5 sentence summary covering the key ideas, findings, or value of this content.
"""

SUMMARIZE_COMMENT_LINK_SYSTEM = """\
You write concise, insightful summaries of web resources for a professional knowledge base.
A LinkedIn commenter shared a link — use their comment as context to understand *why* \
they found it relevant. Respond with 2–3 sentences covering: what the resource is and \
what makes it valuable in the context of the discussion. No headers, no lists, no emojis."""

SUMMARIZE_COMMENT_LINK_USER = """\
A LinkedIn commenter wrote:
"{commenter_name}: {comment_text}"

They linked to this resource:
Title: {title}
URL: {url}

Article content:
{excerpt}

Write a 2–3 sentence summary of what makes this resource valuable, informed by why the commenter shared it.
"""

GENERATE_POST_TITLE_SUBTOPIC_SYSTEM = """\
You are a knowledge organizer for a professional AI/tech knowledge base.
For each post you receive, generate:
1. A two-line title capturing the post's subject and key insight.
2. A subtopic name (2-4 words, title-case) that groups this post within its parent topic.
3. A 3-5 sentence summary that distills the post's core message — clean, no emojis, no hashtags.

Respond with valid JSON only. No explanation."""

GENERATE_POST_TITLE_SUBTOPIC_USER = """\
Parent topic: {topic_name}

Existing subtopics (prefer these if a good match exists):
{existing_subtopics}

Post content:
{content}

Return JSON:
{{
  "title": "First line: what is this about\\nSecond line: the key insight or takeaway",
  "subtopic": "Subtopic Name",
  "summary": "3-5 sentence distillation of the post's core message and value."
}}

Rules for title:
- Line 1 (5-10 words): the subject — what is this post about?
- Line 2 (5-10 words): the value — what is the key insight, result, or action?
- Do NOT mention the author's name
- Be specific ("LoRA Fine-tuning on Consumer GPUs" not "Machine Learning Tutorial")

Rules for subtopic:
- 2-4 words, title-case (e.g. "GPU Optimization", "Fine-tuning Techniques", "Agent Frameworks")
- If one of the existing subtopics fits well, return EXACTLY that name (same spelling/case)
- Only introduce a new subtopic name if none of the existing ones fit

Rules for summary:
- 3-5 sentences maximum
- Preserve specific facts: tool names, numbers, URLs/repos mentioned, key claims
- No emojis, no hashtags, no "Follow me for more" or other CTA noise
- Write in third person ("The author shares...", "This post introduces...")
"""

MERGE_SUBTOPICS_SYSTEM = """\
You are a taxonomy curator. You review lists of subtopic names and identify overlaps or redundancies.
Respond with valid JSON only."""

MERGE_SUBTOPICS_USER = """\
Topic: {topic_name}

Subtopics in use ({count} total):
{subtopic_list}

Identify any subtopics that are duplicates, near-synonyms, or should be merged.
Return JSON:
{{
  "merges": [
    {{"keep": "canonical name", "remove": ["alias1", "alias2"]}},
    ...
  ]
}}

Return an empty list if no merges are needed: {{"merges": []}}
Only suggest merges you are confident about. When in doubt, keep them separate.
"""
