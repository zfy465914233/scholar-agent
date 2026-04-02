"""Shared configuration reader for Lore Agent.

Looks for .lore.json walking up from cwd. If not found, defaults to cwd.

Config file format (.lore.json):
{
  "knowledge_dir": "./knowledge",       // path to knowledge cards
  "index_path": "./indexes/local/index.json",  // path to BM25 index
  "lore_dir": "./lore-agent"            // only needed when embedded as subdirectory
}
"""

from __future__ import annotations

import json
from pathlib import Path

# Lore Agent's own directory (where this file lives)
LORE_ROOT = Path(__file__).resolve().parents[1]

# Defaults: always resolve relative to cwd, not lore-agent directory
_DEFAULTS = {
    "knowledge_dir": str(Path.cwd() / "knowledge"),
    "index_path": str(Path.cwd() / "indexes" / "local" / "index.json"),
    "lore_dir": str(LORE_ROOT),
}

_config_cache: dict | None = None


def _find_config_file() -> Path | None:
    """Walk up from cwd to find .lore.json."""
    current = Path.cwd()
    for _ in range(10):  # max 10 levels up
        candidate = current / ".lore.json"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def load_config() -> dict:
    """Load and return the merged configuration."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config = dict(_DEFAULTS)

    config_file = _find_config_file()
    if config_file is not None:
        try:
            overrides = json.loads(config_file.read_text(encoding="utf-8"))
            config_base = config_file.parent
            # Resolve relative paths against the config file's directory
            for key in ("knowledge_dir", "index_path", "lore_dir"):
                if key in overrides:
                    val = overrides[key]
                    if val is not None:
                        p = Path(val)
                        if not p.is_absolute():
                            p = config_base / p
                        config[key] = str(p.resolve())
        except (json.JSONDecodeError, OSError):
            pass

    _config_cache = config
    return config


def get_knowledge_dir() -> Path:
    return Path(load_config()["knowledge_dir"])


def get_index_path() -> Path:
    return Path(load_config()["index_path"])


def get_lore_dir() -> Path:
    return Path(load_config()["lore_dir"])


def clear_cache() -> None:
    """Clear cached config (useful after setup_mcp.py writes new config)."""
    global _config_cache
    _config_cache = None
