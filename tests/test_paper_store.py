"""Tests for PaperStore — SQLite-backed paper storage."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scholar_agent.engine.paper_store import PaperStore


@pytest.fixture
def store(tmp_path: Path) -> PaperStore:
    db_path = tmp_path / "test_papers.db"
    s = PaperStore(db_path)
    s.initialize()
    yield s
    s.close()


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
            row_id, "recommended",
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
        r3 = store.upsert_paper(_arxiv_paper(arxiv_id="2501.00003"))
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
                    s.upsert_paper(
                        _arxiv_paper(arxiv_id=f"2501.{offset * 10 + i:05d}", title=f"P {offset}-{i}")
                    )
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
