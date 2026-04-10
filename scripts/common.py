"""Shared utilities for Lore Agent scripts.

Consolidates duplicated patterns across the codebase:
  - parse_frontmatter: YAML frontmatter parsing (was in 3 files)
  - slugify / safe_slug: text slugification (was in 3 files)
  - load_json / write_json: safe JSON I/O (was in 10+ files)
  - normalize_date: date normalization (was in 2 files)
  - now_iso: UTC timestamp (was in 2 files)
  - logging setup helpers
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Frontmatter parsing ────────────────────────────────────────────

def parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-like frontmatter from a markdown string.

    Returns (metadata_dict, body_text).
    Handles scalar values and list values (``  - item`` syntax).
    """
    if not raw.startswith("---\n"):
        return {}, raw

    parts = raw.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, raw

    lines = parts[0].splitlines()[1:]  # skip opening ---
    metadata: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[str] | None = None

    for line in lines:
        if not line.strip():
            continue

        # List item under a key (indented with 2 spaces)
        if line.startswith("  - ") and current_key is not None and current_list is not None:
            current_list.append(line[4:].strip())
            continue

        # Also support unindented list items (some markdown styles)
        if line.startswith("- ") and current_key is not None and current_list is not None:
            current_list.append(line[2:].strip())
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("'\"")

        if not value:
            current_key = key
            current_list = []
            metadata[key] = current_list
        else:
            current_key = None
            current_list = None
            metadata[key] = value

    return metadata, parts[1].strip()


# ── Slugification ──────────────────────────────────────────────────

def slugify(text: str, fallback: str = "untitled") -> str:
    """Convert text to a URL-safe slug.

    Args:
        text: Input text.
        fallback: Value returned when the result would be empty.
    """
    normalized = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return normalized or fallback


def safe_slug(text: str) -> str:
    """Like slugify but also strips path separators and dots to prevent traversal."""
    slug = slugify(text, fallback="untitled")
    # Belt-and-suspenders: strip anything that could form a path component
    slug = slug.replace(".", "").replace("/", "").replace("\\", "")
    return slug or "untitled"


# ── JSON I/O ───────────────────────────────────────────────────────

def load_json(path: Path) -> dict[str, Any]:
    """Load JSON from a file with error handling.

    Returns empty dict on failure and prints a warning to stderr.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("failed to load JSON from %s: %s", path, exc)
        return {}


def write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Write JSON to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )


# ── Date / time helpers ────────────────────────────────────────────

def normalize_date(value: Any) -> str | None:
    """Normalize a date value to ISO format.

    Accepts datetime objects, date strings in common formats, or None.
    Returns None for unparseable or empty input.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(text[:19], fmt)
            return (
                parsed.date().isoformat()
                if "T" not in fmt and " " not in fmt
                else parsed.replace(tzinfo=timezone.utc).isoformat()
            )
        except ValueError:
            continue
    return text


def now_iso() -> str:
    """Current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# ── Wiki-link extraction ──────────────────────────────────────────

_WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def extract_wiki_links(text: str) -> list[str]:
    """Extract [[card-id]] wiki-links from markdown text.

    Returns a deduplicated list of link targets (card IDs or slugs).
    """
    return list(dict.fromkeys(_WIKI_LINK_RE.findall(text)))


def resolve_link_target(target: str, all_ids: set[str]) -> str | None:
    """Resolve a wiki-link target to a doc_id.

    Tries exact match first, then partial match (target is a substring
    of a doc_id). Returns None if no match is found.
    """
    if target in all_ids:
        return target
    for did in all_ids:
        if target in did:
            return did
    return None
