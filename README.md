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
Online research (LLM web search + academic APIs)
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

### Step 1: Install

```bash
git clone https://github.com/zfy465914233/scholar-agent.git
cd scholar-agent
pip install -e .
```

### Step 2: Choose Your Mode

#### Mode A: Global (Recommended)

One knowledge base shared across all projects. Data stored at `~/scholar/`.

```bash
scholar-agent init
```

This registers MCP in `~/.claude.json` (user-level), making Scholar Agent available in **every project**.

#### Mode B: Project-Local

Each project gets its own isolated knowledge base inside the project directory. Knowledge cards can be version-controlled alongside your code.

```bash
cd my-project
SCHOLAR_HOME=$(pwd)/scholar scholar-agent init    # macOS / Linux

# Windows (PowerShell)
# $env:SCHOLAR_HOME = "$PWD\scholar"
# scholar-agent init
```

Data stored in `my-project/scholar/`. MCP registered in `my-project/.mcp.json` (project-level), available **only in that project**.

Add `scholar/` to `.gitignore` if you don't want knowledge cards in version control, or commit them to share with your team.

#### Mode C: Developer / Contributor

```bash
git clone https://github.com/zfy465914233/scholar-agent.git
cd scholar-agent
pip install -e .
scholar-agent config init
python -m pytest tests/ -v
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `scholar-agent init` | One-command setup: data dirs + config + MCP registration |
| `scholar-agent serve-mcp` | Start the MCP server (used by Claude Code internally) |
| `scholar-agent doctor` | Show environment and config diagnostics |
| `scholar-agent config show` | Show resolved configuration |
| `scholar-agent config init` | Create user-level data dirs and config |
| `scholar-agent config migrate --to user-home` | Migrate data from old directory layout |
| `scholar-agent install claude --write` | Register MCP with Claude Code |
| `scholar-agent install vscode --write` | Register MCP with VS Code Copilot |
| `scholar-agent install opencode --write` | Register MCP with OpenCode |
| `scholar-agent install claude --status` | Check if MCP is registered with Claude Code |
| `scholar-agent install claude --uninstall` | Remove MCP registration from Claude Code |

## Data Directory

| Mode | Default Path |
|------|-------------|
| Global | `~/scholar/` |
| Project-Local | `my-project/scholar/` |

Override with the `SCHOLAR_HOME` environment variable.

```
Directory structure after init:
  scholar/
  ├── config/         # Configuration files
  ├── knowledge/      # Knowledge cards
  ├── paper-notes/    # Paper analysis notes
  ├── daily-notes/    # Daily paper recommendations
  ├── indexes/        # BM25 search index
  ├── cache/          # Cached data
  └── outputs/        # Generated outputs
```

## System Dependencies

| Dependency | macOS | Ubuntu / Debian | Windows |
|-----------|-------|----------------|---------|
| Python 3.10+ | `brew install python` | `sudo apt install python3` | [python.org](https://www.python.org/downloads/) |

PDF text and image extraction is handled by PyMuPDF (`pip install -e .` installs it automatically).

## Recommended Workflow

For best analysis quality, follow this order:

1. **Download the paper**: `download_paper("2510.24701", title="Paper Title", domain="LLM")`
2. **Extract images**: `extract_paper_images("2510.24701")` (auto-detects local PDF)
3. **Deep analysis**: `analyze_paper(paper_json)` (auto-detects local PDF, extracts full text)

> **Tip**: Downloading the PDF before analysis enables full-text extraction, producing high-quality notes with specific data, formulas, and experimental results. Without a local PDF, analysis relies on the abstract only.

## MCP Tools

### Core Tools (always available)

| Tool | Description |
|------|-------------|
| `query_knowledge` | Search local knowledge base |
| `save_research` | Save structured research results as a knowledge card (supports Mermaid diagrams, source images) |
| `list_knowledge` | Browse all knowledge cards |
| `capture_answer` | Quick-capture a Q&A pair as a draft card |
| `ingest_source` | Ingest a URL or raw text into the knowledge base |
| `build_graph` | Generate an interactive knowledge graph (vis.js) |

### Academic Tools (set `SCHOLAR_ACADEMIC=1` to enable)

| Tool | Description |
|------|-------------|
| `search_papers` | Search arXiv + Semantic Scholar with 4-dim scoring |
| `search_conf_papers` | Search conference papers via DBLP + S2 enrichment |
| `download_paper` | Download a paper PDF to local storage |
| `analyze_paper` | Generate deep-analysis markdown notes (20+ sections) |
| `extract_paper_images` | Extract figures from arXiv source / PDF |
| `paper_to_card` | Convert paper analysis into a knowledge card |
| `daily_recommend` | Daily paper recommendation workflow |
| `link_paper_keywords` | Auto-link keywords as `[[wikilinks]]` in notes |

## Configuration

### .scholar.json

The `.scholar.json` file configures knowledge paths and academic research settings. See [`.scholar.example.json`](.scholar.example.json) for a full example with comments.

Key sections:
- `knowledge_dir` — Path to knowledge cards directory
- `index_path` — Path to BM25 search index
- `academic.research_interests` — Your research domains, keywords, and arXiv categories
- `academic.scoring` — Paper scoring weights and dimensions

### Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Required | Description |
|----------|----------|-------------|
| `SCHOLAR_ACADEMIC` | No | Set to `1` to enable academic tools |
| `SCHOLAR_HOME` | No | Override data directory (default: `~/scholar/`) |
| `S2_API_KEY` | No | Semantic Scholar API key ([get one free](https://api.semanticscholar.org/)) |
| `LLM_API_KEY` | No | LLM API key for advanced synthesis pipeline |

## Project Structure

```
scholar-agent/
├── mcp_server.py              # MCP server (14 tools)
├── setup_mcp.py               # Embed into existing projects
├── pyproject.toml             # Package configuration
├── .scholar.example.json      # Example config with comments
├── schemas/                   # Answer + evidence JSON schemas
├── templates/                 # Config & MCP templates for setup
├── skills/                    # Claude Code slash-command skills
├── scholar_agent/             # Python package (CLI, installers, config)
│   ├── cli.py                 # CLI entry points
│   ├── installers/            # MCP registration for Claude/VSCode/OpenCode
│   └── config/                # Config loading, paths, profiles
├── scripts/
│   ├── academic/              # Academic research modules
│   │   ├── arxiv_search.py    # arXiv + Semantic Scholar search
│   │   ├── conf_search.py     # Conference paper search (DBLP)
│   │   ├── paper_analyzer.py  # Deep-analysis note generation
│   │   ├── scoring.py         # 4-dim paper scoring engine
│   │   ├── image_extractor.py # Figure extraction from PDFs
│   │   ├── note_linker.py     # Wiki-link discovery + keyword linking
│   │   └── daily_workflow.py  # Daily recommendation pipeline
│   ├── scholar_config.py       # Configuration reader
│   ├── local_index.py         # BM25 index builder
│   ├── local_retrieve.py      # Knowledge retrieval
│   ├── close_knowledge_loop.py # Knowledge card builder + quality gates
│   └── ...                    # Research, synthesis, governance, graph
└── tests/                     # 266 tests
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

266 tests, ~6s. No external services needed.

## License

MIT — see [LICENSE](LICENSE).
