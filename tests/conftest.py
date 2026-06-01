"""Shared test fixtures for scholar-agent."""

import os
from pathlib import Path

# Force UTF-8 mode for all subprocess.run(text=True) calls on Windows (GBK locale).
# This propagates to child processes via the environment.
os.environ.setdefault("PYTHONUTF8", "1")

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src" / "scholar_agent" / "engine"


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def engine_dir() -> Path:
    return ENGINE


@pytest.fixture
def fixtures_dir() -> Path:
    return ROOT / "tests" / "fixtures"


@pytest.fixture
def schemas_dir() -> Path:
    return ROOT / "src" / "scholar_agent" / "schemas"
