"""Shared test fixtures for scholar-agent."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# Force UTF-8 mode for all subprocess.run(text=True) calls on Windows (GBK locale).
# This propagates to child processes via the environment.
os.environ.setdefault("PYTHONUTF8", "1")

import pytest

from scholar_agent.engine import scholar_config

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

# ── Isolation from the developer's real Scholar data ────────────────
# Every user-state path (config, metrics.json, usage.json, synonyms.json and,
# through build_default_config, knowledge_dir / index_path / paper_notes_dir /
# daily_notes_dir) is derived from SCHOLAR_HOME — except that scholar_config
# caches the resolved config for the whole process.  So the suite needs both:
#   1. a session-level SCHOLAR_HOME, set at import time and overriding whatever
#      the shell had, so nothing that runs outside a test (module import during
#      collection, threads a test leaves behind) can reach ~/.scholar or
#      ~/scholar;
#   2. a per-test SCHOLAR_HOME under tmp_path (children inherit it) plus an
#      empty config cache, so no test inherits — or leaves behind — a config
#      resolved under another SCHOLAR_HOME.
# Tests that need a specific config set ``scholar_config._config_cache`` in
# ``setUp`` (a module-level assignment is wiped by the fixture).
_SESSION_SCHOLAR_HOME = tempfile.mkdtemp(prefix="scholar-agent-tests-")
os.environ["SCHOLAR_HOME"] = _SESSION_SCHOLAR_HOME
for _var in ("SCHOLAR_CONFIG", "SCHOLAR_PROFILE"):
    os.environ.pop(_var, None)


def pytest_sessionfinish(session, exitstatus) -> None:
    shutil.rmtree(_SESSION_SCHOLAR_HOME, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_scholar_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point SCHOLAR_HOME at a fresh tmp dir and start with an empty config cache."""
    home = tmp_path / "scholar-home"
    home.mkdir()
    monkeypatch.setenv("SCHOLAR_HOME", str(home))
    for var in ("SCHOLAR_CONFIG", "SCHOLAR_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    scholar_config.clear_cache()


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
