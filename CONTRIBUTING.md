# Contributing to Scholar Agent

Thank you for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/zfy465914233/scholar-agent.git
cd scholar-agent
pip install -e .          # editable install with new CLI
scholar-agent config init # create user-level data dirs
```

## Project Structure

```
scholar-agent/
├── scholar_agent/        # CLI package (cross-platform setup, config, installers)
│   ├── cli.py            # argparse CLI entry point
│   ├── config/           # path resolution, config loading, user home init
│   ├── installers/       # MCP host registration (Claude Code, VS Code, OpenCode)
│   └── adapters/         # bridge to legacy mcp_server.py
├── scripts/              # core logic (BM25 index, arXiv search, scoring, etc.)
├── mcp_server.py         # MCP server exposing tools to Claude Code / VS Code
├── skills/               # (removed — functionality in scripts/academic/)
├── templates/            # config templates for project-local setup
├── schemas/              # JSON schemas (answer.schema.json)
└── tests/                # test suite
```

## Running Tests

```bash
python -m pytest tests/ -v
```

All tests run offline — no API keys or external services needed. 247 tests covering BM25 retrieval, academic scoring, MCP tools, and input validation.

## Testing Your Changes

```bash
# Verify CLI works
scholar-agent doctor
scholar-agent config show

# Verify MCP server starts
scholar-agent serve-mcp  # (Ctrl+C to stop)

# Run test suite
python -m pytest tests/ -v
```

## Pull Requests

1. Fork the repo and create your branch from `main`
2. Add tests for new functionality
3. Ensure all tests pass before submitting
4. Write a clear PR description explaining what changed and why

## Code Style

- Use type hints (Python 3.10+ syntax: `str | None`, `list[str]`)
- Add docstrings to public functions
- Keep functions focused — one function, one responsibility
- Run `scholar-agent doctor` to verify your setup is correct

## Reporting Issues

Open an issue on GitHub with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Python version and OS
- Output of `scholar-agent doctor` (if installed)
