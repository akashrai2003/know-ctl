"""Prompt templates for LLM tasks."""

from __future__ import annotations

CLASSIFY_POST_TOPICS_SYSTEM = """\
You are a topic classifier for a professional AI/tech knowledge base.
You receive the post, any linked article, and notable discussion comments.
Assign topics using the full context, not just the post's first paragraph.
Respond with valid JSON only. No explanation."""

CLASSIFY_POST_TOPICS_USER = """\
Available topics (use ONLY these exact names in your response):
{topics}

Context:
{content}

Respond with JSON:
{{
  "topics": ["Topic1", "Topic2"],
  "confidence": 0.85
}}

Rules:
- Assign 1-3 topics max
- Use ONLY the exact topic names from the list above (do not include descriptions)
- Weigh the linked article and technical comments as much as the post text
- confidence: 0.0–1.0 reflecting how clearly the material fits the chosen topics
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

RANK_COMMENT_SYSTEM = """\
You classify LinkedIn comments for a technical knowledge base.
Judge whether the comment adds information beyond the original post. Applause, repetition,
generic agreement, and product pitches are noise. Concrete experience, facts, tradeoffs,
technical questions, and useful documentation/code links are valuable.
Respond with valid JSON only."""

RANK_COMMENT_USER = """\
ORIGINAL POST:
{post}

COMMENT:
{comment}

Return JSON:
{{
  "kind": "insight|question|resource|noise",
  "usefulness_score": 0.0
}}

The score is 0.0-1.0. Use resource only for a genuinely useful paper, documentation,
repository, benchmark, or technical article. Marketing links are noise.
"""

GENERATE_POST_TITLE_SUBTOPIC_SYSTEM = """\
You are a knowledge organizer for a professional AI/tech knowledge base.
You receive the post plus any linked article and notable comments.
For each item generate:
1. A two-line title capturing the subject and the key insight (including article/thread if richer).
2. A subtopic name (2-4 words, title-case) that groups this post within its parent topic.
3. A 3-5 sentence summary of the idea — not a paraphrase of the first paragraph only.

Respond with valid JSON only. No explanation."""

GENERATE_POST_TITLE_SUBTOPIC_USER = """\
Parent topic: {topic_name}

Existing subtopics (prefer these if a good match exists):
{existing_subtopics}

Context:
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

SYNTHESIZE_INSIGHTS_SYSTEM = """\
You are a senior AI engineer writing a knowledge briefing from a LinkedIn post.
The post is only the entry point. Your job is to understand the idea using:
- the post
- the linked article (if present)
- high-signal comments (claims, numbers, tools, questions — ignore applause and product pitches)

Write as if the reader will never open LinkedIn. Extract knowledge, not a recap.
Respond with valid JSON only."""

SYNTHESIZE_INSIGHTS_USER = """\
Author: {author}
Title: {title}

POST:
{post}

LINKED ARTICLES:
{articles}

USEFUL COMMENTS (already filtered; treat these as primary sources):
{comments}

COMMENT-SHARED RESOURCES:
{comment_links}

Return JSON:
{{
  "thesis": "2-4 sentences. The actual idea, combining post + article + comments. Include specific numbers, tools, and thresholds. Do not paraphrase the post if the article or comments add more.",
  "article_takeaways": ["concrete claims, techniques, or numbers from the linked article only"],
  "community_insights": [
    {{
      "author": "commenter name",
      "claim": "the new information they added",
      "why_it_matters": "one sentence on why a practitioner should care"
    }}
  ],
  "resources": [
    {{
      "title": "resource title",
      "url": "https://...",
      "value": "why this link is worth opening"
    }}
  ],
  "open_questions": ["unresolved technical questions from the thread"]
}}

Rules:
- Prefer specific facts (50M tokens/day, 70B on 24GB, INT8 KV cache) over vague praise.
- Drop marketing, CTAs, and "great share" even if they slipped in.
- article_takeaways must come from the article text, not the post, and may be [].
- community_insights must add something the post did not already say, and may be [].
- resources should include the main article and any GitHub/docs/papers from comments.
- Never invent URLs or numbers that are not in the sources.
"""
