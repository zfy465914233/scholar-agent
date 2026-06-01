# Contributing to Scholar Agent

Thank you for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/zfy465914233/scholar-agent.git
cd scholar-agent
pip install -e ".[dev]"
pre-commit install
scholar-agent config init
```

## Project Structure

```
scholar-agent/
├── src/scholar_agent/
│   ├── __init__.py
│   ├── server.py              # MCP server (14 tools)
│   ├── cli.py                 # CLI entry point (scholar-agent command)
│   ├── engine/                # Core business logic
│   │   ├── academic/          # Academic research modules
│   │   │   ├── arxiv_search.py    # arXiv + Semantic Scholar search
│   │   │   ├── conf_search.py     # Conference paper search (DBLP)
│   │   │   ├── paper_analyzer.py  # Deep-analysis note generation
│   │   │   ├── scoring.py         # 4-dim paper scoring engine
│   │   │   ├── image_extractor.py # Figure extraction from PDFs
│   │   │   ├── note_linker.py     # Wiki-link discovery + keyword linking
│   │   │   └── daily_workflow.py  # Daily recommendation pipeline
│   │   ├── search_providers/  # Pluggable search backends
│   │   ├── local_index.py     # BM25 index builder
│   │   ├── local_retrieve.py  # Knowledge retrieval
│   │   └── ...                # Research, synthesis, governance, graph
│   ├── schemas/               # JSON schemas + routing policy
│   ├── templates/             # Paper analysis templates (zh/en)
│   ├── config_data/           # Default configuration files
│   ├── config/                # Config loading, paths, profiles
│   ├── installers/            # MCP registration for Claude/VSCode/OpenCode
│   ├── skills/                # Claude Code skill definition
│   └── validation/            # Note validation + normalization
└── tests/                     # Test suite
```

## Running Tests

```bash
python -m pytest tests/ -v
```

All tests run offline — no API keys or external services needed. 276 tests covering BM25 retrieval, academic scoring, MCP tools, and input validation.

## Code Quality

```bash
# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/

# Type check
mypy src/scholar_agent/

# All checks at once
make lint
```

## Testing Your Changes

```bash
# Verify CLI works
scholar-agent doctor

# Verify MCP server starts
scholar-agent serve-mcp  # (Ctrl+C to stop)

# Run test suite
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=scholar_agent --cov-report=term-missing
```

## Pull Requests

1. Fork the repo and create your branch from `main`
2. Add tests for new functionality
3. Ensure all tests pass and linting is clean
4. Write a clear PR description explaining what changed and why
5. Keep PRs focused — one logical change per PR

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add paper citation graph tool
fix: preserve Chinese characters in BM25 index
docs: update installation instructions
refactor: extract scoring logic into separate module
test: add edge cases for knowledge lifecycle
```

## Code Style

- Use type hints (Python 3.10+ syntax: `str | None`, `list[str]`)
- Add docstrings to public functions
- Keep functions focused — one function, one responsibility
- Run `ruff check` before committing
- Run `scholar-agent doctor` to verify your setup is correct

## Reporting Issues

Open an issue on GitHub with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Python version and OS
- Output of `scholar-agent doctor` (if installed)
