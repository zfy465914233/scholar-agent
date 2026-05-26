"""URL cache helper for the research pipeline.

Stores crawled URL content as Markdown files.
Key: SHA-256 of the URL. TTL: 24 hours by default.

Cache directory resolution order:
  1. SCHOLAR_CACHE_DIR environment variable
  2. <project_root>/.cache/
  3. /tmp/scholar_cache/ (fallback)

Supports LRU eviction: when the cache exceeds MAX_ENTRIES, the oldest
entries are pruned automatically on the next ``put()`` call.
"""

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _resolve_cache_dir() -> Path:
    if env := os.environ.get("SCHOLAR_CACHE_DIR"):
        return Path(env)
    # Walk up from this script to find project root (contains .github/)
    here = Path(__file__).resolve().parent
    for ancestor in [here.parent, *here.parent.parents]:
        if (ancestor / ".github").is_dir():
            return ancestor / ".cache"
    return Path("/tmp/scholar_cache")


CACHE_DIR = _resolve_cache_dir()
DEFAULT_TTL = 86400  # 24 hours
MAX_ENTRIES = int(os.environ.get("SCHOLAR_CACHE_MAX_ENTRIES", "500"))


def _key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def get(url: str, ttl: int = DEFAULT_TTL) -> Optional[str]:
    """Return cached Markdown content for *url*, or None if missing / expired."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = CACHE_DIR / f"{_key(url)}.meta.json"
    content_path = CACHE_DIR / f"{_key(url)}.md"
    if not meta_path.exists() or not content_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None  # corrupted cache entry
    if time.time() - meta.get("ts", 0) > ttl:
        return None  # expired
    return content_path.read_text()


def put(url: str, markdown: str) -> Path:
    """Store *markdown* for *url* and return the content path."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _evict_if_needed()
    k = _key(url)
    meta_path = CACHE_DIR / f"{k}.meta.json"
    content_path = CACHE_DIR / f"{k}.md"
    meta_path.write_text(json.dumps({"url": url, "ts": time.time()}))
    content_path.write_text(markdown)
    return content_path


def invalidate(url: str) -> None:
    """Remove cached entry for *url*."""
    k = _key(url)
    for suffix in (".meta.json", ".md"):
        p = CACHE_DIR / f"{k}{suffix}"
        p.unlink(missing_ok=True)


def clear_all() -> int:
    """Remove all cached entries. Returns count of entries removed."""
    if not CACHE_DIR.exists():
        return 0
    count = 0
    for p in CACHE_DIR.glob("*.meta.json"):
        k = p.stem.replace(".meta", "")
        p.unlink()
        md = CACHE_DIR / f"{k}.md"
        md.unlink(missing_ok=True)
        count += 1
    return count


def _evict_if_needed() -> None:
    """Prune oldest entries when cache exceeds MAX_ENTRIES."""
    if not CACHE_DIR.exists():
        return
    meta_files = sorted(
        CACHE_DIR.glob("*.meta.json"),
        key=lambda p: p.stat().st_mtime,
    )
    excess = len(meta_files) - MAX_ENTRIES
    if excess <= 0:
        return
    # Remove the oldest 10% beyond the limit (amortize eviction cost)
    to_remove = max(excess, len(meta_files) // 10)
    for meta_path in meta_files[:to_remove]:
        k = meta_path.stem.replace(".meta", "")
        meta_path.unlink(missing_ok=True)
        (CACHE_DIR / f"{k}.md").unlink(missing_ok=True)
    logger.debug("Cache eviction: removed %d entries (limit=%d)", to_remove, MAX_ENTRIES)


def cache_stats() -> dict[str, int]:
    """Return cache statistics: entry count and total size in bytes."""
    if not CACHE_DIR.exists():
        return {"entries": 0, "bytes": 0}
    entries = 0
    total_bytes = 0
    for p in CACHE_DIR.iterdir():
        if p.is_file():
            entries += 1
            total_bytes += p.stat().st_size
    return {"entries": entries // 2, "bytes": total_bytes}


if __name__ == "__main__":
    # Quick self-test
    test_url = "https://example.com/test"
    put(test_url, "# Hello\nCached content.")
    assert get(test_url) is not None, "cache miss after put"
    stats = cache_stats()
    assert stats["entries"] >= 1, "cache stats should report at least 1 entry"
    invalidate(test_url)
    assert get(test_url) is None, "cache hit after invalidate"
    print("cache_helper: self-test passed")
