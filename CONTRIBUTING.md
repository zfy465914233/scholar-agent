# Contributing to Scholar Agent

Thank you for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/zfy465914233/scholar-agent.git
cd scholar-agent
pip install -r requirements.txt
```

## Running Tests

```bash
python -m pytest tests/ -v
```

All tests run offline — no API keys or external services needed.

## Pull Requests

1. Fork the repo and create your branch from `main`
2. Add tests for new functionality
3. Ensure all tests pass before submitting
4. Write a clear PR description explaining what changed and why

## Code Style

- Use type hints (Python 3.10+ syntax: `str | None`, `list[str]`)
- Add docstrings to public functions
- Keep functions focused — one function, one responsibility

## Reporting Issues

Open an issue on GitHub with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Python version and OS
