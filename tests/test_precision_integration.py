"""Integration tests for precision funnel path through daily_workflow and CLI."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scholar_agent.engine.academic.daily_workflow import (
    build_daily_note,
    generate_daily_recommendations,
    get_analyzed_paper_ids,
)
from scholar_agent.engine.paper_store import PaperStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _paper(title="Test Paper", abstract=None, arxiv_id="2501.00001", **kw):
    if abstract is None:
        abstract = (
            "We propose a novel deep learning method for reinforcement learning. "
            "Our approach uses a neural network architecture with attention mechanisms. "
            "Experiments on three benchmarks show 15% improvement over prior work. "
            "We provide theoretical convergence guarantees and detailed ablation studies."
        )
    p = {
        "arxiv_id": arxiv_id,
        "title": title,
        "summary": abstract,
        "authors": ["Alice"],
        "categories": ["cs.AI"],
        "source": "arxiv",
    }
    p.update(kw)
    return p


@pytest.fixture
def store(tmp_path: Path) -> PaperStore:
    s = PaperStore(tmp_path / "test.db")
    s.initialize()
    yield s
    s.close()


@pytest.fixture
def search_config():
    return {
        "research_domains": {
            "ai": {
                "keywords": ["deep learning", "neural network", "reinforcement learning"],
                "arxiv_categories": ["cs.AI", "cs.LG"],
            },
        },
        "excluded_keywords": [],
    }


@pytest.fixture
def precision_cfg():
    return {
        "enabled": True,
        "max_daily_recommendations": 3,
        "hard_negative": {
            "min_abstract_length": 100,
            "reject_title_patterns": ["survey of", "review of"],
            "reject_abstract_starters": ["we present a survey"],
        },
        "llm_review": {
            "required_passes": [
                "PROBLEM_DEFINED",
                "METHOD_SPECIFIC",
                "CONTRIBUTION_GENUISE",
                "NO_RED_FLAGS",
            ],
            "call_delay_seconds": 0,
            "max_survivors": 8,
        },
        "cross_comparison": {
            "max_candidates": 8,
        },
    }


def _mock_llm_for_funnel(selected_indices=None):
    """Mock call_llm that handles both stage 3 and stage 4 calls."""
    if selected_indices is None:
        selected_indices = [1]

    checks = [
        {"question": "PROBLEM_DEFINED", "passed": True, "evidence": "clear"},
        {"question": "METHOD_SPECIFIC", "passed": True, "evidence": "detailed"},
        {"question": "RESULTS_CONCRETE", "passed": True, "evidence": "numbers"},
        {"question": "CONTRIBUTION_GENUISE", "passed": True, "evidence": "novel"},
        {"question": "NO_RED_FLAGS", "passed": True, "evidence": "clean"},
    ]
    stage3_response = json.dumps({
        "checks": checks,
        "novelty": 4, "credibility": 4, "depth": 4, "rigor": 4,
    })

    selected = [{"index": i, "reason": f"Paper {i} is excellent", "priority": j + 1}
                for j, i in enumerate(selected_indices)]
    stage4_response = json.dumps({
        "selected": selected,
        "rationale": "Selected based on novelty and rigor.",
    })

    def _call(payload):
        user_msg = payload["messages"][-1]["content"]
        if "Select at most" in user_msg or "Candidates:" in user_msg:
            return {
                "raw_content": stage4_response,
                "model": "test",
                "usage": {"prompt_tokens": 200, "completion_tokens": 300, "total_tokens": 500},
            }
        return {
            "raw_content": stage3_response,
            "model": "test",
            "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
        }
    return _call


# ---------------------------------------------------------------------------
# generate_daily_recommendations — precision path
# ---------------------------------------------------------------------------


class TestPrecisionRecommendations:
    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_precision_path_returns_funnel_stats(
        self, tmp_path, search_config, precision_cfg
    ) -> None:
        mock_papers = [_paper(arxiv_id=f"2501.{i:05d}", title=f"Paper {i}") for i in range(3)]
        paper_notes_dir = str(tmp_path / "notes")
        db_path = tmp_path / "test.db"

        with (
            patch("scholar_agent.engine.academic.arxiv_search.query_arxiv", return_value=mock_papers),
            patch("scholar_agent.engine.scholar_config.get_paper_db_path", return_value=db_path),
            patch("scholar_agent.engine.synthesize_answer.call_llm") as mock_llm,
        ):
            mock_llm.side_effect = _mock_llm_for_funnel(selected_indices=[1, 2])

            result = generate_daily_recommendations(
                config=search_config,
                paper_notes_dir=paper_notes_dir,
                precision_config=precision_cfg,
                daily_config={"unified_pipeline": {"enabled": False}},
            )

        assert result.get("precision_funnel") is True
        assert "funnel_stats" in result
        assert result["funnel_stats"]["stage_counts"]["input"] == 3
        assert len(result["papers"]) == 2
        assert result["papers"][0]["track"] == "precision_funnel"

    def test_precision_disabled_falls_through(self, search_config) -> None:
        result = generate_daily_recommendations(
            config=search_config,
            paper_notes_dir="/tmp/nonexistent",
            dual_track=False,
            precision_config={"enabled": False},
            daily_config={"unified_pipeline": {"enabled": False}},
        )
        # Should hit single-track path (will try search_and_score, may fail)
        assert result.get("precision_funnel") is None


# ---------------------------------------------------------------------------
# build_daily_note — precision rendering
# ---------------------------------------------------------------------------


class TestPrecisionNote:
    def test_renders_funnel_stats(self, tmp_path: Path) -> None:
        papers = [
            {**_paper(), "recommendation_reason": "Novel architecture with strong results"},
        ]
        funnel_stats = {
            "stage_counts": {"input": 10, "stage1_passed": 6, "stage2_passed": 4, "stage3_passed": 2, "stage4_passed": 1},
            "llm_calls": 3,
            "llm_tokens": 800,
            "duration_seconds": 5.2,
        }

        note_path = build_daily_note(
            "2025-01-15",
            papers,
            str(tmp_path),
            language="zh",
            funnel_stats=funnel_stats,
        )

        content = Path(note_path).read_text()
        assert "精选推荐" in content
        assert "输入: 10" in content
        assert "推荐: 1 篇" in content
        assert "推荐理由" in content
        assert "precision_funnel: true" in content

    def test_renders_llm_scores_en(self, tmp_path: Path) -> None:
        papers = [
            {
                "title": "Scored Paper",
                "arxiv_id": "2501.00001",
                "authors": ["Alice"],
                "llm_novelty": 4,
                "llm_credibility": 5,
                "llm_depth": 3,
                "llm_rigor": 4,
            },
        ]
        funnel_stats = {
            "stage_counts": {"input": 5, "stage1_passed": 3, "stage3_passed": 1, "stage4_passed": 1},
        }

        note_path = build_daily_note(
            "2025-01-15",
            papers,
            str(tmp_path),
            language="en",
            funnel_stats=funnel_stats,
        )

        content = Path(note_path).read_text()
        assert "Precision Funnel" in content
        assert "novelty=4" in content
        assert "credibility=5" in content

    def test_no_papers_renders_empty_message(self, tmp_path: Path) -> None:
        funnel_stats = {
            "stage_counts": {"input": 10, "stage1_passed": 0},
        }

        note_path = build_daily_note(
            "2025-01-15",
            [],
            str(tmp_path),
            language="zh",
            funnel_stats=funnel_stats,
        )

        content = Path(note_path).read_text()
        assert "今日没有论文通过质量筛选" in content


# ---------------------------------------------------------------------------
# get_analyzed_paper_ids — SQLite-first path
# ---------------------------------------------------------------------------


class TestAnalyzedPaperIds:
    def test_sqlite_preferred_over_files(self, store: PaperStore, tmp_path: Path) -> None:
        # Insert a recommended paper into SQLite
        row_id = store.upsert_paper(_paper(arxiv_id="2501.99999", title="Recommended Paper"))
        store.update_status(row_id, "recommended")

        # Call with empty paper-notes dir
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()

        db_path = tmp_path / "test.db"
        with patch("scholar_agent.engine.scholar_config.get_paper_db_path", return_value=db_path):
            ids = get_analyzed_paper_ids(str(notes_dir))

        assert "2501.99999" in ids

    def test_falls_back_to_file_scan(self, tmp_path: Path) -> None:
        # No SQLite at non-existent path
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()

        # Create a fake paper note
        note = notes_dir / "test.md"
        note.write_text("---\npaper_id: arXiv:2501.12345\n---\nContent")

        with patch("scholar_agent.engine.scholar_config.get_paper_db_path", return_value=tmp_path / "nonexistent.db"):
            ids = get_analyzed_paper_ids(str(notes_dir))

        assert "2501.12345" in ids


# ---------------------------------------------------------------------------
# CLI parser — backfill and daily-process
# ---------------------------------------------------------------------------


class TestCLIParser:
    def test_backfill_defaults(self) -> None:
        from scholar_agent.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["backfill"])
        assert args.years == 3
        assert args.categories == "cs.AI,cs.LG,cs.CL,cs.CV"
        assert args.max_per_month == 2000
        assert args.format == "text"

    def test_backfill_custom(self) -> None:
        from scholar_agent.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["backfill", "--years", "1", "--categories", "cs.AI,cs.LG", "--format", "json"])
        assert args.years == 1
        assert args.categories == "cs.AI,cs.LG"
        assert args.format == "json"

    def test_daily_process_defaults(self) -> None:
        from scholar_agent.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["daily-process"])
        assert args.date == ""
        assert args.dry_run is False
        assert args.format == "text"

    def test_daily_process_dry_run(self) -> None:
        from scholar_agent.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["daily-process", "--date", "2025-06-01", "--dry-run", "--format", "json"])
        assert args.date == "2025-06-01"
        assert args.dry_run is True
        assert args.format == "json"


# ---------------------------------------------------------------------------
# query_arxiv_paginated — pagination logic
# ---------------------------------------------------------------------------


class TestPaginatedQuery:
    def test_single_page(self) -> None:
        from scholar_agent.engine.academic.arxiv_search import query_arxiv_paginated

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            '<entry><title>Paper 1</title><id>http://arxiv.org/abs/2501.00001v1</id>'
            '<summary>Abstract 1</summary><published>2025-01-01T00:00:00Z</published>'
            '<author><name>Alice</name></author>'
            '<link title="pdf" href="https://arxiv.org/pdf/2501.00001v1" rel="related" type="application/pdf"/>'
            '<category term="cs.AI"/></entry>'
            '</feed>'
        )

        with patch("scholar_agent.engine.academic.arxiv_search._with_retry", return_value=xml):
            papers = query_arxiv_paginated(
                categories=["cs.AI"],
                from_dt=datetime(2025, 1, 1),
                to_dt=datetime(2025, 1, 31),
                max_total=200,
            )

        assert len(papers) == 1
        assert papers[0]["title"] == "Paper 1"

    def test_stops_on_empty_page(self) -> None:
        from scholar_agent.engine.academic.arxiv_search import query_arxiv_paginated

        empty_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        )

        with patch("scholar_agent.engine.academic.arxiv_search._with_retry", return_value=empty_xml):
            papers = query_arxiv_paginated(
                categories=["cs.AI"],
                from_dt=datetime(2025, 1, 1),
                to_dt=datetime(2025, 1, 31),
            )

        assert papers == []

    def test_stops_on_network_failure(self) -> None:
        from scholar_agent.engine.academic.arxiv_search import query_arxiv_paginated

        with patch("scholar_agent.engine.academic.arxiv_search._with_retry", return_value=None):
            papers = query_arxiv_paginated(
                categories=["cs.AI"],
                from_dt=datetime(2025, 1, 1),
                to_dt=datetime(2025, 1, 31),
            )

        assert papers == []

    def test_multi_page(self) -> None:
        from scholar_agent.engine.academic.arxiv_search import query_arxiv_paginated

        def _make_xml(count, offset):
            entries = "".join(
                f'<entry><title>Paper {offset + i}</title><id>http://arxiv.org/abs/2501.{offset + i:05d}v1</id>'
                f'<summary>Abstract {offset + i}</summary><published>2025-01-01T00:00:00Z</published>'
                f'<author><name>Alice</name></author>'
                f'<link title="pdf" href="https://arxiv.org/pdf/2501.{offset + i:05d}v1" rel="related" type="application/pdf"/>'
                f'<category term="cs.AI"/></entry>'
                for i in range(count)
            )
            return (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<feed xmlns="http://www.w3.org/2005/Atom">'
                f'{entries}</feed>'
            )

        call_count = [0]

        def mock_retry(fn, url, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_xml(2, 0)  # full page of 2
            elif call_count[0] == 2:
                return _make_xml(1, 2)  # partial page of 1 → stops
            return _make_xml(0, 0)

        with patch("scholar_agent.engine.academic.arxiv_search._with_retry", side_effect=mock_retry):
            with patch("scholar_agent.engine.academic.arxiv_search.time.sleep"):
                papers = query_arxiv_paginated(
                    categories=["cs.AI"],
                    from_dt=datetime(2025, 1, 1),
                    to_dt=datetime(2025, 1, 31),
                    max_total=200,
                    page_size=2,
                    delay_seconds=0.01,
                )

        assert len(papers) == 3
        assert call_count[0] == 2  # second page was partial, stops
