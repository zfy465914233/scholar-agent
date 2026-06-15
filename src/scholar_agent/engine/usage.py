"""Usage-based card popularity tracking for light personalization.

Records how often each card is surfaced by ``query_knowledge``. ``retrieve()``
reads the counts and applies a capped, sub-linear boost so frequently-used
cards edge upward — without overriding relevance.

Design notes:
- The boost is logarithmic and capped (max ~+20%), so a brand-new card
  (count 0) is unaffected (cold-start safe) and even a very popular card
  cannot outrank a clearly more relevant one.
- Counts persist to ``SCHOLAR_HOME/usage.json`` so they survive restarts of
  the long-running MCP server.
- All access goes through a lock — safe for the MCP server's request threads.
"""

from __future__ import annotations

import json
import math
import os
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_usage: dict[str, int] = {}

# Boost curve: 1 + BOOST_FACTOR * min(log2(1 + count), BOOST_CAP_STEPS).
# log2 keeps the boost sub-linear (diminishing returns); the cap bounds the
# maximum influence of popularity on ranking.
BOOST_FACTOR = 0.05
BOOST_CAP_STEPS = 4.0  # log2(1+15)≈4 → max boost 1 + 0.05*4 = 1.20


def _usage_path() -> Path:
    home = os.environ.get("SCHOLAR_HOME")
    base = Path(home) if home else Path.home() / ".scholar"
    return Path(base) / "usage.json"


def load_usage() -> dict[str, int]:
    """Return ``{doc_id: count}``, loaded lazily from disk and cached."""
    with _lock:
        if _usage:
            return _usage
        path = _usage_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, (int, float)) and v > 0:
                    _usage[str(k)] = int(v)
        return _usage


def record_usage(doc_ids: list[str]) -> None:
    """Increment counts for *doc_ids* and persist atomically."""
    if not doc_ids:
        return
    path = _usage_path()
    with _lock:
        for d in doc_ids:
            key = str(d)
            _usage[key] = _usage.get(key, 0) + 1
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(_usage, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass


def usage_boost(doc_id: str, usage: dict[str, int] | None = None) -> float:
    """Capped logarithmic popularity boost in [1.0, 1.20]."""
    counts = usage if usage is not None else load_usage()
    count = counts.get(str(doc_id), 0)
    if count <= 0:
        return 1.0
    return 1.0 + BOOST_FACTOR * min(math.log2(1 + count), BOOST_CAP_STEPS)


def reset() -> None:
    """Clear the in-memory cache. Primarily for tests."""
    with _lock:
        _usage.clear()


def get_usage_snapshot() -> dict[str, Any]:
    """Return a JSON-serializable snapshot of current counts (for status)."""
    with _lock:
        return {"cards": len(_usage), "total_hits": sum(_usage.values()), "top": _get_top(5)}


def _get_top(n: int) -> list[dict[str, Any]]:
    items = sorted(_usage.items(), key=lambda x: -x[1])[:n]
    return [{"doc_id": k, "hits": v} for k, v in items]
