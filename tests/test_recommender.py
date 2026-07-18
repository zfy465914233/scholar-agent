"""Tests for the public recommendation engine entry point.

Covers generate_recommendations end-to-end (mocked providers + LLM), the
stable output schema, domain priority weighting, the cross-day reject-dedup
window, LLM-degradation warnings, and funnel_runs persistence.
"""

from __future__ import annotations

import contextlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from unittest.mock import patch

from scholar_agent.engine.academic.recommender import (
    SCHEMA_VERSION,
    generate_recommendations,
)
from scholar_agent.engine.paper_store import PaperStore

if TYPE_CHECKING:
    from pathlib import Path

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


def _full_config(**unified_overrides):
    """Full .scholar.json-shaped config with unified pipeline enabled."""
    uc = {"enabled": True, "max_daily_recommendations": 3, "reject_dedup_days": 14}
    uc.update(unified_overrides)
    return {
        "academic": {
            "research_interests": {
                "research_domains": {
                    "ai": {
                        "keywords": ["deep learning", "neural network", "reinforcement learning"],
                        "arxiv_categories": ["cs.AI", "cs.LG"],
                    },
                },
                "excluded_keywords": [],
            },
            "unified_pipeline": uc,
        }
    }


def _mock_llm_response(selected=None):
    if selected is None:
        selected = [{"index": 1, "reason": "Novel approach", "novelty": 4, "credibility": 5}]
    return {
        "raw_content": json.dumps({"selected": selected, "rationale": "Best papers."}),
        "usage": {"total_tokens": 800},
    }


@contextlib.contextmanager
def _patched_providers(tmp_path, arxiv_papers, s2_papers=()):
    """Patch network providers + analyzed-ids + the paper DB location."""
    with (
        patch("scholar_agent.engine.academic.arxiv_search.query_arxiv", return_value=list(arxiv_papers)),
        patch("scholar_agent.engine.academic.arxiv_search.collect_hot_papers", return_value=list(s2_papers)),
        patch("scholar_agent.engine.academic.daily_workflow.get_analyzed_paper_ids", return_value=set()),
        patch("scholar_agent.engine.scholar_config.get_paper_db_path", return_value=tmp_path / "papers.db"),
    ):
        yield


# ---------------------------------------------------------------------------
# End-to-end + schema stability
# ---------------------------------------------------------------------------


class TestGenerateRecommendationsE2E:
    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_end_to_end_with_llm(self, tmp_path):
        papers = [_paper(arxiv_id=f"2501.{i:05d}", title=f"Paper {i}") for i in range(5)]

        with (
            _patched_providers(tmp_path, papers),
            patch("scholar_agent.engine.synthesize_answer.call_llm", return_value=_mock_llm_response()),
        ):
            result = generate_recommendations(
                config=_full_config(),
                date="2025-01-15",
                paper_notes_dir=str(tmp_path / "notes"),
            )

        assert result["schema_version"] == SCHEMA_VERSION
        assert result["date"] == "2025-01-15"
        assert result["unified_pipeline"] is True
        assert len(result["papers"]) == 1
        assert result["papers"][0]["track"] == "unified_pipeline"
        assert result["warnings"] == []
        assert result["stats"]["llm_calls"] == 1
        assert result["stats"]["arxiv_fetched"] == 5
        # LLM-selected paper carries the LLM sub-scores
        assert result["papers"][0]["scores"]["llm_novelty"] == 4
        assert result["papers"][0]["scores"]["llm_credibility"] == 5

    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_schema_stability(self, tmp_path):
        papers = [
            _paper(arxiv_id="2501.00001", published_date=datetime(2025, 1, 14)),
            _paper(arxiv_id="2501.00002", title="Another Paper"),
        ]

        with (
            _patched_providers(tmp_path, papers),
            patch("scholar_agent.engine.synthesize_answer.call_llm", return_value=_mock_llm_response()),
        ):
            result = generate_recommendations(
                config=_full_config(),
                date="2025-01-15",
                paper_notes_dir=str(tmp_path / "notes"),
            )

        # Top-level schema keys
        for key in ("schema_version", "date", "papers", "stats", "warnings", "skipped", "total_found"):
            assert key in result, f"missing top-level key: {key}"

        # Per-paper schema keys
        required = {
            "arxiv_id",
            "title",
            "abstract",
            "authors",
            "url",
            "published_date",
            "categories",
            "scores",
            "recommendation_reason",
            "track",
            "domain",
        }
        for p in result["papers"]:
            assert required.issubset(p.keys()), f"missing paper keys: {required - p.keys()}"
            assert "fit" in p["scores"]
            assert "recommendation" in p["scores"]

        # datetime values are normalized — the whole result is JSON-safe
        encoded = json.dumps(result, ensure_ascii=False)
        assert json.loads(encoded)["schema_version"] == SCHEMA_VERSION
        assert isinstance(result["papers"][0]["published_date"], str)

    def test_empty_fetch_returns_stable_schema(self, tmp_path):
        with (
            _patched_providers(tmp_path, []),
            patch.dict(os.environ, {}, clear=True),
        ):
            os.environ.pop("LLM_API_KEY", None)
            result = generate_recommendations(
                config=_full_config(),
                date="2025-01-15",
                paper_notes_dir=str(tmp_path / "notes"),
            )

        assert result["papers"] == []
        assert result["schema_version"] == SCHEMA_VERSION
        assert result["stats"]["candidates"] == 0
        json.dumps(result)


