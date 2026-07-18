"""Tests for index_lifecycle — staleness scan memoization (TTL cache)."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

import pytest

from scholar_agent.engine import index_lifecycle as il
from scholar_agent.engine.common import BoundedMemo

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _clear_memo():
    il._stale_scan_memo.clear()
    yield
    il._stale_scan_memo.clear()


def _make_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Notes dir with one card + an index file, both with the same old mtime."""
    notes = tmp_path / "notes"
    notes.mkdir()
    card = notes / "card.md"
    card.write_text("---\ntitle: t\n---\nbody", encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text("{}", encoding="utf-8")
    old = time.time() - 100
    os.utime(card, (old, old))
    os.utime(index, (old, old))
    return notes, index


def _add_card(notes: Path, name: str = "card2.md", *, mtime: float | None = None) -> Path:
    card = notes / name
    card.write_text("---\ntitle: newer\n---\nbody", encoding="utf-8")
    if mtime is not None:
        os.utime(card, (mtime, mtime))
    return card


class TestStaleScanMemo:
    def test_memoized_within_ttl(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        notes, index = _make_tree(tmp_path)
        monkeypatch.setattr(il, "_scan_dirs", lambda: [notes])
        monkeypatch.setattr(il, "_stale_scan_memo", BoundedMemo(bound=8, ttl_seconds=9999.0))

        assert il._is_stale_vs_files(index) is False
        # A card newer than the index appears after the scan: within the TTL
        # the memoized verdict is reused instead of re-walking the tree.
        _add_card(notes)
        assert il._is_stale_vs_files(index) is False

    def test_rescans_after_ttl(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        notes, index = _make_tree(tmp_path)
        monkeypatch.setattr(il, "_scan_dirs", lambda: [notes])
        # ttl=0 → every call expires the cached verdict and re-scans.
        monkeypatch.setattr(il, "_stale_scan_memo", BoundedMemo(bound=8, ttl_seconds=0.0))

        assert il._is_stale_vs_files(index) is False
        _add_card(notes)
        assert il._is_stale_vs_files(index) is True

    def test_index_mtime_change_forces_rescan(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        notes, index = _make_tree(tmp_path)
        monkeypatch.setattr(il, "_scan_dirs", lambda: [notes])
        monkeypatch.setattr(il, "_STALE_SCAN_TTL", 9999.0)

        _add_card(notes, mtime=time.time() - 50)  # newer than the index
        assert il._is_stale_vs_files(index) is True  # memoizes "stale"

        # A rebuild rewrites the index (new mtime) -> new memo key -> re-scan
        index.write_text('{"documents": []}', encoding="utf-8")
        assert il._is_stale_vs_files(index) is False

    def test_ensure_ready_clears_memo_after_rebuild(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        notes, index = _make_tree(tmp_path)
        _add_card(notes, mtime=time.time() - 50)  # newer than the index -> stale
        monkeypatch.setattr(il, "_scan_dirs", lambda: [notes])
        monkeypatch.setattr(il, "_STALE_SCAN_TTL", 9999.0)
        monkeypatch.setattr(il, "get_index_path", lambda: index)
        monkeypatch.setattr(il, "get_knowledge_dir", lambda: notes)

        def _fake_reindex(root: Path, path: Path) -> bool:
            path.write_text('{"documents": []}', encoding="utf-8")
            return True

        monkeypatch.setattr(il, "_do_reindex", _fake_reindex)

        assert il._is_stale_vs_files(index) is True
        assert il._stale_scan_memo  # memo populated by the scan

        path, refreshed, error = il.ensure_ready()
        assert refreshed is True
        assert error is None
        assert len(il._stale_scan_memo) == 0  # invalidated by the rebuild
        assert il._is_stale_vs_files(path) is False
