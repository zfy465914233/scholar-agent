# Promotion Posts

## Reddit / Hacker News

**Title**: Show HN: Scholar Agent – An MCP server that makes AI smarter in YOUR domain, every query compounds

**Body**:

> Most LLM sessions are stateless — you ask, it answers, and next time you start from zero. Scholar Agent fixes this by building a local knowledge flywheel that compounds over time.

Here's what happens:

1. You ask a question in Claude Code or VS Code Copilot
2. Scholar Agent researches across the web, arXiv, DBLP, and Semantic Scholar
3. It saves a structured knowledge card (Markdown, Obsidian-compatible, with citations and confidence scores)
4. Next time you ask something similar — it hits the local BM25 index first. <0.1s, no API call, accurate.

Every round makes the next one better. After 50 questions in your domain, you have a curated, indexed knowledge base that your AI can retrieve from instantly.

**What's included:**

- 14 MCP tools (search, score, analyze papers, extract figures, daily recommendations...)
- Academic pipeline: arXiv + Semantic Scholar search with a 4-dim scoring engine (relevance, recency, popularity, quality)
- Deep paper analysis: auto-generates 20+ section Obsidian-style notes
- Knowledge lifecycle: draft → reviewed → trusted → stale → deprecated
- Works offline — local BM25 index, graceful fallback
- Cross-platform: macOS, Linux, Windows

**Install:**

```
pip install py-scholar-agent
scholar-agent init
```

That's it. One command creates data dirs, writes config, and registers MCP.

**Tech details:** Python 3.10+, MIT license, 276 tests, ruff + mypy enforced, CI on 4 OS × 4 Python versions.

GitHub: https://github.com/zfy465914233/scholar-agent

Happy to answer questions or take feature requests.

---

## Twitter / X

Most AI sessions are stateless — every chat starts from zero.

I built Scholar Agent: an MCP server that builds a knowledge flywheel for your domain. Every query compounds.

Ask → Research (web + arXiv) → Save structured knowledge card → Next question hits local cache in <0.1s

After 50 questions, your AI has a curated knowledge base it can retrieve from instantly. No API calls. Works offline.

Features:
- 14 MCP tools for Claude Code & VS Code
- Academic pipeline: arXiv/DBLP/S2 search + 4-dim scoring + deep analysis
- Obsidian-compatible Markdown + wiki-links
- Knowledge lifecycle management

Install in one line:
pip install py-scholar-agent && scholar-agent init

Open source, MIT: github.com/zfy465914233/scholar-agent