# ---------------------------------------------------------------------------
# LLM degradation warnings
# ---------------------------------------------------------------------------


class TestLLMDegradationWarning:
    def test_warning_without_api_key(self, tmp_path):
        papers = [_paper(arxiv_id=f"2501.{i:05d}", title=f"Paper {i}") for i in range(3)]

        with (
            _patched_providers(tmp_path, papers),
            patch.dict(os.environ, {}, clear=True),
        ):
            os.environ.pop("LLM_API_KEY", None)
            result = generate_recommendations(
                config=_full_config(),
                date="2025-01-15",
                paper_notes_dir=str(tmp_path / "notes"),
            )

        assert any("LLM_API_KEY" in w for w in result["warnings"])
        # Heuristic fallback still returns papers with the stable scores contract
        assert result["papers"], "heuristic fallback should still recommend papers"
        assert result["stats"]["llm_calls"] == 0
        for p in result["papers"]:
            assert "recommendation" in p["scores"]

    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_warning_on_llm_failure(self, tmp_path):
        papers = [_paper(arxiv_id="2501.00001")]

        with (
            _patched_providers(tmp_path, papers),
            patch("scholar_agent.engine.synthesize_answer.call_llm", side_effect=Exception("API down")),
        ):
            result = generate_recommendations(
                config=_full_config(),
                date="2025-01-15",
                paper_notes_dir=str(tmp_path / "notes"),
            )

        assert any("heuristic" in w.lower() for w in result["warnings"])


# ---------------------------------------------------------------------------
# Domain priority weighting
# ---------------------------------------------------------------------------


class TestPriorityWeighting:
    def test_priority_scales_domain_fit(self):
        from scholar_agent.engine.academic.scoring import PaperScorer

        paper = {"title": "deep learning and neural network methods", "summary": "", "categories": []}

        weighted = PaperScorer(
            domains={
                "low": {"keywords": ["deep learning"], "arxiv_categories": [], "priority": 1},
                "high": {"keywords": ["neural network"], "arxiv_categories": [], "priority": 4},
            }
        )
        _fit, domain, _kws = weighted._fit(paper)
        # Equal raw points (1 title hit each) — the high-priority domain wins
        assert domain == "high"

    def test_low_priority_domain_discounted(self):
        from scholar_agent.engine.academic.scoring import PaperScorer

        paper = {"title": "A deep learning method", "summary": "", "categories": []}

        plain = PaperScorer(domains={"ai": {"keywords": ["deep learning"], "arxiv_categories": []}})
        discounted = PaperScorer(
            domains={
                "ai": {"keywords": ["deep learning"], "arxiv_categories": [], "priority": 1},
                "other": {"keywords": ["graphics"], "arxiv_categories": [], "priority": 4},
            }
        )
        fit_plain, _, _ = plain._fit(paper)
        fit_discounted, domain, _ = discounted._fit(paper)
        assert domain == "ai"
        assert 0 < fit_discounted < fit_plain

    def test_no_priority_unchanged(self):
        from scholar_agent.engine.academic.scoring import PaperScorer

        paper = {"title": "A deep learning method", "summary": "", "categories": []}
        a = PaperScorer(domains={"ai": {"keywords": ["deep learning"], "arxiv_categories": []}})
        b = PaperScorer(
            domains={
                "ai": {"keywords": ["deep learning"], "arxiv_categories": [], "priority": 1.0},
            }
        )
        assert a._fit(paper) == b._fit(paper)

    def test_priority_still_capped(self):
        from scholar_agent.engine.academic.scoring import PaperScorer

        scorer = PaperScorer(
            domains={
                "ai": {
                    "keywords": ["deep learning", "neural network", "reinforcement learning"],
                    "arxiv_categories": ["cs.AI"],
                    "priority": 10,
                },
                "other": {"keywords": ["graphics"], "arxiv_categories": [], "priority": 1},
            }
        )
        paper = {
            "title": "deep learning neural network reinforcement learning",
            "summary": "deep learning neural network reinforcement learning " * 5,
            "categories": ["cs.AI"],
        }
        fit, _, _ = scorer._fit(paper)
        assert fit <= 5.0  # _CEILING


# ---------------------------------------------------------------------------
# Cross-day reject dedup
# ---------------------------------------------------------------------------


