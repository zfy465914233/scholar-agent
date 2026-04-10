# Lore Agent

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![MCP Ready](https://img.shields.io/badge/MCP-Ready-brightgreen.svg)

> 为了解决通用模型在专业领域知识不够优/新的问题，通过在线研究补充 + 本地知识库沉淀实现知识治理，让 AI 在你的领域越用越强。通过 MCP 接入 Claude Code 与 VS Code Copilot。

A **zero-dependency, drop-in knowledge agent** that gives any project local retrieval, web research, structured answer synthesis, and a self-improving knowledge loop — all accessible to Claude Code and VS Code Copilot through MCP.

## Why Lore Agent?

| | Lore Agent | Typical RAG Tool |
|---|---|---|
| **Setup** | Drop in, `pip install -r requirements.txt`, done | Vector DB + embedding model + config |
| **External deps** | Minimal. BM25 + MCP server run offline | Usually requires Pinecone/Weaviate/Chroma + OpenAI |
| **Knowledge lifecycle** | draft → reviewed → trusted → stale → deprecated, with dedup & governance | Add docs, search docs — no lifecycle |
| **Knowledge loop** | Research → distill → promote → reindex. The system gets smarter over time | One-way: ingest then retrieve |
| **MCP support** | Claude Code + VS Code Copilot out of the box | Usually one or none |
| **Answer structure** | Enforced JSON schema: claims, inferences, uncertainty, missing evidence, visual aids | Raw text chunks |
| **Visual aids** | Auto-generated Mermaid diagrams + source page images captured and filtered | None |

## Quick Start

### As a standalone project

```bash
# 1. Clone and install
git clone https://github.com/zfy465914233/lore-agent.git
cd lore-agent
pip install -r requirements.txt

# 2. Build the knowledge index
python scripts/local_index.py --output indexes/local/index.json

# 3. (Optional) Start SearXNG for web research
docker compose up -d

# 4. (Optional) Add semantic retrieval
pip install sentence-transformers
python scripts/local_index.py --output indexes/local/index.json --build-embedding-index
```

### Embed into an existing project

```bash
# 1. Copy lore-agent into your project
cp -r lore-agent/ your-project/lore-agent/

# 2. Run the setup script (from your project root)
cd your-project
python lore-agent/setup_mcp.py
```

This automatically:
- Creates `.lore.json` config pointing knowledge to your project root
- Creates `knowledge/` and `indexes/` directories in your project
- Copies templates and example cards to get you started
- Injects MCP config into `.mcp.json` (Claude Code) and `.vscode/mcp.json` (VS Code Copilot)
- Adds a `CLAUDE.md` snippet instructing the AI to prioritize Lore tools

Knowledge lives in **your project**, not inside lore-agent. After restarting Claude Code or VS Code, the AI will automatically discover and use `query_knowledge`, `save_research`, `list_knowledge`, and `capture_answer`.

## MCP Integration

Lore Agent exposes 6 tools to LLM agents:

| Tool | Description |
|------|-------------|
| `query_knowledge(query, limit?)` | Search local knowledge base |
| `save_research(query, answer_json)` | Save research results as a knowledge card. Supports `visual_aids` (Mermaid diagrams, source images) |
| `list_knowledge(topic?)` | Browse all knowledge cards |
| `capture_answer(query, answer, tags?)` | Quick-capture a Q&A pair as a draft card with optional tags |
| `ingest_source(source, title?, tags?)` | Ingest a URL or raw text into the knowledge base |
| `build_graph()` | Generate an interactive knowledge graph HTML visualization |

### Claude Code

`.mcp.json` is pre-configured. `cd` into the project and start Claude Code.

### VS Code Copilot

`.vscode/mcp.json` is pre-configured. Open the project in VS Code, enable Copilot agent mode.

Both configs run the same `mcp_server.py` via `fastmcp` (installed with `pip install -r requirements.txt`).

When `setup_mcp.py` generates config for an embedded project, it prefers a real `fastmcp` executable from the active environment over `python -m fastmcp`, because some FastMCP versions do not expose `fastmcp.__main__`.

## How It Works

```
Query → Router (local-led / web-led / mixed / context-led)
         │                    │
         ▼                    ▼
   Local Retrieval      Web Research
   (BM25 + embed)      (SearXNG + APIs, concurrent fetch)
         │                    │
         └──────┬─────────────┘
                ▼
        Evidence Sufficiency Check ── insufficient? ──► refine query, retry
                │ sufficient
                ▼
        Answer Synthesis
        (structured JSON, claim-evidence ID validation)
                │
                ▼
        Knowledge Loop ──► distill → promote → incremental reindex
```

1. **Router** classifies queries — definitions go local, fresh topics go web, complex ones mix both, code/debug goes context-led
2. **Researcher** gathers evidence with multi-query expansion (depth-aware), concurrent URL fetching, and BM25 + optional semantic embeddings for hybrid search
3. **Synthesizer** produces structured answers with claims, inferences, uncertainty, and action items. Claims are validated against actual evidence IDs
4. **Visual Aids** — the system auto-judges when visuals improve understanding: Mermaid diagrams for processes/architectures/comparisons, and source page images (charts, figures) are captured and filtered from research evidence
5. **Knowledge Loop** saves research as Markdown cards with embedded visuals, promotes drafts, and incrementally rebuilds the index — the system accumulates knowledge over time
6. **Knowledge Graph** — cards can link each other via `[[card-id]]` wiki-links; the index automatically computes backlinks, enabling graph-aware retrieval. `build_graph` generates an interactive vis.js visualization
7. **Entity Extraction** — auto-extracts named concepts from card text and generates wiki-link cross-references
8. **Contradiction Detection** — when saving cards, BM25-retrieves similar existing cards and flags potential overlaps/duplicates
9. **Multi-Perspective Research** — parallel research from academic, technical, applied, contrarian, and historical perspectives for deeper coverage
10. **Retry** — if evidence is insufficient, the agent refines the query and loops back (configurable `max_retries`)

## Search Boundary

Lore Agent treats search as a two-layer system:

- **Lore-internal programmable providers** handle sources Lore can call directly, such as `SearXNG`, `OpenAlex`, and `Semantic Scholar`.
- **Host-provided search** stays outside Lore. A main agent can launch a host-side search subagent, collect results, and pass them into Lore as an `ExternalCandidateBatch`.

Lore does **not** assume Claude Code WebSearch or VS Code Copilot Search is callable from inside `research_harness.py`. Those results should be injected from the host layer, then merged with Lore's own provider output inside the shared evidence pipeline.

```text
Host Agent
  ├─ query_knowledge
  ├─ run host search in subagent
  ├─ emit ExternalCandidateBatch
  └─ call Lore pipeline
         ├─ internal providers
         ├─ merge + dedupe
         └─ normalize to evidence
```

## Project Structure

### Standalone mode

```
lore-agent/
├── mcp_server.py              # MCP server (Claude Code + VS Code Copilot)
├── setup_mcp.py               # Setup script for embedding into other projects
├── docker-compose.yml         # SearXNG for web research
├── requirements.txt           # Core dependencies (zero external deps)
├── schemas/
│   ├── answer.schema.json     # Structured answer schema
│   └── evidence.schema.json   # Evidence schema
├── scripts/
│   ├── lore_config.py         # Shared config reader (.lore.json)
│   ├── local_index.py         # Build BM25 index from knowledge cards
│   ├── local_retrieve.py      # Hybrid retrieval (BM25 + embedding)
│   ├── bm25.py                # Pure Python BM25 implementation
│   ├── research_harness.py    # Web research (SearXNG + OpenAlex + Semantic Scholar)
│   ├── search_pipeline.py     # Merge/dedupe pipeline for internal + external candidates
│   ├── inputs/                # ExternalCandidateBatch input contract
│   ├── normalizers/           # Candidate -> evidence normalization
│   ├── search_providers/      # Lore-internal programmable search providers
│   ├── close_knowledge_loop.py# Save research → knowledge card → reindex
│   ├── synthesize_answer.py   # Answer synthesis (LLM API or --local-answer)
│   ├── agent.py               # Agent state machine (Router → Researcher → Synthesizer → Curator)
│   ├── orchestrate_research.py# Query routing and evidence orchestration
│   ├── exceptions.py          # Unified exception hierarchy
│   ├── knowledge_governance.py # Validate, lint, scan, lifecycle CLI
│   ├── build_graph.py         # Interactive knowledge graph (vis.js)
│   ├── common.py              # Shared utilities (frontmatter, slug, JSON, wiki-links, entity extraction)
│   ├── cache_helper.py        # URL cache with TTL + LRU eviction
│   └── retry.py               # Exponential backoff for external APIs
├── changelog.md               # Auto-recorded change log
├── knowledge/                 # Your project's knowledge (follows the project)
│   └── templates/             # Card templates (optional)
├── indexes/                   # Generated (gitignored)
└── tests/                     # 189 tests, ~5s
```

### Embedded mode (after `setup_mcp.py`)

```
your-project/
├── .lore.json                 # Config: paths to knowledge and indexes
├── knowledge/                 # Your project's knowledge (empty at first)
├── indexes/                   # Generated (gitignored)
├── lore-agent/                # Engine only — can be gitignored
│   ├── scripts/
│   ├── mcp_server.py
│   └── ...
└── CLAUDE.md                  # Auto-generated AI instructions
```

## Adding Knowledge

### Option A: Through MCP (recommended)

Ask your LLM agent:

> "Search for recent advances in [topic], then save the findings."

The agent calls `save_research(query, answer_json)` which writes a knowledge card and rebuilds the index.

### Option B: Manually

Create a Markdown file in `knowledge/<domain>/` following a template from `lore-agent/templates/`. Then rebuild the index:

```bash
python scripts/local_index.py --output indexes/local/index.json
```

### Option C: Web Research Pipeline

```bash
# Research a topic via SearXNG + academic APIs
python scripts/research_harness.py "your topic" --depth medium --output /tmp/research.json

# Synthesize and save
python scripts/close_knowledge_loop.py \
  --query "your topic" \
  --research /tmp/research.json \
  --answer /tmp/answer.json
```

## Knowledge Governance

A CLI tool (`scripts/knowledge_governance.py`) for maintaining knowledge quality:

```bash
python scripts/knowledge_governance.py validate      # frontmatter schema check
python scripts/knowledge_governance.py lint           # orphan / broken-link / stale detection
python scripts/knowledge_governance.py duplicates     # find near-duplicate cards
python scripts/knowledge_governance.py scan           # status / type / topic summary
python scripts/knowledge_governance.py transition --card-id <id> --state reviewed
```

Changes to cards are auto-recorded in `changelog.md` (project root).

## Agent Compatibility

Lore Agent ships instruction files for major LLM coding agents:

| Agent | File | Auto-loaded |
|-------|------|-------------|
| Claude Code | `CLAUDE.md` | ✅ |
| VS Code Copilot | `.github/copilot-instructions.md` | ✅ |
| Codex / OpenCode | `AGENTS.md` | ✅ |
| Gemini CLI | `GEMINI.md` | ✅ |
| Cursor | `.cursor/rules/lore-agent.mdc` | ✅ |
| Windsurf | `.windsurf/rules/lore-agent.md` | ✅ |

## Running Tests

```bash
python -m pytest tests/ -v    # 189 tests, ~5s
```

The close-loop tests use a temporary knowledge tree and temporary index output, so they do not rewrite the active project index even in embedded mode.

## Benchmark

Built-in eval harness with 8 benchmark cases across 4 query categories.

```bash
python scripts/run_eval.py --dry-run
```

| Metric | Score |
|---|---|
| **Route accuracy** | 100% (8/8) |
| **Retrieval hit rate** | 100% (8/8) |
| **Min citations met** | 100% (8/8) |
| **Errors** | 0 |

Breakdown by category:

| Category | Cases | Route correct | Retrieval hit |
|---|---|---|---|
| Definition (local-led) | 3 | 3/3 | 3/3 |
| Derivation (mixed) | 2 | 2/2 | 2/2 |
| Freshness (web-led) | 2 | 2/2 | 2/2 |
| Comparison (mixed) | 1 | 1/1 | 1/1 |

> Note: Dry-run mode skips LLM calls. `answer_present_rate` is 0% in dry-run since no LLM generates answers. With a live LLM, answer quality is additionally evaluated.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
