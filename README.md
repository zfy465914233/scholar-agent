# Scholar Agent

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![MCP Ready](https://img.shields.io/badge/MCP-Ready-brightgreen.svg)

[中文](README.zh-CN.md)

> General-purpose LLMs are often inaccurate and outdated in specialized domains. Scholar Agent combines **online research + local knowledge accumulation** into a sustainable knowledge flywheel, making your AI smarter in your domain over time. It also builds a human-readable knowledge base for quick learning. Integrates seamlessly with Claude Code and VS Code Copilot via MCP.

## What It Does

```
Your question
    │
    ▼
Online research (AI agent search + SearXNG + academic APIs)
    │
    ▼
Structured synthesis (with citations, confidence, uncertainty)
    │
    ▼
Local accumulation (Markdown knowledge cards + BM25 index)
    │
    ▼
Next question: AI checks local first ── hit? ──► use directly, fast & accurate
    │ miss
    ▼
Research again → accumulate → reindex ──► knowledge base keeps growing
```

Each round compounds. Knowledge cards have full lifecycle management: **draft → reviewed → trusted → stale → deprecated**.

## Academic Research Pipeline

Scholar Agent includes a comprehensive academic paper research pipeline:

- **Paper Search** — Search papers from arXiv, DBLP, and Semantic Scholar. Filter by top conferences (CVPR, ICCV, ECCV, ICLR, AAAI, NeurIPS, ICML, ACL, EMNLP, MICCAI)
- **Smart Scoring** — Four-dimensional scoring engine (relevance, recency, popularity, quality) ranks papers by your research interests
- **Deep Analysis Notes** — Auto-generate 20+ section Obsidian-style markdown notes with `<!-- LLM: -->` placeholders for AI-assisted completion
- **Figure Extraction** — Extract images from arXiv source archives and PDFs (via PyMuPDF)
- **Daily Recommendations** — Automated daily paper search, scoring, deduplication, and recommendation note generation
- **Paper → Knowledge Card** — Convert paper analyses into knowledge cards that feed back into the knowledge flywheel
- **Keyword Auto-Linking** — Scan notes for technical terms and create `[[wiki-links]]` automatically

## Quick Start

### Use as a standalone project

```bash
# Clone and install
git clone https://github.com/zfy465914233/scholar-agent.git
cd scholar-agent
pip install -r requirements.txt

# Build the knowledge index
python scripts/local_index.py --output indexes/local/index.json

# (Optional) Start SearXNG for web research
docker compose up -d
```

MCP configs are pre-configured:

- **Claude Code**: `.mcp.json` is ready. `cd` into the project and start Claude Code.
- **VS Code Copilot**: `.vscode/mcp.json` is ready. Open the project, enable agent mode.

### Embed into an existing project

```bash
cp -r scholar-agent/ your-project/scholar-agent/
cd your-project && python scholar-agent/setup_mcp.py
```

Auto-generates config. Knowledge lives in **your project**, not inside scholar-agent.

## MCP Tools

### Core Tools (always available)

| Tool | Description |
|------|-------------|
| `query_knowledge` | Search local knowledge base |
| `save_research` | Save structured research results as a knowledge card |
| `list_knowledge` | Browse all knowledge cards |
| `capture_answer` | Quick-capture a Q&A pair as a draft card |
| `ingest_source` | Ingest a URL or raw text into the knowledge base |
| `build_graph` | Generate an interactive knowledge graph (vis.js) |

### Academic Tools (set `LORE_ACADEMIC=1` to enable)

| Tool | Description |
|------|-------------|
| `search_papers` | Search arXiv + Semantic Scholar with 4-dim scoring |
| `search_conf_papers` | Search conference papers via DBLP + S2 enrichment |
| `analyze_paper` | Generate deep-analysis markdown notes (20+ sections) |
| `extract_paper_images` | Extract figures from arXiv source / PDF |
| `paper_to_card` | Convert paper analysis into a knowledge card |
| `daily_recommend` | Daily paper recommendation workflow |
| `link_paper_keywords` | Auto-link keywords as `[[wikilinks]]` in notes |

## Configuration

### .lore.json

The `.lore.json` file configures knowledge paths and academic research settings. See [`.lore.example.json`](.lore.example.json) for a full example with comments.

Key sections:
- `knowledge_dir` — Path to knowledge cards directory
- `index_path` — Path to BM25 search index
- `academic.research_interests` — Your research domains, keywords, and arXiv categories
- `academic.scoring` — Paper scoring weights and dimensions

### Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Required | Description |
|----------|----------|-------------|
| `LORE_ACADEMIC` | No | Set to `1` to enable academic tools |
| `S2_API_KEY` | No | Semantic Scholar API key ([get one free](https://api.semanticscholar.org/)) |
| `LLM_API_KEY` | No | LLM API key for advanced synthesis pipeline |
| `SEARXNG_BASE_URL` | No | SearXNG URL for web research (default: `http://localhost:8080`) |

## Project Structure

```
scholar-agent/
├── mcp_server.py              # MCP server (13 tools)
├── setup_mcp.py               # Embed into existing projects
├── pyproject.toml             # Package configuration
├── docker-compose.yml         # SearXNG
├── .lore.json                 # Project & academic configuration
├── schemas/                   # Answer + evidence JSON schemas
├── scripts/
│   ├── academic/              # Academic research modules
│   │   ├── arxiv_search.py    # arXiv + Semantic Scholar search
│   │   ├── conf_search.py     # Conference paper search (DBLP)
│   │   ├── paper_analyzer.py  # Deep-analysis note generation
│   │   ├── scoring.py         # 4-dim paper scoring engine
│   │   ├── image_extractor.py # Figure extraction from PDFs
│   │   ├── note_linker.py     # Wiki-link discovery + keyword linking
│   │   └── daily_workflow.py  # Daily recommendation pipeline
│   ├── lore_config.py         # Configuration reader
│   ├── local_index.py         # BM25 index builder
│   ├── local_retrieve.py      # Knowledge retrieval
│   ├── close_knowledge_loop.py # Knowledge card builder
│   └── ...                    # Research, synthesis, governance, graph
├── knowledge/                 # Knowledge cards (gitignored, user-generated)
├── indexes/                   # Generated indexes (gitignored)
└── tests/                     # 247 tests
```

## More Features

- **Multi-perspective research** — Parallel research from 5 perspectives (academic, technical, applied, contrarian, historical)
- **Obsidian compatible** — Standard Markdown + YAML frontmatter + `[[wiki-links]]`
- **Knowledge governance CLI** — Validate frontmatter, detect orphaned cards, find duplicates, manage lifecycle
- **Provider fault tolerance** — Each search source fails independently; falls back to local retrieval when offline

## Testing

```bash
python -m pytest tests/ -v
```

247 tests, ~13s. No external services needed.

## License

MIT — see [LICENSE](LICENSE).
