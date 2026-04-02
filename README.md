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
| **External deps** | Zero. BM25 runs offline, everything else is optional | Usually requires Pinecone/Weaviate/Chroma + OpenAI |
| **Knowledge lifecycle** | draft → reviewed → trusted → stale → deprecated, with dedup & governance | Add docs, search docs — no lifecycle |
| **Knowledge loop** | Research → distill → promote → reindex. The system gets smarter over time | One-way: ingest then retrieve |
| **MCP support** | Claude Code + VS Code Copilot out of the box | Usually one or none |
| **Answer structure** | Enforced JSON schema: claims, inferences, uncertainty, missing evidence | Raw text chunks |

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

Knowledge lives in **your project**, not inside lore-agent. After restarting Claude Code or VS Code, the AI will automatically discover and use `query_knowledge`, `save_research`, and `list_knowledge`.

## MCP Integration

Lore Agent exposes 3 tools to LLM agents:

| Tool | Description |
|------|-------------|
| `query_knowledge(query, limit?)` | Search local knowledge base |
| `save_research(query, answer_json)` | Save research results as a knowledge card |
| `list_knowledge(topic?)` | Browse all knowledge cards |

### Claude Code

`.mcp.json` is pre-configured. `cd` into the project and start Claude Code.

### VS Code Copilot

`.vscode/mcp.json` is pre-configured. Open the project in VS Code, enable Copilot agent mode.

Both configs run the same `mcp_server.py` via `uv run --with fastmcp`.

## How It Works

```
Query → Router (local-led or web-led)
         │                    │
         ▼                    ▼
   Local Retrieval      Web Research
   (BM25 + embed)      (SearXNG + APIs)
         │                    │
         └──────┬─────────────┘
                ▼
        Answer Synthesis
        (structured JSON schema)
                │
                ▼
        Knowledge Loop ──► distill → promote → reindex
```

1. **Router** classifies queries — definitions go local, fresh topics go web, complex ones mix both
2. **Retriever** uses BM25 (always) + optional semantic embeddings for hybrid search
3. **Synthesizer** produces structured answers with claims, inferences, uncertainty, and action items
4. **Knowledge Loop** saves research as Markdown cards, promotes drafts, and rebuilds the index — the system accumulates knowledge over time

## Project Structure

```
lore-agent/
├── mcp_server.py              # MCP server (Claude Code + VS Code Copilot)
├── .mcp.json                  # Claude Code MCP config
├── .vscode/mcp.json           # VS Code Copilot MCP config
├── docker-compose.yml         # SearXNG for web research
├── requirements.txt           # Core dependencies (zero external deps)
├── schemas/
│   ├── answer.schema.json     # Structured answer schema
│   └── evidence.schema.json   # Evidence schema
├── scripts/
│   ├── local_index.py         # Build BM25 index from knowledge cards
│   ├── local_retrieve.py      # Hybrid retrieval (BM25 + embedding)
│   ├── embedding_retrieve.py  # Semantic embedding (sentence-transformers)
│   ├── bm25.py                # Pure Python BM25 implementation
│   ├── research_harness.py    # Web research (SearXNG + OpenAlex + Semantic Scholar)
│   ├── close_knowledge_loop.py# Save research → knowledge card → reindex
│   ├── synthesize_answer.py   # Answer synthesis (LLM API or --local-answer)
│   ├── agent.py               # Agent control loop (Router/Researcher/Synthesizer/Curator)
│   ├── orchestrate_research.py# Query routing and evidence orchestration
│   └── retry.py               # Exponential backoff for external APIs
├── knowledge/                 # Knowledge cards organized by topic
│   ├── templates/             # Card templates (definition, method, research-note, etc.)
│   └── examples/              # Example cards to get started
├── indexes/                   # Generated (gitignored)
└── tests/                     # 74 tests, ~4s
```

## Adding Knowledge

### Option A: Through MCP (recommended)

Ask your LLM agent:

> "Search for recent advances in [topic], then save the findings."

The agent calls `save_research(query, answer_json)` which writes a knowledge card and rebuilds the index.

### Option B: Manually

Create a Markdown file in `knowledge/<domain>/` following a template from `knowledge/templates/`. Then rebuild the index:

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

## Running Tests

```bash
python -m pytest tests/ -v    # 74 tests, ~4s
```

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
