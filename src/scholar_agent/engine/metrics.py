"""In-process metrics counters for LLM usage and retrieval operations.

Lightweight, dependency-free. Counters are process-scoped: they reset when
the process restarts. In the MCP server (a long-running process) they
accumulate over the server lifetime; in one-shot CLI invocations they
reflect only that single run.

Use :func:`get_metrics` to snapshot the current counters (e.g. for a status
report), or :func:`reset` between test cases.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LLMStats:
    calls: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class RetrieveStats:
    calls: int = 0
    expansions_used: int = 0  # queries that triggered synonym expansion
    rerank_calls: int = 0
    rerank_fallbacks: int = 0  # batched → per-candidate fallback events


@dataclass
class _Metrics:
    llm: LLMStats = field(default_factory=LLMStats)
    retrieve: RetrieveStats = field(default_factory=RetrieveStats)


_metrics = _Metrics()
_lock = threading.Lock()


# ── Recording API ──────────────────────────────────────────────────


def record_llm_call(usage: dict[str, int] | None = None, *, failed: bool = False) -> None:
    """Record one LLM call. *usage* is the provider's token usage dict."""
    with _lock:
        _metrics.llm.calls += 1
        if failed:
            _metrics.llm.failures += 1
        if usage:
            _metrics.llm.prompt_tokens += int(usage.get("prompt_tokens", 0))
            _metrics.llm.completion_tokens += int(usage.get("completion_tokens", 0))
            _metrics.llm.total_tokens += int(usage.get("total_tokens", 0))


def record_retrieve_call(*, expansions_used: bool = False) -> None:
    """Record one retrieve() call. *expansions_used* indicates synonym expansion triggered."""
    with _lock:
        _metrics.retrieve.calls += 1
        if expansions_used:
            _metrics.retrieve.expansions_used += 1


def record_rerank_call(*, fallback: bool = False) -> None:
    """Record one rerank invocation. *fallback* indicates batched → per-candidate fallback."""
    with _lock:
        _metrics.retrieve.rerank_calls += 1
        if fallback:
            _metrics.retrieve.rerank_fallbacks += 1


# ── Snapshot API ───────────────────────────────────────────────────


def get_metrics() -> dict[str, Any]:
    """Return a JSON-serializable snapshot of the current counters."""
    with _lock:
        return {
            "llm": {
                "calls": _metrics.llm.calls,
                "failures": _metrics.llm.failures,
                "prompt_tokens": _metrics.llm.prompt_tokens,
                "completion_tokens": _metrics.llm.completion_tokens,
                "total_tokens": _metrics.llm.total_tokens,
            },
            "retrieve": {
                "calls": _metrics.retrieve.calls,
                "expansions_used": _metrics.retrieve.expansions_used,
                "rerank_calls": _metrics.retrieve.rerank_calls,
                "rerank_fallbacks": _metrics.retrieve.rerank_fallbacks,
            },
        }


def reset() -> None:
    """Reset all counters. Primarily for tests."""
    with _lock:
        _metrics.llm = LLMStats()
        _metrics.retrieve = RetrieveStats()


def _metrics_path() -> Path:
    """Where the metrics snapshot is persisted for out-of-process readers."""
    home = os.environ.get("SCHOLAR_HOME")
    base = Path(home) if home else Path.home() / ".scholar"
    return Path(base) / "metrics.json"


def persist() -> bool:
    """Atomically snapshot the counters to ``SCHOLAR_HOME/metrics.json``.

    Lets an out-of-process caller (e.g. ``scholar-agent status`` run in another
    shell) observe a long-running MCP server's accumulated metrics, which
    otherwise live only in that server's memory. Returns True on success.
    """
    path = _metrics_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(get_metrics(), ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        return False


def load_persisted() -> dict[str, Any] | None:
    """Read the persisted snapshot, or None if absent / unreadable."""
    path = _metrics_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
