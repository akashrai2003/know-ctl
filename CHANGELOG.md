# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Evidence-backed AI briefings synthesized from the original post, linked articles, useful comments, and comment-shared resources.
- Hybrid comment usefulness ranking with deterministic filtering, local-model review, and insight, question, resource, or noise labels.
- Freshness hashes and automatic invalidation when briefing evidence changes.
- `sg insights`, `sg rank-comments`, and targeted `sg brief <urn>` commands.
- Dashboard briefing coverage, community-intelligence metrics, structured briefing views, and one-click regeneration.
- MCP `get_briefing` tool for structured AI-agent retrieval.
- Local-only, batched briefing generation with `sg insights --provider local` or `sg run --insights-provider local`.
- A newest-first, date-grouped Obsidian post timeline and clickable topic-to-subtopic navigation.
- Safe force-reclassification and force-subtopic CLI modes with resumable local-model batches.

### Fixed
- Comment-scrape failures remain retryable instead of being recorded as successful empty threads.
- Forced comment refreshes no longer delete existing comments before a replacement scrape succeeds.
- Web pipeline result serialization now handles stage outputs correctly.
- Groq-only installations can run batch-shaped small-model tasks when no local server is configured.
- Primary topics now preserve model priority instead of using alphabetical tie-breaking; agent mentions no longer override central inference, GPU, CUDA, optimization, or reinforcement-learning subjects.
- Force-reclassification removes stale taxonomy and graph edges only after a valid replacement is available.

## [0.1.0] - 2026-06-16

### Added
- **Core Pipeline**: Ingest posts from exported JSON files or live LinkedIn scraping.
- **LLM Enrichment**: Automatically enrich posts by retrieving external URL contents and comments, using LLM routing (vLLM and Groq API).
- **Taxonomy & Graph Builder**: Classify posts into topics and build semantic nodes/edges to construct an interactive knowledge base.
- **Obsidian Vault Writer**: Generate a structured Obsidian vault with links between posts, authors, and topics.
- **Web Dashboard**: Modern web interface showing graph visualization, search, pipeline statistics, and post lists.
- **CLI Subcommands**: Fully modularized and type-annotated CLI subcommands (`sg init`, `sg run`, `sg status`, `sg graph`, `sg schedule`).
- **CI/CD & Pre-commit**: Configured GitHub Actions CI pipeline and pre-commit hooks for code quality.
