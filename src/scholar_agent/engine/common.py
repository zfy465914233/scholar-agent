"""Shared utilities for Scholar Agent scripts.

Consolidates duplicated patterns across the codebase:
  - parse_frontmatter: YAML frontmatter parsing (was in 3 files)
  - slugify / safe_slug: text slugification (was in 3 files)
  - load_json / write_json: safe JSON I/O (was in 10+ files)
  - normalize_date: date normalization (was in 2 files)
  - now_iso: UTC timestamp (was in 2 files)
  - logging setup helpers
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RESERVED_KNOWLEDGE_DIRS = frozenset({"_snapshots", "templates"})


# ── Repo root resolution ──────────────────────────────────────────

_REPO_ROOT: Path | None = None

# Package data directory (schemas, templates, config_data live here)
_PKG_DATA_DIR = Path(__file__).resolve().parent.parent  # scholar_agent/


def get_repo_root() -> Path:
    """Return the project repository root directory.

    Walks up from this file until it finds ``pyproject.toml``.
    Cached after first call.
    """
    global _REPO_ROOT
    if _REPO_ROOT is not None:
        return _REPO_ROOT
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "pyproject.toml").exists():
            _REPO_ROOT = candidate
            return candidate
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    # Fallback: assume src layout → up 3 levels from engine/
    _REPO_ROOT = Path(__file__).resolve().parents[3]
    return _REPO_ROOT


def get_package_data_path(*parts: str) -> Path:
    """Return a path to a bundled data file within the scholar_agent package.

    Looks for the file at ``_PKG_DATA_DIR / parts`` first (pip-installed),
    then falls back to ``get_repo_root() / "src" / "scholar_agent" / parts``
    (development mode with src layout).
    """
    pkg_path = _PKG_DATA_DIR.joinpath(*parts)
    if pkg_path.exists():
        return pkg_path
    return get_repo_root().joinpath("src", "scholar_agent", *parts)


def is_reserved_knowledge_path(path: Path) -> bool:
    """Return True for internal knowledge files that are not user cards."""
    parts = set(path.parts)
    return bool(parts & RESERVED_KNOWLEDGE_DIRS) or path.name.lower() == "readme.md"


# ── Network / URL helpers ──────────────────────────────────────────


# Domains that reliably block/forbid automated retrieval. Single source of
# truth — used by research_harness.fetch_content and dead_link_check.
BLOCKED_FETCH_DOMAINS: frozenset[str] = frozenset(
    {
        "sciencedirect.com",
        "wiley.com",
        "onlinelibrary.wiley.com",
        "ieee.org",
        "ieeexplore.ieee.org",
        "nature.com",
    }
)


def is_blocked_host(url: str) -> str | None:
    """Return the matched blocked domain for *url*, or None if not blocked."""
    from urllib.parse import urlparse

    host = urlparse(url).netloc.lower()
    for domain in BLOCKED_FETCH_DOMAINS:
        if host == domain or host.endswith(f".{domain}"):
            return domain
    return None


def extract_source_urls(metadata: dict[str, Any]) -> list[str]:
    """Extract http(s) URLs from a card's parsed frontmatter source_refs/sources."""
    urls: list[str] = []
    seen: set[str] = set()
    for key in ("source_refs", "sources"):
        val = metadata.get(key)
        if isinstance(val, list):
            candidates = val
        elif isinstance(val, str) and val:
            candidates = [val]
        else:
            candidates = []
        for entry in candidates:
            url = str(entry).strip().strip("'\"")
            if url.startswith(("http://", "https://")) and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


# ── Frontmatter parsing ────────────────────────────────────────────


def _normalize_frontmatter_value(value: Any) -> Any:
    """Convert YAML-loaded values into JSON-safe frontmatter values."""
    if value is None:
        # Preserve the historical lightweight parser behavior: a bare
        # ``key:`` represented an empty list placeholder.
        return []
    if isinstance(value, dict):
        return {str(k): _normalize_frontmatter_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_frontmatter_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _decode_unicode_escapes(value: str) -> str:
    if "\\u" not in value:
        return value
    return re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda m: chr(int(m.group(1), 16)),
        value,
    )


