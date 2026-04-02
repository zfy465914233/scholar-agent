# Lore — Domain Knowledge Agent with Local Retrieval

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![MCP Ready](https://img.shields.io/badge/MCP-Ready-brightgreen.svg)

A self-contained knowledge system that can be dropped into any project. Provides semantic search over a local knowledge base, web research via SearXNG, structured answer synthesis, and a knowledge improvement loop — all accessible to Claude Code and VS Code Copilot through MCP.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt          # core (zero external deps)
pip install fastmcp                      # for MCP server (optional)
pip install sentence-transformers        # for semantic retrieval (optional)

# 2. Build the knowledge index
python scripts/local_index.py --output indexes/local/index.json

# 3. (Optional) Start SearXNG for web research
docker compose up -d

# 4. (Optional) Build embedding index for semantic search
python scripts/local_index.py --output indexes/local/index.json --build-embedding-index
```

## MCP Integration

The optimizer exposes 3 tools to LLM agents:

| Tool | Description |
|------|-------------|
| `query_knowledge(query, limit?)` | Search local knowledge base |
| `save_research(query, answer_json)` | Save research results as knowledge card |
| `list_knowledge(topic?)` | Browse all knowledge cards |

### Claude Code

`.mcp.json` is already configured. Just `cd` into the optimizer directory and start Claude Code.

### VS Code Copilot

`.vscode/mcp.json` is already configured. Open the optimizer directory in VS Code, enable Copilot agent mode.

Both configs run the same `mcp_server.py` via `uv run --with fastmcp`.

## Project Structure

```
optimizer/
├── mcp_server.py              # MCP server (Claude Code + VS Code Copilot)
├── .mcp.json                  # Claude Code MCP config
├── .vscode/mcp.json           # VS Code Copilot MCP config
├── docker-compose.yml         # SearXNG for web research
├── requirements.txt           # Core dependencies
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
│   ├── retry.py               # Exponential backoff for external APIs
│   └── ...                    # Supporting scripts
├── knowledge/                 # Knowledge cards organized by topic
│   ├── templates/             # Card templates (definition, method, research-note, etc.)
│   ├── qpe/                   # Radar QPE domain
│   ├── markov_chain/          # Markov chain domain
│   └── ...                    # Add your own domain folders
├── indexes/                   # Generated (gitignored)
└── tests/                     # 78 tests
```

## Adding Knowledge

### Option A: Through MCP (recommended)

Ask your LLM agent to save research:

> "Search for recent advances in [topic], then save the findings."

The agent calls `save_research(query, answer_json)` which writes a knowledge card to `knowledge/<domain>/` and rebuilds the index.

### Option B: Manually

Create a Markdown file in `knowledge/<domain>/` following a template from `knowledge/templates/`. Then rebuild the index:

```bash
python scripts/local_index.py --output indexes/local/index.json
```

### Option C: Web Research Pipeline

```bash
# Research a topic via SearXNG + academic APIs
python scripts/research_harness.py "XGBoost for QPE" --depth medium --output /tmp/research.json

# Synthesize and save (requires LLM or --local-answer)
python scripts/close_knowledge_loop.py \
  --query "XGBoost for QPE" \
  --research /tmp/research.json \
  --answer /tmp/answer.json
```

## Key Design Decisions

- **Zero required external APIs** — BM25 retrieval works offline. SearXNG, embedding models, and LLM APIs are all optional.
- **Graceful degradation** — Every optional component (SearXNG, embeddings, LLM) falls back silently when unavailable.
- **Knowledge accumulates** — Every research session can produce a knowledge card that persists and improves future retrieval.
- **Answer schema enforced** — All answers conform to `schemas/answer.schema.json` with supporting claims, inferences, uncertainty, and action items.

## Running Tests

```bash
python -m pytest tests/ -v
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
