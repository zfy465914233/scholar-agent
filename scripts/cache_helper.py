"""URL cache helper for the research harness.

Stores crawled URL content as Markdown files.
Key: SHA-256 of the URL. TTL: 24 hours by default.

Cache directory resolution order:
  1. HARNESS_CACHE_DIR environment variable
  2. <project_root>/.cache/
  3. /tmp/harness_cache/ (fallback)
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional


def _resolve_cache_dir() -> Path:
    if env := os.environ.get("HARNESS_CACHE_DIR"):
        return Path(env)
    # Walk up from this script to find project root (contains .github/)
    here = Path(__file__).resolve().parent
    for ancestor in [here.parent, *here.parent.parents]:
        if (ancestor / ".github").is_dir():
            return ancestor / ".cache"
    return Path("/tmp/harness_cache")


CACHE_DIR = _resolve_cache_dir()
DEFAULT_TTL = 86400  # 24 hours


def _key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def get(url: str, ttl: int = DEFAULT_TTL) -> Optional[str]:
    """Return cached Markdown content for *url*, or None if missing / expired."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = CACHE_DIR / f"{_key(url)}.meta.json"
    content_path = CACHE_DIR / f"{_key(url)}.md"
    if not meta_path.exists() or not content_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    if time.time() - meta.get("ts", 0) > ttl:
        return None  # expired
    return content_path.read_text()


def put(url: str, markdown: str) -> Path:
    """Store *markdown* for *url* and return the content path."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
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


if __name__ == "__main__":
    # Quick self-test
    test_url = "https://example.com/test"
    put(test_url, "# Hello\nCached content.")
    assert get(test_url) is not None, "cache miss after put"
    invalidate(test_url)
    assert get(test_url) is None, "cache hit after invalidate"
    print("cache_helper: self-test passed")
