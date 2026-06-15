"""Synonym-based query expansion for local retrieval.

Loads a curated dictionary from ``assets/synonyms.json`` (project default)
merged with ``~/.scholar/synonyms.json`` (user override). When a query
contains any phrase in a synonym group, all phrases in that group are
appended as additional queries and fused via RRF in :mod:`local_retrieve`.

Format::

    {
      "groups": [
        {"canonical": "diffusion model", "aliases": ["DDPM", "SDE", ...]},
        ...
      ]
    }

Public API:
- :func:`load_synonyms` — cached merge of project + user dictionaries
- :func:`expand_query` — return [original_query, alias1, alias2, ...]
"""

from __future__ import annotations

import json
import logging
import os
import threading
from functools import lru_cache
from pathlib import Path

from scholar_agent.engine.common import atomic_write_text

logger = logging.getLogger(__name__)

_DEFAULT_PROJECT_DICT = Path(__file__).resolve().parents[3] / "assets" / "synonyms.json"


def _user_dict_path() -> Path:
    """Return the user-level synonyms path under SCHOLAR_HOME or ~/.scholar."""
    home = os.environ.get("SCHOLAR_HOME")
    base = Path(home) if home else Path.home() / ".scholar"
    return Path(base) / "synonyms.json"


_load_lock = threading.Lock()


def _read_dict_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("failed to parse synonyms %s: %s", path, exc)
        return []
    groups = data.get("groups", []) if isinstance(data, dict) else []
    return [g for g in groups if isinstance(g, dict) and "canonical" in g]


def _merge_groups(project: list[dict], user: list[dict]) -> dict[str, list[str]]:
    """Merge project + user groups. User groups override by canonical name."""
    merged: dict[str, list[str]] = {}
    for group in project:
        canonical = str(group["canonical"]).strip().lower()
        aliases = [str(a).strip().lower() for a in group.get("aliases", []) if str(a).strip()]
        merged[canonical] = aliases
    for group in user:
        canonical = str(group["canonical"]).strip().lower()
        aliases = [str(a).strip().lower() for a in group.get("aliases", []) if str(a).strip()]
        merged[canonical] = aliases  # override
    return merged


@lru_cache(maxsize=4)
def _load_cached(project_path_str: str, user_path_str: str, user_mtime: float) -> dict[str, list[str]]:
    """Cache key includes file mtimes so edits invalidate the cache."""
    project = _read_dict_file(Path(project_path_str))
    user = _read_dict_file(Path(user_path_str))
    return _merge_groups(project, user)


def load_synonyms(project_path: Path | None = None) -> dict[str, list[str]]:
    """Return the merged synonym dictionary.

    Returns a mapping ``{canonical_lowercased: [aliases...]}``. Cached at
    module level; cache is keyed by file mtimes so edits invalidate it.
    """
    project_path = project_path or _DEFAULT_PROJECT_DICT
    user_path = _user_dict_path()
    try:
        user_mtime = user_path.stat().st_mtime if user_path.exists() else 0.0
    except OSError:
        user_mtime = 0.0

    with _load_lock:
        return _load_cached(str(project_path), str(user_path), user_mtime)


def clear_cache() -> None:
    """Invalidate the synonym cache. For use by CLI after editing the user dict."""
    _load_cached.cache_clear()


def expand_query(query: str, synonyms: dict[str, list[str]] | None = None) -> list[str]:
    """Return ``[original_query, alias1, alias2, ...]``.

    A group is "hit" if any phrase (canonical or alias) appears as a substring
    of the query (case-insensitive). All phrases from hit groups are appended
    as additional queries. Order is preserved; duplicates are removed.
    """
    if not query or not query.strip():
        return [query] if query else []

    if synonyms is None:
        try:
            synonyms = load_synonyms()
        except Exception as exc:
            logger.warning("synonyms load failed, skipping expansion: %s", exc)
            return [query]

    if not synonyms:
        return [query]

    lowered = query.lower()
    seen = {query.lower()}
    expansions = [query]

    for canonical, aliases in synonyms.items():
        group = [canonical, *aliases]
        if not any(member.lower() in lowered for member in group):
            continue
        for member in group:
            key = member.lower()
            if key not in seen:
                expansions.append(member)
                seen.add(key)

    return expansions


def add_user_group(canonical: str, aliases: list[str]) -> Path:
    """Add or overwrite a group in the user-level synonyms file. Returns its path."""
    user_path = _user_dict_path()
    user_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, object] = {"groups": []}
    if user_path.exists():
        try:
            existing = json.loads(user_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and isinstance(existing.get("groups"), list):
                data = existing
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("user synonyms file %s is unreadable, will be overwritten: %s", user_path, exc)

    raw_groups = data.get("groups", [])
    groups: list[dict] = [g for g in raw_groups if isinstance(g, dict)] if isinstance(raw_groups, list) else []
    canonical_clean = canonical.strip()
    aliases_clean = [a.strip() for a in aliases if a.strip()]
    # Remove existing group with same canonical (case-insensitive)
    groups = [g for g in groups if str(g.get("canonical", "")).lower() != canonical_clean.lower()]
    groups.append({"canonical": canonical_clean, "aliases": aliases_clean})
    data["groups"] = groups

    atomic_write_text(
        user_path,
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    clear_cache()
    return user_path


def remove_user_group(canonical: str) -> bool:
    """Remove a group from user-level synonyms. Returns True if removed."""
    user_path = _user_dict_path()
    if not user_path.exists():
        return False

    try:
        data = json.loads(user_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    groups = list(data.get("groups", [])) if isinstance(data, dict) else []
    canonical_lower = canonical.strip().lower()
    new_groups = [g for g in groups if str(g.get("canonical", "")).lower() != canonical_lower]
    if len(new_groups) == len(groups):
        return False

    data["groups"] = new_groups
    atomic_write_text(
        user_path,
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    clear_cache()
    return True