def _parse_inline_list(value: str) -> list[str] | None:
    stripped = value.strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        return None
    inner = stripped[1:-1].strip()
    if not inner:
        return []
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    return [item.strip().strip("'\"") for item in inner.split(",") if item.strip()]


def _parse_frontmatter_fallback(frontmatter: str) -> dict[str, Any]:
    """Parse the small frontmatter subset used when PyYAML is unavailable."""
    lines = frontmatter.splitlines()
    metadata: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[str] | None = None

    for line in lines:
        if not line.strip():
            continue

        # List item under a key (indented with 2 spaces)
        if line.startswith("  - ") and current_key is not None and current_list is not None:
            current_list.append(_decode_unicode_escapes(line[4:].strip().strip("'\"")))
            continue

        # Also support unindented list items (some markdown styles)
        if line.startswith("- ") and current_key is not None and current_list is not None:
            current_list.append(_decode_unicode_escapes(line[2:].strip().strip("'\"")))
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = _decode_unicode_escapes(value.strip().strip("'\""))

        if not value:
            current_key = key
            current_list = []
            metadata[key] = current_list
            continue

        inline_list = _parse_inline_list(value)
        if inline_list is not None:
            metadata[key] = inline_list
        else:
            metadata[key] = value
        current_key = None
        current_list = None

    return metadata


def parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown string.

    Returns (metadata_dict, body_text).
    Uses PyYAML when installed, with a small fallback parser for the
    project-generated scalar/list subset.
    """
    if not raw.startswith("---\n") and not raw.startswith("---\r\n"):
        return {}, raw

    # Normalize line endings for consistent splitting
    normalized = raw.replace("\r\n", "\n")
    parts = normalized.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, raw

    frontmatter = "\n".join(parts[0].splitlines()[1:])  # skip opening ---
    try:
        import yaml  # type: ignore[import-untyped]

        loaded = yaml.safe_load(frontmatter) if frontmatter.strip() else {}
        if isinstance(loaded, dict):
            return (
                {str(k): _normalize_frontmatter_value(v) for k, v in loaded.items()},
                parts[1].strip(),
            )
    except Exception as exc:
        logger.debug("PyYAML frontmatter parse failed, using fallback parser: %s", exc)

    return _parse_frontmatter_fallback(frontmatter), parts[1].strip()


# ── Slugification ──────────────────────────────────────────────────


def sanitize_title(title: str) -> str:
    """Convert a paper title to a filesystem-safe directory/filename.

    Replaces unsafe characters with underscores, collapses whitespace,
    and truncates to 120 chars.  Used by both ``generate_note`` and
    ``download_paper`` so they produce the same subfolder name.
    """
    s = unicodedata.normalize("NFKC", title.strip())
    s = re.sub(r"[:/\\?*|\"<>,;&%#@!()]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(" ", "_")
    if len(s) > 120:
        s = s[:120].rstrip("_")
    return s or "untitled"


def slugify(text: str, fallback: str = "untitled") -> str:
    """Convert text to a URL-safe slug.

    Args:
        text: Input text.
        fallback: Value returned when the result would be empty.
    """
    normalized_text = unicodedata.normalize("NFKC", text).strip().lower()
    normalized_text = re.sub(r"[^\w\s-]+", " ", normalized_text, flags=re.UNICODE)
    normalized = re.sub(r"[_\s-]+", "-", normalized_text, flags=re.UNICODE).strip("-")
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
        val = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(val, dict):
            return val
        logger.warning("JSON at %s is not a dictionary", path)
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("failed to load JSON from %s: %s", path, exc)
        return {}


def write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Write JSON to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path,
        json.dumps(data, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Atomically write text by replacing a same-directory temporary file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding=encoding,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp_name).replace(path)
    except Exception:
        if tmp_name:
            with contextlib.suppress(OSError):
                Path(tmp_name).unlink(missing_ok=True)
        raise


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


# ── Entity extraction ─────────────────────────────────────────────

_CAPITALIZED_PHRASE = re.compile(r"\b([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)+)\b")
_BACKTICK_TERM = re.compile(r"`([^`]{2,40})`")
_STOP_ENTITIES = {
    "Research Note",
    "Knowledge Note",
    "Method Note",
    "Supporting Claims",
    "Missing Evidence",
    "Suggested Next Steps",
    "Visual Aids",
    "Source Images",
    "Concrete Example",
    "Expected Output",
    "Question",
    "Answer",
    "Uncertainty",
    "Inferences",
    "See Also",
    "Key Findings",
    "Related Work",
    "Further Reading",
    "Open Questions",
}


def extract_entities(text: str) -> list[str]:
    """Extract potential entity names from text using heuristics.

    Extracts:
    - Capitalized multi-word phrases (e.g. "Andrej Karpathy", "Monte Carlo")
    - Backtick-enclosed technical terms (e.g. `XGBoost`, `BM25`)

    Returns deduplicated list of entity strings.
    """
    entities: list[str] = []
    seen: set[str] = set()

    for match in _CAPITALIZED_PHRASE.findall(text):
        normalized = match.strip()
        if normalized not in _STOP_ENTITIES and normalized.lower() not in seen:
            seen.add(normalized.lower())
            entities.append(normalized)

    for match in _BACKTICK_TERM.findall(text):
        normalized = match.strip()
        if normalized.lower() not in seen and not normalized.startswith(("/", ".", "#")):
            seen.add(normalized.lower())
            entities.append(normalized)

    return entities


# ── Bounded memoization ───────────────────────────────────────────


class _Missing:
    """Sentinel for cache misses (distinct from a cached ``None``)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<MISS>"


