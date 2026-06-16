# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-16

### Added
- **Core Pipeline**: Ingest posts from exported JSON files or live LinkedIn scraping.
- **LLM Enrichment**: Automatically enrich posts by retrieving external URL contents and comments, using LLM routing (vLLM and Groq API).
- **Taxonomy & Graph Builder**: Classify posts into topics and build semantic nodes/edges to construct an interactive knowledge base.
- **Obsidian Vault Writer**: Generate a structured Obsidian vault with links between posts, authors, and topics.
- **Web Dashboard**: Modern web interface showing graph visualization, search, pipeline statistics, and post lists.
- **CLI Subcommands**: Fully modularized and type-annotated CLI subcommands (`sg init`, `sg run`, `sg status`, `sg graph`, `sg schedule`).
- **CI/CD & Pre-commit**: Configured GitHub Actions CI pipeline and pre-commit hooks for code quality.
