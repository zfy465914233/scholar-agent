"""Index lifecycle management — stale detection, locking, background rebuilds.

This module owns the decision of **when** to rebuild the search index.
The actual build logic lives in :func:`local_index.write_index`; this module
wraps it with:

* **Stale-marker tracking** — a ``.stale`` sentinel file that signals
  "index is out-of-date, rebuild on next read".
* **mtime-based change detection** — if any card in the configured scan
  directories (knowledge, paper-notes, daily-notes) is newer than the
  index, a rebuild is triggered automatically.
* **Multi-process safety** — :func:`local_index.write_index` handles its
  own ``O_EXCL`` lock file.  This module does **not** layer a second lock
  on top, avoiding the deadlock that would arise from nested lock
  acquisition on the same file.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from scholar_agent.engine.scholar_config import (
    get_daily_notes_dir,
    get_index_path,
    get_knowledge_dir,
    get_paper_notes_dir,
)

logger = logging.getLogger(__name__)


# ── Stale marker helpers ────────────────────────────────────────────


def _stale_marker_path(index_path: Path) -> Path:
    return index_path.with_suffix(index_path.suffix + ".stale")


def mark_stale(index_path: Path) -> None:
    """Signal that the index is out-of-date and should be rebuilt."""
    marker = _stale_marker_path(index_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("stale\n", encoding="utf-8")


def _clear_stale(index_path: Path) -> None:
    marker = _stale_marker_path(index_path)
    with contextlib.suppress(FileNotFoundError):
        marker.unlink()


# ── Scan directories for stale detection ────────────────────────────


def _scan_dirs() -> list[Path]:
    """Return all directories to check for file modifications.

    De-duplicates in case any of the configured paths overlap.
    """
    dirs = [get_knowledge_dir(), get_paper_notes_dir(), get_daily_notes_dir()]
    seen: set[str] = set()
    unique: list[Path] = []
    for d in dirs:
        key = str(d.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


def _is_stale_vs_files(index_path: Path) -> bool:
    """Return True if any card file is newer than the index."""
    if not index_path.exists():
        return True
    try:
        index_mtime = index_path.stat().st_mtime
    except OSError:
        return True

    for scan_dir in _scan_dirs():
        if not scan_dir.exists():
            continue
        try:
            for card_path in scan_dir.rglob("*.md"):
                if card_path.stat().st_mtime > index_mtime:
                    return True
        except OSError:
            continue
    return False


# ── Rebuild helpers ─────────────────────────────────────────────────


def _do_reindex(knowledge_root: Path, index_path: Path) -> bool:
    """Call ``close_knowledge_loop.reindex`` and return True on success."""
    from scholar_agent.engine.close_knowledge_loop import reindex

    try:
        return reindex(knowledge_root, index_path)
    except Exception:
        logger.exception("index rebuild failed")
        return False


# ── Public API ──────────────────────────────────────────────────────


def async_reindex(index_path: Path) -> None:
    """Mark index stale and trigger a non-blocking rebuild in a background thread."""

    mark_stale(index_path)

    def _run() -> None:
        try:
            logger.info("Triggering background search index rebuild...")
            ensure_ready()
            logger.info("Background search index rebuild completed.")
        except Exception:
            logger.exception("Error in background reindex thread")

    threading.Thread(target=_run, daemon=True).start()


def ensure_ready() -> tuple[Path, bool, str | None]:
    """Ensure the search index is fresh; rebuild if necessary.

    Returns ``(index_path, was_refreshed, error_message)``.

    * ``was_refreshed`` is True when a rebuild was attempted (whether or
      not it succeeded).
    * ``error_message`` is None on success, or a human-readable string
      describing why the refresh failed.

    This function does **not** acquire its own lock.  Locking is handled
    entirely by :func:`local_index.write_index`, which uses an
    ``O_EXCL`` lock file.  If another process holds the lock,
    ``write_index`` raises :class:`RuntimeError` after a timeout; we
    surface that as a transient error message.
    """
    index_path = get_index_path()
    marker = _stale_marker_path(index_path)

    # Determine whether a rebuild is needed
    needs_refresh = marker.exists() or _is_stale_vs_files(index_path)

    if not needs_refresh:
        return index_path, False, None

    # Attempt rebuild — write_index handles its own locking
    success = _do_reindex(get_knowledge_dir(), index_path)

    if success:
        _clear_stale(index_path)
        return index_path, True, None

    logger.warning("Index refresh failed for %s", index_path)
    if not index_path.exists():
        return index_path, True, "Knowledge index not found and automatic refresh failed."
    return index_path, True, "Automatic refresh failed; serving the last available index."
