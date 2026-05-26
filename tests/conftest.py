"""Shared test fixtures for scholar-agent."""

from pathlib import Path

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
    return ROOT / "schemas"
