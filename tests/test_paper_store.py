"""Tests for PaperStore — SQLite-backed paper storage."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import TYPE_CHECKING

import pytest

from scholar_agent.engine.paper_store import PaperStore

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def store(tmp_path: Path) -> PaperStore:
    db_path = tmp_path / "test_papers.db"
    s = PaperStore(db_path)
    s.initialize()
    yield s
    s.close()


class TestPrunePaperpulseRelations:
    def test_prunes_unexpected_paperpulse_edges(self, store: PaperStore) -> None:
        store.upsert_relation({"source_key": "a", "target_key": "b", "rel_type": "cites", "source": "paperpulse"})
        store.upsert_relation({"source_key": "a", "target_key": "c", "rel_type": "cites", "source": "paperpulse"})
        deleted = store.prune_paperpulse_relations({("a", "b", "cites")})
        assert deleted == 1
        keys = {(r["source_key"], r["target_key"], r["source"]) for r in store.get_relations()}
        assert ("a", "b", "paperpulse") in keys
        assert ("a", "c", "paperpulse") not in keys

    def test_manual_edges_are_never_pruned(self, store: PaperStore) -> None:
        store.upsert_relation({"source_key": "a", "target_key": "b", "rel_type": "cites", "source": "paperpulse"})
        store.upsert_relation({"source_key": "x", "target_key": "y", "rel_type": "cites", "source": "manual"})
        deleted = store.prune_paperpulse_relations(set())  # drop all paperpulse
        assert deleted == 1
        keys = {(r["source_key"], r["target_key"], r["source"]) for r in store.get_relations()}
        assert ("x", "y", "manual") in keys  # manual untouched
        assert ("a", "b", "paperpulse") not in keys


def _arxiv_paper(**overrides):
    """Build a minimal arXiv paper dict for testing."""
    base = {
        "arxiv_id": "2501.12345",
        "title": "Test Paper Title",
        "summary": "A test abstract about deep learning.",
        "authors": ["Alice Smith", "Bob Jones"],
        "affiliations": ["MIT", "Stanford"],
        "categories": ["cs.AI", "cs.LG"],
        "published_date": "2025-01-15",
        "source": "arxiv",
        "pdf_url": "https://arxiv.org/pdf/2501.12345",
        "url": "https://arxiv.org/abs/2501.12345",
    }
    base.update(overrides)
    return base


class TestSchema:
    def test_initialize_creates_tables(self, store: PaperStore) -> None:
        with store._cursor() as cur:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row["name"] for row in cur.fetchall()}
        assert "papers" in tables
        assert "funnel_runs" in tables
        assert "fetch_checkpoints" in tables
        assert "schema_version" in tables

    def test_schema_version_recorded(self, store: PaperStore) -> None:
        with store._cursor() as cur:
            cur.execute("SELECT version FROM schema_version")
            row = cur.fetchone()
        assert row is not None
        assert row["version"] == 1

    def test_wal_mode_enabled(self, store: PaperStore) -> None:
        with store._cursor() as cur:
            cur.execute("PRAGMA journal_mode")
            mode = cur.fetchone()["journal_mode"]
        assert mode == "wal"


class TestUpsert:
    def test_upsert_single_paper(self, store: PaperStore) -> None:
        row_id = store.upsert_paper(_arxiv_paper())
        assert row_id > 0
        assert store.paper_exists(arxiv_id="2501.12345")

    def test_upsert_normalizes_summary_to_abstract(self, store: PaperStore) -> None:
        store.upsert_paper(_arxiv_paper(summary="My abstract text"))
        papers = store.get_papers_by_status("fetched")
        assert papers[0]["abstract"] == "My abstract text"

    def test_upsert_dedup_by_arxiv_id(self, store: PaperStore) -> None:
        store.upsert_paper(_arxiv_paper(title="First"))
        store.upsert_paper(_arxiv_paper(title="Updated Title"))
        papers = store.get_papers_by_status("fetched")
        assert len(papers) == 1
        assert papers[0]["title"] == "Updated Title"

    def test_upsert_preserves_higher_citations(self, store: PaperStore) -> None:
        store.upsert_paper(_arxiv_paper(citation_count=10))
        store.upsert_paper(_arxiv_paper(citation_count=50))
        papers = store.get_papers_by_status("fetched")
        assert papers[0]["citation_count"] == 50

    def test_upsert_batch(self, store: PaperStore) -> None:
        papers = [_arxiv_paper(arxiv_id=f"2501.{i:05d}", title=f"Paper {i}") for i in range(5)]
        count = store.upsert_papers(papers)
        assert count == 5
        assert store.count_by_status()["fetched"] == 5

    def test_upsert_batch_deduplicates(self, store: PaperStore) -> None:
        papers = [_arxiv_paper(arxiv_id="2501.00001"), _arxiv_paper(arxiv_id="2501.00001")]
        count = store.upsert_papers(papers)
        assert count == 2  # both upserts executed
        assert store.count_by_status()["fetched"] == 1

    def test_upsert_with_no_arxiv_id(self, store: PaperStore) -> None:
        paper = {"title": "No arXiv ID paper", "abstract": "Some text", "source": "s2_graph"}
        row_id = store.upsert_paper(paper)
        assert row_id > 0
        assert store.paper_exists(title="No arXiv ID paper")

    def test_upsert_s2_paper(self, store: PaperStore) -> None:
        paper = {
            "paperId": "abc123",
            "arxivId": "2501.99999",
            "title": "S2 Paper",
            "abstract": "From S2",
            "publicationDate": "2025-02-01",
            "citationCount": 42,
            "influentialCitationCount": 10,
            "source": "s2_graph",
            "authors": [{"name": "Carol White"}],
        }
        row_id = store.upsert_paper(paper)
        assert row_id > 0
        papers = store.get_papers_by_status("fetched")
        assert papers[0]["citation_count"] == 42
        assert json.loads(papers[0]["authors"]) == ["Carol White"]

    def test_upsert_historical_flag(self, store: PaperStore) -> None:
        store.upsert_paper(_arxiv_paper(is_historical=True))
        papers = store.get_papers_by_status("fetched")
        assert papers[0]["is_historical"] == 1


class TestQuery:
    def test_paper_exists_by_arxiv_id(self, store: PaperStore) -> None:
        store.upsert_paper(_arxiv_paper())
        assert store.paper_exists(arxiv_id="2501.12345")
        assert not store.paper_exists(arxiv_id="9999.99999")

    def test_paper_exists_by_title(self, store: PaperStore) -> None:
        store.upsert_paper(_arxiv_paper())
        assert store.paper_exists(title="Test Paper Title")
        assert not store.paper_exists(title="Nonexistent")

    def test_get_papers_by_status(self, store: PaperStore) -> None:
        store.upsert_paper(_arxiv_paper(arxiv_id="2501.00001"))
        store.upsert_paper(_arxiv_paper(arxiv_id="2501.00002"))
        papers = store.get_papers_by_status("fetched")
        assert len(papers) == 2

    def test_get_papers_by_status_empty(self, store: PaperStore) -> None:
        papers = store.get_papers_by_status("nonexistent")
        assert papers == []


class TestUpdateStatus:
    def test_update_status_basic(self, store: PaperStore) -> None:
        row_id = store.upsert_paper(_arxiv_paper())
        store.update_status(row_id, "stage1_passed", relevance_score=3.5, best_domain="ai")
        papers = store.get_papers_by_status("stage1_passed")
        assert len(papers) == 1
        assert papers[0]["relevance_score"] == 3.5
        assert papers[0]["best_domain"] == "ai"

    def test_update_status_sets_processed_at(self, store: PaperStore) -> None:
        row_id = store.upsert_paper(_arxiv_paper())
        store.update_status(row_id, "skipped", skip_reason="short_abstract")
        papers = store.get_papers_by_status("skipped")
        assert papers[0]["processed_at"] is not None
        assert papers[0]["skip_reason"] == "short_abstract"

    def test_update_status_recommended_sets_recommended_at(self, store: PaperStore) -> None:
        row_id = store.upsert_paper(_arxiv_paper())
        store.update_status(
            row_id,
            "recommended",
            recommendation_score=8.5,
            recommendation_reason="Excellent contribution",
        )
        papers = store.get_papers_by_status("recommended")
        assert papers[0]["recommended_at"] is not None
        assert papers[0]["recommendation_score"] == 8.5


class TestCheckpoints:
    def test_set_and_get_checkpoint(self, store: PaperStore) -> None:
        store.set_checkpoint("arxiv", "cs.AI", "2025-01-15", papers_fetched=42)
        result = store.get_checkpoint("arxiv", "cs.AI")
        assert result == "2025-01-15"

    def test_checkpoint_not_found(self, store: PaperStore) -> None:
        assert store.get_checkpoint("nonexistent", "") is None

    def test_update_checkpoint(self, store: PaperStore) -> None:
        store.set_checkpoint("arxiv", "cs.AI", "2025-01-15")
        store.set_checkpoint("arxiv", "cs.AI", "2025-01-16", papers_fetched=10)
        assert store.get_checkpoint("arxiv", "cs.AI") == "2025-01-16"


class TestFunnelRuns:
    def test_start_and_update_funnel_run(self, store: PaperStore) -> None:
        config = {"hard_negative": {"min_abstract_length": 500}}
        run_id = store.start_funnel_run("2025-01-15", config_snapshot=config)
        assert run_id > 0

        store.update_funnel_run(
            run_id,
            stage1_input=100,
            stage2_output=50,
            status="completed",
        )

        with store._cursor() as cur:
            cur.execute("SELECT * FROM funnel_runs WHERE id = ?", (run_id,))
            row = dict(cur.fetchone())

        assert row["stage1_input"] == 100
        assert row["stage2_output"] == 50
        assert row["status"] == "completed"
        assert json.loads(row["config_snapshot"])["hard_negative"]["min_abstract_length"] == 500


class TestCountByStatus:
    def test_count_by_status(self, store: PaperStore) -> None:
        r1 = store.upsert_paper(_arxiv_paper(arxiv_id="2501.00001"))
        r2 = store.upsert_paper(_arxiv_paper(arxiv_id="2501.00002"))
        store.upsert_paper(_arxiv_paper(arxiv_id="2501.00003"))
        store.update_status(r1, "stage1_passed")
        store.update_status(r2, "recommended")
        counts = store.count_by_status()
        assert counts["fetched"] == 1
        assert counts["stage1_passed"] == 1
        assert counts["recommended"] == 1


class TestConcurrency:
    def test_concurrent_writes(self, tmp_path: Path) -> None:
        db_path = tmp_path / "concurrent.db"
        store = PaperStore(db_path)
        store.initialize()
        store.close()

        errors: list[Exception] = []

        def writer(offset: int) -> None:
            s = PaperStore(db_path)
            try:
                for i in range(10):
                    s.upsert_paper(_arxiv_paper(arxiv_id=f"2501.{offset * 10 + i:05d}", title=f"P {offset}-{i}"))
            except Exception as e:
                errors.append(e)
            finally:
                s.close()

        threads = [threading.Thread(target=writer, args=(j,)) for j in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

        # Reopen and verify
        store2 = PaperStore(db_path)
        store2.initialize()
        counts = store2.count_by_status()
        assert counts.get("fetched", 0) == 30
        store2.close()


class TestContextManager:
    """Tests for PaperStore __enter__/__exit__."""

    def test_enter_returns_self(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ctx_test.db"
        with PaperStore(db_path) as store:
            store.initialize()
            assert isinstance(store, PaperStore)
            # Should be usable inside the with block
            store.upsert_paper(_arxiv_paper(arxiv_id="2501.ctx01"))

    def test_exit_closes_connection(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ctx_close.db"
        store = PaperStore(db_path)
        store.initialize()
        store.__enter__()
        store.__exit__(None, None, None)
        # Connection should be closed; accessing cursor should raise
        with pytest.raises((sqlite3.ProgrammingError, sqlite3.OperationalError)):
            store._conn.execute("SELECT 1")

    def test_with_statement_closes_on_success(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ctx_success.db"
        with PaperStore(db_path) as store:
            store.initialize()
            store.upsert_paper(_arxiv_paper(arxiv_id="2501.ctx02"))
        # After with block, connection is closed
        with pytest.raises((sqlite3.ProgrammingError, sqlite3.OperationalError)):
            store._conn.execute("SELECT 1")

    def test_with_statement_closes_on_exception(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ctx_exc.db"
        with pytest.raises(ValueError), PaperStore(db_path) as store:
            store.initialize()
            raise ValueError("test error")
        with pytest.raises((sqlite3.ProgrammingError, sqlite3.OperationalError)):
            store._conn.execute("SELECT 1")

    def test_data_persists_across_contexts(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ctx_persist.db"
        with PaperStore(db_path) as store:
            store.initialize()
            store.upsert_paper(_arxiv_paper(arxiv_id="2501.persist"))
        with PaperStore(db_path) as store2:
            store2.initialize()
            papers = store2.get_papers_by_status("fetched")
            ids = [p["arxiv_id"] for p in papers]
            assert "2501.persist" in ids


class TestTransaction:
    """Tests for the transaction() batch-commit context manager."""

    def test_transaction_commits_all_operations(self, store: PaperStore) -> None:
        with store.transaction():
            store.upsert_paper(_arxiv_paper(arxiv_id="2501.00001"))
            store.upsert_paper(_arxiv_paper(arxiv_id="2501.00002"))
        assert store.count_by_status()["fetched"] == 2

    def test_transaction_rolls_back_on_error(self, store: PaperStore) -> None:
        with pytest.raises(RuntimeError, match="boom"), store.transaction():
            store.upsert_paper(_arxiv_paper(arxiv_id="2501.00001"))
            raise RuntimeError("boom")
        assert not store.paper_exists(arxiv_id="2501.00001")

    def test_transaction_reads_see_own_writes(self, store: PaperStore) -> None:
        # Same-connection reads inside the block see uncommitted writes, and
        # the re-entrant lock does not deadlock.
        with store.transaction():
            store.upsert_paper(_arxiv_paper())
            assert store.paper_exists(arxiv_id="2501.12345")

    def test_transaction_nested_joins_outer(self, store: PaperStore) -> None:
        with store.transaction():
            store.upsert_paper(_arxiv_paper(arxiv_id="2501.00001"))
            with store.transaction():
                store.upsert_paper(_arxiv_paper(arxiv_id="2501.00002"))
        assert store.count_by_status()["fetched"] == 2

    def test_upsert_papers_is_atomic(self, store: PaperStore, monkeypatch: pytest.MonkeyPatch) -> None:
        papers = [_arxiv_paper(arxiv_id="2501.00001"), _arxiv_paper(arxiv_id="2501.00002")]
        original = store.upsert_paper
        calls = 0

        def fail_second(raw: dict) -> int:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated mid-batch failure")
            return original(raw)

        monkeypatch.setattr(store, "upsert_paper", fail_second)
        with pytest.raises(RuntimeError, match="simulated mid-batch failure"):
            store.upsert_papers(papers)
        # The first insert rolled back together with the failed batch
        assert not store.paper_exists(arxiv_id="2501.00001")
        assert store.count_by_status() == {}


class TestRejectedStatus:
    """Rejected candidates carry a rejected_at timestamp for cross-day dedup."""

    def test_rejected_at_auto_set(self, store: PaperStore) -> None:
        row_id = store.upsert_paper(_arxiv_paper())
        store.update_status(row_id, "rejected", skip_reason="not_selected")
        paper = store.get_papers_by_status("rejected")[0]
        assert paper["rejected_at"], "rejected_at should be auto-set on status='rejected'"

    def test_rejected_at_explicit_honored(self, store: PaperStore) -> None:
        row_id = store.upsert_paper(_arxiv_paper())
        ts = "2025-01-01T00:00:00+00:00"
        store.update_status(row_id, "rejected", rejected_at=ts)
        paper = store.get_papers_by_status("rejected")[0]
        assert paper["rejected_at"] == ts

    def test_get_recently_rejected_ids_window(self, store: PaperStore) -> None:
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        recent = store.upsert_paper(_arxiv_paper(arxiv_id="2501.00001", title="Recent"))
        old = store.upsert_paper(_arxiv_paper(arxiv_id="2501.00002", title="Old"))
        other = store.upsert_paper(_arxiv_paper(arxiv_id="2501.00003", title="Other"))
        store.update_status(recent, "rejected", rejected_at=(now - timedelta(days=1)).isoformat())
        store.update_status(old, "rejected", rejected_at=(now - timedelta(days=20)).isoformat())
        store.update_status(other, "recommended")

        assert store.get_recently_rejected_ids(14) == {"2501.00001"}
        assert store.get_recently_rejected_ids(30) == {"2501.00001", "2501.00002"}

    def test_initialize_migrates_existing_db(self, tmp_path: Path) -> None:
        """A pre-v2 database (no rejected_at column) is migrated idempotently."""
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db_path))
        # Full v1 papers schema — every column except rejected_at
        conn.execute(
            """CREATE TABLE papers (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                arxiv_id                    TEXT UNIQUE,
                s2_id                       TEXT,
                doi                         TEXT,
                title                       TEXT NOT NULL,
                abstract                    TEXT,
                authors                     TEXT,
                affiliations                TEXT,
                categories                  TEXT,
                published_date              TEXT,
                venue                       TEXT,
                source                      TEXT NOT NULL DEFAULT 'arxiv',
                citation_count              INTEGER DEFAULT 0,
                influential_citation_count  INTEGER DEFAULT 0,
                pdf_url                     TEXT,
                url                         TEXT,
                status          TEXT NOT NULL DEFAULT 'fetched',
                is_historical   INTEGER NOT NULL DEFAULT 0,
                funnel_run_id   INTEGER,
                relevance_score REAL DEFAULT 0,
                best_domain     TEXT,
                domain_keywords TEXT,
                skip_reason        TEXT,
                llm_review_passed   INTEGER DEFAULT 0,
                llm_review_detail   TEXT,
                llm_novelty         REAL,
                llm_credibility     REAL,
                llm_depth           REAL,
                llm_rigor           REAL,
                llm_model           TEXT,
                recommendation_score  REAL DEFAULT 0,
                recommendation_reason TEXT,
                recommended_at        TEXT,
                fetched_at   TEXT NOT NULL DEFAULT (datetime('now')),
                processed_at TEXT
            )"""
        )
        conn.execute("INSERT INTO papers (arxiv_id, title) VALUES ('2501.99999', 'Legacy Paper')")
        conn.commit()
        conn.close()

        with PaperStore(db_path) as store:
            store.initialize()
            # Second initialize is a no-op (idempotent)
            store.initialize()
            cols = {row["name"] for row in store._conn.execute("PRAGMA table_info(papers)")}
            assert "rejected_at" in cols
            # Existing rows survive; new writes can use the column
            row_id = store.upsert_paper(_arxiv_paper())
            store.update_status(row_id, "rejected")
            assert store.get_recently_rejected_ids(14)
            assert store.paper_exists(arxiv_id="2501.99999")
