"""Path helpers for Scholar Agent configuration and state."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

APP_NAME = "scholar-agent"
_SCHOLAR_HOME_DIR = "scholar"


def get_scholar_root() -> Path:
    # Assumes this module lives at scholar_agent/config/paths.py, so parents[2] is the project root.
    return Path(__file__).resolve().parents[2]


def _default_user_home() -> Path:
    """Cross-platform default: ~/scholar/ on all platforms.

    Simple, discoverable, consistent. Override with SCHOLAR_HOME env var.
    """
    return Path.home() / _SCHOLAR_HOME_DIR


def get_user_home(env: Mapping[str, str] | None = None) -> Path:
    env_map = os.environ if env is None else env
    override = env_map.get("SCHOLAR_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _default_user_home().resolve()


def get_user_config_path(env: Mapping[str, str] | None = None) -> Path:
    return get_user_home(env) / "config" / "config.json"


def get_user_profile_path(profile: str, env: Mapping[str, str] | None = None) -> Path:
    return get_user_home(env) / "config" / "profiles" / f"{profile}.json"


def build_default_config(*, env: Mapping[str, str] | None = None, scholar_root: Path | None = None) -> dict:
    resolved_root = (scholar_root or get_scholar_root()).resolve()
    user_home = get_user_home(env)
    profile = (env or os.environ).get("SCHOLAR_PROFILE", "default").strip() or "default"
    return {
        "knowledge_dir": str((user_home / "knowledge").resolve()),
        "index_path": str((user_home / "indexes" / "local" / "index.json").resolve()),
        "scholar_dir": str(resolved_root),
        "profile": profile,
        "academic": {
            "paper_notes_dir": str((user_home / "paper-notes").resolve()),
            "daily_notes_dir": str((user_home / "daily-notes").resolve()),
            "search": {
                "sources": ["arxiv", "dblp", "semantic_scholar"],
                "default_conferences": [
                    "CVPR", "ICCV", "ECCV", "ICLR", "AAAI",
                    "NeurIPS", "ICML", "ACL", "EMNLP", "MICCAI",
                ],
                "max_results": 20,
                "date_range_days": 30,
            },
            "scoring": {
                "dimensions": ["relevance", "recency", "popularity", "quality"],
                "max_score": 3.0,
            },
            "research_interests": {
                "research_domains": {},
                "excluded_keywords": ["survey", "workshop"],
            },
        },
    }
