# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `SCHOLAR_TOOLSET` now selects which tools the server exposes: unset / `default` / `all` = everything; otherwise a comma, space or `+` separated list of groups — `core` (knowledge read/write), `paper` (graph, PaperPulse import and the academic tools), `maintenance` (read-only governance scans). An unknown group aborts startup with the legal values.
- `query_knowledge` returns `knowledge_status` (`total_cards`, `draft_backlog`) computed from the already-loaded index; `lint_knowledge` returns `draft_backlog` as well. The count follows the card lifecycle state, so it drops as cards are promoted through `review_card`.
- Index documents carry `review_status` next to `confidence`. The index schema version is now 3, so an index built by an earlier version is rebuilt in full once on first use — incremental rebuilds only re-parse changed cards, and would otherwise keep counting already-reviewed cards as drafts.
- The Claude Code skill routes technical and research questions to `query_knowledge` first, and explains when to `save_research` and how `draft_backlog` invites a `review_card` pass.

### Changed

- Test suite isolated from the developer's real Scholar data (temporary `SCHOLAR_HOME` per test); a full run completes in seconds.
- README tool lists cover all 21 tools with one-line descriptions and the `SCHOLAR_TOOLSET` groups; CONTRIBUTING no longer hard-codes tool or test counts.

### Removed

- `requirements.txt` — dependencies are declared in `pyproject.toml` only.

### Fixed

- Corrected the 0.1.0 release year (2025 → 2026).

## [0.1.0] - 2026-05-28

### Added

- Knowledge flywheel MCP server with 6 core tools (query, save, list, capture, ingest, graph)
- Academic research pipeline with 8 tools (paper search, scoring, analysis, extraction, etc.)
- BM25-based local knowledge retrieval and indexing
- Multi-perspective research orchestration (academic, technical, applied, contrarian, historical)
- Obsidian-compatible markdown knowledge cards with YAML frontmatter and `[[wiki-links]]`
- Knowledge card lifecycle management (draft → reviewed → trusted → stale → deprecated)
- Conference paper search via DBLP + Semantic Scholar enrichment (CVPR, ICLR, NeurIPS, ICML, etc.)
- Four-dimensional paper scoring engine (relevance, recency, popularity, quality)
- Deep-analysis note generation with 20+ sections and LLM-assisted placeholder completion
- Daily paper recommendation workflow with dual-track mode
- Figure extraction from arXiv source archives and PDFs
- Automatic keyword linking via `[[wikilinks]]`
- Interactive knowledge graph visualization (vis.js)
- CLI with init, doctor, config, install, and serve-mcp commands
- MCP registration for Claude Code, VS Code Copilot, and OpenCode
- Global and project-local deployment modes
- Structured research output with JSON schema validation
- Quality gates for knowledge card creation
- Cross-platform support (macOS, Linux, Windows)
- 1121 tests with full offline coverage

[Unreleased]: https://github.com/zfy465914233/scholar-agent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/zfy465914233/scholar-agent/releases/tag/v0.1.0
