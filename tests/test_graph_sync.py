"""Tests for engine.graph_sync — PaperPulse → local relation sync, and the
paper_relations (schema v3) migration in PaperStore."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

import pytest
import requests

from scholar_agent.engine import graph_sync
from scholar_agent.engine.graph_sync import sync_from_paperpulse
from scholar_agent.engine.paper_store import _CREATE_TABLES, PaperStore

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def store(tmp_path: Path) -> PaperStore:
    s = PaperStore(tmp_path / "papers.db")
    s.initialize()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero-out retry/polite delays so failure-path tests stay fast."""
    monkeypatch.setattr(graph_sync, "_RETRY_BASE_DELAY", 0)
    monkeypatch.setattr(graph_sync, "_POLITE_DELAY_S", 0)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


class _FakeSession:
    """Minimal requests.Session stand-in: routes matched by URL substring."""

    def __init__(
        self,
        routes: dict[str, _FakeResponse] | None = None,
        failures: dict[str, type[Exception]] | None = None,
    ) -> None:
        self._routes = routes or {}
        self._failures = failures or {}
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []

    def get(self, url: str, params: dict | None = None, timeout: int | None = None) -> _FakeResponse:
        self.calls.append(url)
        for key, exc_type in self._failures.items():
            if key in url:
                raise exc_type(f"boom: {url}")
        for key, resp in self._routes.items():
            if key in url:
                return resp
        return _FakeResponse({}, 404)

    def close(self) -> None:
        pass


def _patch_session(monkeypatch: pytest.MonkeyPatch, session: _FakeSession) -> None:
    monkeypatch.setattr(graph_sync._requests, "Session", lambda: session)


_ATTENTION = {"arxiv_id": "1706.03762", "title": "Attention Is All You Need"}
_BERT = {"arxiv_id": "1810.04805", "title": "BERT: Pre-training of Deep Bidirectional Transformers"}

_OVERVIEW = {
    "nodes": [
        {"id": "uuid-attn", "title": "Attention Is All You Need!", "year": 2017},
        {"id": "uuid-unrelated", "title": "Totally Unrelated Paper", "year": 2020},
    ],
    "edges": [],
}

_CONTEXT_ATTN = {
    "citations_outgoing": [
        {"paper_id": "uuid-bert", "title": "BERT: Pre-training of Deep Bidirectional Transformers"},
    ],
    "citations_incoming": [
        {"paper_id": "uuid-gpt", "title": "Improving Language Understanding by Generative Pre-Training"},
    ],
    "semantic_relations": [
        {
            "paper_id": "uuid-rnn",
            "title": "Some RNN Baseline",
            "rel_type": "baseline_for",
            "confidence": 0.9,
            "reason": "used as the recurrent baseline",
        },
        # unsupported rel_type — must be filtered out
        {"paper_id": "uuid-x", "title": "Whatever", "rel_type": "same_authors", "confidence": 0.5},
    ],
}