class TestRejectDedupWindow:
    def _seed_rejected(self, db_path: Path) -> None:
        """One paper rejected yesterday, one rejected 20 days ago."""
        now = datetime.now(timezone.utc)
        with PaperStore(db_path) as store:
            store.initialize()
            rid_recent = store.upsert_paper(_paper(arxiv_id="2501.00011", title="Rejected Recently"))
            rid_old = store.upsert_paper(_paper(arxiv_id="2501.00022", title="Rejected Long Ago"))
            store.update_status(rid_recent, "rejected", rejected_at=(now - timedelta(days=1)).isoformat())
            store.update_status(rid_old, "rejected", rejected_at=(now - timedelta(days=20)).isoformat())

    def test_store_window_query(self, tmp_path):
        db_path = tmp_path / "papers.db"
        self._seed_rejected(db_path)
        with PaperStore(db_path) as store:
            store.initialize()
            assert store.get_recently_rejected_ids(14) == {"2501.00011"}
            assert store.get_recently_rejected_ids(30) == {"2501.00011", "2501.00022"}

    def test_pipeline_respects_window(self, tmp_path):
        db_path = tmp_path / "papers.db"
        self._seed_rejected(db_path)
        fetched = [
            _paper(arxiv_id="2501.00011", title="Rejected Recently"),
            _paper(arxiv_id="2501.00022", title="Rejected Long Ago"),
            _paper(arxiv_id="2501.00033", title="Fresh Paper"),
        ]

        with (
            patch("scholar_agent.engine.academic.arxiv_search.query_arxiv", return_value=fetched),
            patch("scholar_agent.engine.academic.arxiv_search.collect_hot_papers", return_value=[]),
            patch("scholar_agent.engine.academic.daily_workflow.get_analyzed_paper_ids", return_value=set()),
            patch("scholar_agent.engine.scholar_config.get_paper_db_path", return_value=db_path),
            patch.dict(os.environ, {}, clear=True),
        ):
            os.environ.pop("LLM_API_KEY", None)
            result = generate_recommendations(
                config=_full_config(),
                date="2025-01-15",
                paper_notes_dir=str(tmp_path / "notes"),
            )

        ids = {p["arxiv_id"] for p in result["papers"]}
        # Rejected yesterday → still excluded; rejected 20 days ago → re-eligible
        assert "2501.00011" not in ids
        assert result["total_found"] == 2  # 3 fetched - 1 windowed rejection
        assert "2501.00022" in ids or "2501.00033" in ids

    def test_window_disabled_with_zero(self, tmp_path):
        db_path = tmp_path / "papers.db"
        self._seed_rejected(db_path)
        fetched = [_paper(arxiv_id="2501.00011", title="Rejected Recently")]

        with (
            patch("scholar_agent.engine.academic.arxiv_search.query_arxiv", return_value=fetched),
            patch("scholar_agent.engine.academic.arxiv_search.collect_hot_papers", return_value=[]),
            patch("scholar_agent.engine.academic.daily_workflow.get_analyzed_paper_ids", return_value=set()),
            patch("scholar_agent.engine.scholar_config.get_paper_db_path", return_value=db_path),
            patch.dict(os.environ, {}, clear=True),
        ):
            os.environ.pop("LLM_API_KEY", None)
            result = generate_recommendations(
                config=_full_config(reject_dedup_days=0),
                date="2025-01-15",
                paper_notes_dir=str(tmp_path / "notes"),
            )

        assert result["total_found"] == 1


# ---------------------------------------------------------------------------
# funnel_runs persistence
# ---------------------------------------------------------------------------


class TestFunnelRunPersistence:
    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_funnel_run_row_written_with_stats(self, tmp_path):
        db_path = tmp_path / "papers.db"
        papers = [_paper(arxiv_id=f"2501.{i:05d}", title=f"Paper {i}") for i in range(4)]

        with (
            _patched_providers(tmp_path, papers),
            patch("scholar_agent.engine.synthesize_answer.call_llm", return_value=_mock_llm_response()),
        ):
            result = generate_recommendations(
                config=_full_config(),
                date="2025-01-15",
                paper_notes_dir=str(tmp_path / "notes"),
            )

        with PaperStore(db_path) as store:
            store.initialize()
            with store._cursor() as cur:
                runs = cur.execute("SELECT * FROM funnel_runs").fetchall()
        assert len(runs) == 1
        run = runs[0]
        assert run["run_date"] == "2025-01-15"
        assert run["status"] == "success"
        assert run["stage1_input"] == 4  # 4 arXiv + 0 S2
        assert run["recommended"] == len(result["papers"])
        assert run["llm_calls"] == 1
        assert run["llm_tokens"] == 800
        assert run["duration_seconds"] >= 0

    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_checkpoints_written(self, tmp_path):
        db_path = tmp_path / "papers.db"
        papers = [_paper()]

        with (
            _patched_providers(tmp_path, papers),
            patch("scholar_agent.engine.synthesize_answer.call_llm", return_value=_mock_llm_response()),
        ):
            generate_recommendations(
                config=_full_config(),
                date="2025-01-15",
                paper_notes_dir=str(tmp_path / "notes"),
            )

        with PaperStore(db_path) as store:
            store.initialize()
            assert store.get_checkpoint("unified_arxiv") == "2025-01-15"
            assert store.get_checkpoint("unified_s2") == "2025-01-15"
