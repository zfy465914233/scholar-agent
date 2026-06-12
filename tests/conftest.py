"""Shared test fixtures for scholar-agent."""

import os
import subprocess
from pathlib import Path

# Force UTF-8 mode for all subprocess.run(text=True) calls on Windows (GBK locale).
# This propagates to child processes via the environment.
os.environ.setdefault("PYTHONUTF8", "1")

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src" / "scholar_agent" / "engine"

# Monkey-patch subprocess.run to inject a default timeout, preventing test
# suite hangs when a child process deadlocks.  Individual calls can still
# override by passing their own timeout=.
_original_run = subprocess.run


def _run_with_default_timeout(*args, **kwargs):
    kwargs.setdefault("timeout", 60)
    return _original_run(*args, **kwargs)


subprocess.run = _run_with_default_timeout


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