#: Returned by :meth:`BoundedMemo.get` on a miss, TTL expiry, or identity drift.
MISS: Any = _Missing()


class BoundedMemo:
    """Thread-safe bounded FIFO memo, consolidating the duplicated
    ``(path, mtime)``-keyed and ``id(obj)``-keyed caches that lived in
    ``local_retrieve``, ``embedding_retrieve``, ``note_linker``, and
    ``index_lifecycle``.

    Two keying modes:

    - **value mode** (default): *key* is any hashable (e.g. a ``(path, mtime)``
      tuple). The entry is valid while it sits in the cache.
    - **identity mode** (``identity=True``): *key* is the object itself; the
      entry holds a strong reference to it and ``get`` re-checks
      ``stored is key`` to defend against ``id()`` reuse after garbage
      collection. Use for caches keyed on a mutable parsed payload that the
      caller reuses.

    ``ttl_seconds`` optionally expires entries: a ``get`` past the TTL returns
    :data:`MISS`. FIFO eviction at ``bound`` keeps memory bounded.
    """

    __slots__ = ("_bound", "_d", "_identity", "_lock", "_ttl")

    def __init__(
        self,
        bound: int = 4,
        *,
        ttl_seconds: float | None = None,
        identity: bool = False,
    ) -> None:
        self._d: dict[Any, Any] = {}
        self._lock = threading.Lock()
        self._bound = bound
        self._ttl = ttl_seconds
        self._identity = identity

    def get(self, key: Any) -> Any:
        """Return the cached value, or :data:`MISS` on miss / expiry / identity drift."""
        with self._lock:
            entry = self._d.get(id(key) if self._identity else key)
            if entry is None:
                return MISS
            if self._identity:
                stored_obj, value, ts = entry
                if stored_obj is not key:
                    return MISS
            else:
                value, ts = entry
            if self._ttl is not None and time.monotonic() - ts > self._ttl:
                return MISS
            return value

    def set(self, key: Any, value: Any) -> None:
        now = time.monotonic()
        with self._lock:
            k = id(key) if self._identity else key
            self._d[k] = (key, value, now) if self._identity else (value, now)
            while len(self._d) > self._bound:
                del self._d[next(iter(self._d))]

    def clear(self) -> None:
        with self._lock:
            self._d.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._d)
