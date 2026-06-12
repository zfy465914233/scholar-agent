"""Shared configuration reader for Scholar Agent.

Thin facade over ``config.loader.resolve_config()`` that provides a
process-wide cache.  All runtime code should use this module for
configuration access; the ``config/`` package handles actual discovery
and merging.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scholar_agent.config.loader import ConfigResolution

logger = logging.getLogger(__name__)

# ── Process-wide cache ──────────────────────────────────────────────
# ``_config_cache`` is set directly by tests; ``_resolution_cache``
# stores the full ``ConfigResolution`` for diagnostic access.
_config_lock = threading.RLock()
_config_cache: dict | None = None
_resolution_cache: ConfigResolution | None = None


def _get_resolution() -> ConfigResolution:
    """Return the cached ``ConfigResolution``, resolving it on first call."""
    global _resolution_cache
    with _config_lock:
        if _resolution_cache is None:
            from scholar_agent.config.loader import resolve_config

            _resolution_cache = resolve_config()
        return _resolution_cache


def load_config() -> dict:
    """Load and return the merged configuration.

    Uses ``config.loader.resolve_config()`` as the single source of truth.
    The result is cached for the process lifetime; call :func:`clear_cache`
    to force a re-read (e.g. after writing a new config file).
    """
    global _config_cache
    with _config_lock:
        if _config_cache is not None:
            return _config_cache
        _config_cache = _get_resolution().config
        return _config_cache


# ── Path getters ────────────────────────────────────────────────────


def get_knowledge_dir() -> Path:
    return Path(load_config()["knowledge_dir"])


def get_index_path() -> Path:
    return Path(load_config()["index_path"])


def get_scholar_dir() -> Path:
    return Path(load_config()["scholar_dir"])


def get_paper_notes_dir() -> Path:
    """Return the configured paper-notes directory.

    Reads ``academic.paper_notes_dir`` from config.  Falls back to a
    ``paper-notes`` sibling of ``knowledge_dir`` when the key is absent.
    """
    config = load_config()
    configured = config.get("academic", {}).get("paper_notes_dir")
    if configured:
        return Path(configured)
    return Path(config["knowledge_dir"]).parent / "paper-notes"


def get_daily_notes_dir() -> Path:
    """Return the configured daily-notes directory.

    Reads ``academic.daily_notes_dir`` from config.  Falls back to a
    ``daily-notes`` sibling of ``knowledge_dir`` when the key is absent.
    """
    config = load_config()
    configured = config.get("academic", {}).get("daily_notes_dir")
    if configured:
        return Path(configured)
    return Path(config["knowledge_dir"]).parent / "daily-notes"


def get_paper_db_path() -> Path:
    """Return the path to the papers SQLite database.

    Reads ``academic.paper_db_path`` from config.  Falls back to
    ``{scholar_dir}/data/papers.db`` when the key is absent.
    """
    config = load_config()
    configured = config.get("academic", {}).get("paper_db_path")
    if configured:
        return Path(configured)
    return Path(config["scholar_dir"]) / "data" / "papers.db"


# ── Cache management ────────────────────────────────────────────────


def clear_cache() -> None:
    """Clear cached config (useful after setup_mcp.py writes new config)."""
    global _config_cache, _resolution_cache
    with _config_lock:
        _config_cache = None
        _resolution_cache = None


# ── Diagnostics ─────────────────────────────────────────────────────


def get_config_file_path() -> Path | None:
    """Return the resolved config file path (without loading)."""
    return _get_resolution().config_file


def detect_runtime_mode() -> str:
    """Detect the current runtime mode based on config file location."""
    return _get_resolution().mode


def get_research_interests() -> dict:
    """Return research_interests from .scholar.json academic config.

    Returns a dict with 'research_domains' and 'excluded_keywords'.
    Falls back to empty domains if not configured.
    """
    config = load_config()
    academic = config.get("academic", {})
    interests = academic.get("research_interests", {})
    if isinstance(interests, list) and not interests:
        return {"research_domains": {}, "excluded_keywords": []}
    if not isinstance(interests, dict):
        return {"research_domains": {}, "excluded_keywords": []}
    return interests