class TestMigration:
    def _build_v2_db(self, db_path: Path) -> None:
        """Create a pre-v3 database (schema v1+v2 rows, no paper_relations)."""
        conn = sqlite3.connect(str(db_path))
        conn.executescript(_CREATE_TABLES)
        conn.execute("INSERT INTO schema_version (version, description) VALUES (1, 'initial')")
        conn.execute("INSERT INTO schema_version (version, description) VALUES (2, 'papers.rejected_at')")
        conn.execute("INSERT INTO papers (arxiv_id, title) VALUES ('1706.03762', 'Attention Is All You Need')")
        conn.commit()
        conn.close()

    def test_v2_db_migrates_to_v3_and_data_survives(self, tmp_path: Path) -> None:
        db_path = tmp_path / "papers.db"
        self._build_v2_db(db_path)
        with PaperStore(db_path) as store:
            store.initialize()
            with store._cursor() as cur:
                tables = {row["name"] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                versions = [row["version"] for row in cur.execute("SELECT version FROM schema_version")]
            assert "paper_relations" in tables
            assert 3 in versions
            assert store.paper_exists(arxiv_id="1706.03762")

    def test_initialize_idempotent(self, store: PaperStore) -> None:
        store.initialize()  # second run on the same DB
        store.initialize()
        with store._cursor() as cur:
            versions = [row["version"] for row in cur.execute("SELECT version FROM schema_version")]
            rel_tables = [
                row["name"]
                for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='paper_relations'")
            ]
        assert sorted(versions) == [1, 2, 3, 4]
        assert rel_tables == ["paper_relations"]


class TestRelationStorage:
    def test_upsert_dedups_on_unique_key(self, store: PaperStore) -> None:
        rel = {
            "source_key": "1706.03762",
            "target_key": "1810.04805",
            "target_title": "BERT",
            "rel_type": "cites",
            "confidence": 0.5,
        }
        store.upsert_relation(rel)
        store.upsert_relation({**rel, "confidence": 0.9, "reason": "updated"})
        rows = store.get_relations()
        assert len(rows) == 1
        assert rows[0]["confidence"] == 0.9
        assert rows[0]["reason"] == "updated"
        assert rows[0]["source"] == "paperpulse"

    def test_get_relations_queries(self, store: PaperStore) -> None:
        store.upsert_relation(
            {"source_key": "a1", "target_key": "a2", "target_title": "T2", "rel_type": "cites", "confidence": 1.0}
        )
        store.upsert_relation(
            {
                "source_key": "a3",
                "target_key": "a1",
                "target_title": "T1",
                "rel_type": "extends",
                "confidence": 0.7,
                "source": "manual",
            }
        )
        assert len(store.get_relations()) == 2
        paperpulse = store.get_relations(source="paperpulse")
        assert len(paperpulse) == 1 and paperpulse[0]["source_key"] == "a1"
        manual = store.get_relations(source="manual")
        assert len(manual) == 1 and manual[0]["rel_type"] == "extends"
        # get_relations_for matches either direction.
        for_a1 = store.get_relations_for("a1")
        assert {r["rel_type"] for r in for_a1} == {"cites", "extends"}
        assert len(store.get_relations_for("a2")) == 1
        assert store.get_relations_for("nobody") == []


class TestSyncFlow:
    def test_missing_token_returns_error(self, store: PaperStore, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("scholar_agent.engine.scholar_config.load_config", lambda: {})
        called = False

        def _no_session() -> Any:
            nonlocal called
            called = True
            return _FakeSession()

        monkeypatch.setattr(graph_sync._requests, "Session", _no_session)
        result = sync_from_paperpulse(store=store)
        assert result["status"] == "error"
        assert "paperpulse_token" in result["error"]
        assert not called  # no HTTP attempted

    def test_full_flow_and_resync_dedup(self, store: PaperStore, monkeypatch: pytest.MonkeyPatch) -> None:
        store.upsert_papers([_ATTENTION, _BERT])
        session = _FakeSession(
            {
                "overview": _FakeResponse(_OVERVIEW),
                "papers/uuid-attn/context": _FakeResponse(_CONTEXT_ATTN),
            }
        )
        _patch_session(monkeypatch, session)

        result = sync_from_paperpulse(token="tok", base_url="https://example.test", store=store)
        assert result == {
            "status": "ok",
            "matched_papers": 1,
            "relations_upserted": 3,
            "relations_pruned": 0,
            "cloud_nodes": 2,
        }
        # Bearer header set on the session.
        assert session.headers["Authorization"] == "Bearer tok"

        rows = store.get_relations()
        by_rel = {(r["source_key"], r["target_key"], r["rel_type"]): r for r in rows}
        # Outgoing citation: local → other; target resolved to its local arxiv via store title.
        assert ("1706.03762", "1810.04805", "cites") in by_rel
        # Incoming citation: stored flipped so "cites" keeps its true direction;
        # cloud-only target keeps the cloud UUID as key.
        assert ("uuid-gpt", "1706.03762", "cites") in by_rel
        # Semantic relation with reason; unknown rel_type filtered.
        semantic = by_rel[("1706.03762", "uuid-rnn", "baseline_for")]
        assert semantic["confidence"] == 0.9
        assert semantic["reason"] == "used as the recurrent baseline"
        assert semantic["target_title"] == "Some RNN Baseline"
        assert all(r["rel_type"] != "same_authors" for r in rows)

        # Re-sync: UNIQUE(source_key, target_key, rel_type) dedups — still 3 rows.
        result2 = sync_from_paperpulse(token="tok", base_url="https://example.test", store=store)
        assert result2["status"] == "ok"
        assert len(store.get_relations()) == 3

    def test_title_match_via_paper_note_frontmatter(
        self, store: PaperStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cloud node matching only a paper-note (not the store) still syncs."""
        notes_dir = tmp_path / "paper-notes"
        notes_dir.mkdir()
        (notes_dir / "attn.md").write_text(
            '---\ntitle: "Attention Is All You Need"\npaper_id: "arXiv:1706.03762"\n---\n',
            encoding="utf-8",
        )
        monkeypatch.setattr("scholar_agent.engine.scholar_config.get_paper_notes_dir", lambda: notes_dir)
        session = _FakeSession(
            {
                "overview": _FakeResponse(_OVERVIEW),
                "papers/uuid-attn/context": _FakeResponse({"citations_outgoing": [], "semantic_relations": []}),
            }
        )
        _patch_session(monkeypatch, session)
        result = sync_from_paperpulse(token="tok", base_url="https://example.test", store=store)
        assert result["status"] == "ok"
        assert result["matched_papers"] == 1

    def test_401_returns_actionable_error(self, store: PaperStore, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession({"overview": _FakeResponse({}, 401)})
        _patch_session(monkeypatch, session)
        result = sync_from_paperpulse(token="expired", base_url="https://example.test", store=store)
        assert result["status"] == "error"
        assert "paperpulse_token expired" in result["error"]
        assert "re-login" in result["error"]
        # 401 is not retried.
        assert len(session.calls) == 1

    def test_partial_failure_keeps_successful_relations(
        self, store: PaperStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store.upsert_papers([_ATTENTION, _BERT])
        overview = {
            "nodes": [
                {"id": "uuid-attn", "title": "Attention Is All You Need"},
                {"id": "uuid-bert", "title": "BERT: Pre-training of Deep Bidirectional Transformers"},
            ]
        }
        session = _FakeSession(
            {
                "overview": _FakeResponse(overview),
                "papers/uuid-attn/context": _FakeResponse(_CONTEXT_ATTN),
            },
            failures={"papers/uuid-bert/context": requests.exceptions.ConnectionError},
        )
        _patch_session(monkeypatch, session)
        result = sync_from_paperpulse(token="tok", base_url="https://example.test", store=store)
        assert result["status"] == "partial"
        assert result["matched_papers"] == 2
        assert result["relations_upserted"] == 3  # all from the successful context
        assert result["relations_pruned"] == 0  # partial fetch must NOT prune — would delete valid cloud edges
        assert result["warnings"]
        # Failing context was retried (_RETRY_MAX + 1 attempts).
        bert_calls = [u for u in session.calls if "uuid-bert" in u]
        assert len(bert_calls) == graph_sync._RETRY_MAX + 1
        assert len(store.get_relations()) == 3

    def test_overview_network_failure(self, store: PaperStore, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession(failures={"overview": requests.exceptions.ConnectionError})
        _patch_session(monkeypatch, session)
        result = sync_from_paperpulse(token="tok", base_url="https://example.test", store=store)
        assert result["status"] == "error"
        assert "failed to fetch graph overview" in result["error"]
        assert result["relations_upserted"] == 0
