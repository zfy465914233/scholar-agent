"""Tests for the review_card authority-management tool (Batch 6).

Guards the "common contract": AI may only change trust on explicit user
instruction, reason is mandatory, transitions go through the state machine
(deprecated is terminal), and every change is auditable on the card.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _write_card(root: Path, card_id: str, review_status: str = "reviewed") -> Path:
    card = root / f"{card_id}.md"
    card.write_text(
        f"---\nid: {card_id}\ntitle: T\ntype: knowledge\nreview_status: {review_status}\n---\nbody",
        encoding="utf-8",
    )
    return card


def _patch_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("scholar_agent.engine.scholar_config.get_knowledge_dir", lambda: tmp_path)
    monkeypatch.setattr("scholar_agent.server.get_index_path", lambda: tmp_path / "index.json")
    monkeypatch.setattr("scholar_agent.server._async_reindex", lambda p: None)


def _call(card_id: str, target: str, reason: str, **kw: object) -> dict:
    from scholar_agent.server import review_card

    fn = getattr(review_card, "fn", review_card)
    return json.loads(fn(card_id, target, reason, **kw))


def test_marks_stale_with_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_env(monkeypatch, tmp_path)
    card = _write_card(tmp_path, "c1", "reviewed")
    payload = _call("c1", "stale", "user said it is outdated")
    assert payload["status"] == "ok"
    assert payload["from"] == "reviewed"
    assert payload["to"] == "stale"
    content = card.read_text(encoding="utf-8")
    assert "review_status: stale" in content
    assert "status_reason:" in content
    assert "status_changed_at:" in content


def test_reason_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_env(monkeypatch, tmp_path)
    payload = _call("c1", "stale", "   ")
    assert "error" in payload


def test_illegal_transition_returns_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_env(monkeypatch, tmp_path)
    _write_card(tmp_path, "c1", "deprecated")  # terminal
    payload = _call("c1", "reviewed", "try to revive")  # deprecated -> reviewed is illegal
    assert "error" in payload
    assert payload["current_status"] == "deprecated"


def test_unknown_card(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_env(monkeypatch, tmp_path)
    payload = _call("nope", "stale", "x")
    assert "error" in payload


def test_invalid_target_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_env(monkeypatch, tmp_path)
    _write_card(tmp_path, "c1")
    payload = _call("c1", "bogus", "x")
    assert "error" in payload


def test_draft_can_be_marked_stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A draft card the user calls "outdated" must go stale (draft→stale is
    legal for an explicit user review — only the auto dead-link sweep opts out)."""
    _patch_env(monkeypatch, tmp_path)
    card = _write_card(tmp_path, "c1", "draft")
    payload = _call("c1", "stale", "user said this draft is already outdated")
    assert payload["status"] == "ok"
    assert payload["from"] == "draft"
    assert payload["to"] == "stale"
    assert "review_status: stale" in card.read_text(encoding="utf-8")


def test_draft_can_be_promoted_to_trusted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """User can vouch for a draft directly (draft→trusted), skipping reviewed."""
    _patch_env(monkeypatch, tmp_path)
    _write_card(tmp_path, "c1", "draft")
    payload = _call("c1", "trusted", "user vouches for it directly")
    assert payload["status"] == "ok"
    assert payload["to"] == "trusted"
