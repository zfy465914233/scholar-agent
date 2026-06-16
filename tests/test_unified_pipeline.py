"""Tests for the unified lightweight recommendation pipeline."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from scholar_agent.engine.academic.unified_pipeline import (
    _parse_batch_response,
    batch_llm_select,
    heuristic_pre_filter,
    refine_queries,
    run_unified_pipeline,
)

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


def _config():
    return {
        "research_domains": {
            "ai": {
                "keywords": ["deep learning", "neural network", "reinforcement learning"],
                "arxiv_categories": ["cs.AI", "cs.LG"],
            },
        },
        "excluded_keywords": [],
    }


# ---------------------------------------------------------------------------
# refine_queries
# ---------------------------------------------------------------------------


class TestRefineQueries:
    def test_extracts_categories_and_phrases(self):
        cats, phrases = refine_queries(_config())
        assert "cs.AI" in cats
        assert "cs.LG" in cats
        assert len(phrases) >= 1
        assert "deep learning" in phrases[0].lower()

    def test_empty_config_uses_defaults(self):
        cats, phrases = refine_queries({})
        assert len(cats) >= 2
        assert len(phrases) >= 1

    def test_multiple_domains(self):
        config = {
            "research_domains": {
                "ai": {"keywords": ["deep learning"], "arxiv_categories": ["cs.AI"]},
                "nlp": {"keywords": ["language model"], "arxiv_categories": ["cs.CL"]},
            },
        }
        cats, phrases = refine_queries(config)
        assert "cs.AI" in cats
        assert "cs.CL" in cats
        assert len(phrases) == 2


# ---------------------------------------------------------------------------
# heuristic_pre_filter
# ---------------------------------------------------------------------------


class TestHeuristicPreFilter:
    def test_filters_by_relevance(self):
        relevant = _paper(title="Deep Reinforcement Learning for Robotics")
        irrelevant = _paper(
            title="A Survey of 3D Reconstruction Methods",
            abstract="We present a survey of 3D reconstruction techniques.",
            arxiv_id="2501.00002",
        )
        result = heuristic_pre_filter([relevant, irrelevant], _config())
        ids = [p["arxiv_id"] for p in result]
        assert "2501.00001" in ids
        # Relevant paper should rank above survey red-flag paper
        if "2501.00002" in ids:
            assert ids.index("2501.00001") < ids.index("2501.00002")

    def test_max_candidates(self):
        papers = [_paper(arxiv_id=f"2501.{i:05d}", title=f"Paper {i}") for i in range(20)]
        result = heuristic_pre_filter(papers, _config(), max_candidates=5)
        assert len(result) == 5

    def test_innovation_signals_boost(self):
        innovative = _paper(
            title="Breakthrough in Neural Architecture Search",
            abstract=(
                "We present a novel unified framework that achieves state-of-the-art results. "
                "Our method outperforms all baselines by 20% on three benchmarks. "
                "We provide theoretical proofs and convergence analysis."
            ),
            arxiv_id="2501.00999",
        )
        plain = _paper(
            title="A Method for Training",
            abstract="We describe a method for training models on data.",
            arxiv_id="2501.00998",
        )
        result = heuristic_pre_filter([innovative, plain], _config())
        # Innovative paper should rank higher
        assert result[0]["arxiv_id"] == "2501.00999"

    def test_short_abstract_penalized(self):
        short = _paper(
            abstract="Short abstract.",
            arxiv_id="2501.00997",
        )
        long_enough = _paper(arxiv_id="2501.00996")
        result = heuristic_pre_filter([short, long_enough], _config())
        ids = [p["arxiv_id"] for p in result]
        # Short abstract gets heavy penalty, may still pass if relevance is high
        # but should rank below long_enough
        if len(result) > 1:
            assert ids.index("2501.00996") < ids.index("2501.00997")


# ---------------------------------------------------------------------------
# _parse_batch_response
# ---------------------------------------------------------------------------


class TestParseBatchResponse:
    def test_valid_json(self):
        raw = json.dumps(
            {
                "selected": [{"index": 1, "reason": "Excellent", "novelty": 4, "credibility": 5}],
                "rationale": "Strong paper.",
            }
        )
        result = _parse_batch_response(raw)
        assert len(result["selected"]) == 1
        assert result["selected"][0]["index"] == 1

    def test_markdown_fences(self):
        raw = '```json\n{"selected": [{"index": 2, "reason": "Good"}], "rationale": "OK"}\n```'
        result = _parse_batch_response(raw)
        assert len(result["selected"]) == 1

    def test_invalid_json(self):
        result = _parse_batch_response("not json at all")
        assert result["selected"] == []

    def test_empty_response(self):
        result = _parse_batch_response("")
        assert result["selected"] == []


# ---------------------------------------------------------------------------
# batch_llm_select
# ---------------------------------------------------------------------------


class TestBatchLLMSelect:
    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_selects_from_candidates(self):
        candidates = [_paper(arxiv_id=f"2501.{i:05d}", title=f"Paper {i}", _heuristic_score=float(i)) for i in range(5)]

        mock_response = {
            "raw_content": json.dumps(
                {
                    "selected": [
                        {"index": 3, "reason": "Novel approach", "novelty": 4, "credibility": 5},
                        {"index": 5, "reason": "Strong results", "novelty": 5, "credibility": 4},
                    ],
                    "rationale": "Top 2 papers.",
                }
            ),
            "usage": {"total_tokens": 500},
        }

        with patch("scholar_agent.engine.synthesize_answer.call_llm", return_value=mock_response):
            selected, calls, tokens = batch_llm_select(candidates, max_select=3)

        assert len(selected) == 2
        assert selected[0]["arxiv_id"] == "2501.00002"  # index 3 → 0-indexed 2
        assert selected[0]["recommendation_reason"] == "Novel approach"
        assert calls == 1
        assert tokens == 500

    def test_fallback_without_api_key(self):
        candidates = [
            _paper(arxiv_id="2501.00001", _heuristic_score=3.0),
            _paper(arxiv_id="2501.00002", _heuristic_score=2.0),
        ]
        with patch.dict(os.environ, {}, clear=True):
            # Remove LLM_API_KEY
            os.environ.pop("LLM_API_KEY", None)
            selected, calls, _tokens = batch_llm_select(candidates, max_select=2)

        assert len(selected) == 2
        assert calls == 0

    def test_empty_candidates(self):
        selected, calls, _tokens = batch_llm_select([], max_select=3)
        assert selected == []
        assert calls == 0

    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_llm_failure_falls_back(self):
        candidates = [_paper(arxiv_id="2501.00001", _heuristic_score=3.0)]

        with patch("scholar_agent.engine.synthesize_answer.call_llm", side_effect=Exception("API error")):
            selected, calls, _tokens = batch_llm_select(candidates, max_select=3)

        assert len(selected) == 1
        assert calls == 0  # fallback means 0 LLM calls counted

    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_llm_selects_none_falls_back(self):
        candidates = [_paper(arxiv_id="2501.00001", _heuristic_score=3.0)]

        mock_response = {
            "raw_content": json.dumps({"selected": [], "rationale": "None meet the bar."}),
            "usage": {"total_tokens": 200},
        }

        with patch("scholar_agent.engine.synthesize_answer.call_llm", return_value=mock_response):
            selected, _calls, _tokens = batch_llm_select(candidates, max_select=3)

        # Falls back to heuristic top-3
        assert len(selected) == 1


# ---------------------------------------------------------------------------
# run_unified_pipeline (integration)
# ---------------------------------------------------------------------------


class TestRunUnifiedPipeline:
    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_end_to_end(self, tmp_path):
        mock_arxiv = [_paper(arxiv_id=f"2501.{i:05d}", title=f"Paper {i}") for i in range(5)]
        mock_s2 = [
            {
                "arxiv_id": "2501.00100",
                "title": "S2 Paper",
                "abstract": "Novel deep learning method with strong results.",
                "authors": [{"name": "Bob"}],
                "influentialCitationCount": 10,
                "source": "s2_graph",
            }
        ]
        paper_notes_dir = str(tmp_path / "notes")

        mock_llm_response = {
            "raw_content": json.dumps(
                {
                    "selected": [
                        {"index": 1, "reason": "Novel approach", "novelty": 4, "credibility": 5},
                    ],
                    "rationale": "Best paper.",
                }
            ),
            "usage": {"total_tokens": 800},
        }

        with (
            patch("scholar_agent.engine.academic.arxiv_search.query_arxiv", return_value=mock_arxiv),
            patch("scholar_agent.engine.academic.arxiv_search.collect_hot_papers", return_value=mock_s2),
            patch("scholar_agent.engine.academic.daily_workflow.get_analyzed_paper_ids", return_value=set()),
            patch("scholar_agent.engine.synthesize_answer.call_llm", return_value=mock_llm_response),
            patch("scholar_agent.engine.scholar_config.get_paper_db_path", return_value=tmp_path / "test.db"),
        ):
            result = run_unified_pipeline(
                config=_config(),
                paper_notes_dir=paper_notes_dir,
            )

        assert result["unified_pipeline"] is True
        assert len(result["papers"]) == 1
        assert result["papers"][0]["track"] == "unified_pipeline"
        assert result["stats"]["llm_calls"] == 1
        assert result["stats"]["candidates"] <= 15

    def test_empty_fetch(self, tmp_path):
        paper_notes_dir = str(tmp_path / "notes")

        with (
            patch("scholar_agent.engine.academic.arxiv_search.query_arxiv", return_value=[]),
            patch("scholar_agent.engine.academic.arxiv_search.collect_hot_papers", return_value=[]),
            patch("scholar_agent.engine.academic.daily_workflow.get_analyzed_paper_ids", return_value=set()),
        ):
            result = run_unified_pipeline(
                config=_config(),
                paper_notes_dir=paper_notes_dir,
            )

        assert result["unified_pipeline"] is True
        assert result["papers"] == []
        assert result["stats"]["candidates"] == 0


# ---------------------------------------------------------------------------
# daily_workflow routing
# ---------------------------------------------------------------------------


class TestUnifiedRouting:
    def test_unified_path_taken_by_default(self):
        from scholar_agent.engine.academic.daily_workflow import generate_daily_recommendations

        config = _config()
        with patch(
            "scholar_agent.engine.academic.daily_workflow._generate_unified",
            return_value={"papers": [], "date": "2025-01-15", "unified_pipeline": True},
        ) as mock_unified:
            result = generate_daily_recommendations(
                config=config,
                paper_notes_dir="/tmp/test",
            )
            mock_unified.assert_called_once()
            assert result.get("unified_pipeline") is True

    def test_unified_disabled_falls_to_legacy(self):
        from scholar_agent.engine.academic.daily_workflow import generate_daily_recommendations

        config = _config()
        with patch(
            "scholar_agent.engine.academic.daily_workflow._generate_single_track",
            return_value={"papers": [], "date": "2025-01-15"},
        ):
            result = generate_daily_recommendations(
                config=config,
                paper_notes_dir="/tmp/test",
                dual_track=False,
                daily_config={"unified_pipeline": {"enabled": False}},
                precision_config={"enabled": False},
            )
            assert result.get("unified_pipeline") is None


# ---------------------------------------------------------------------------
# build_daily_note — unified pipeline rendering
# ---------------------------------------------------------------------------


class TestUnifiedDailyNote:
    def test_renders_pipeline_stats_zh(self, tmp_path: Path) -> None:
        from scholar_agent.engine.academic.daily_workflow import build_daily_note

        papers = [
            {**_paper(), "recommendation_reason": "Novel architecture with strong results"},
        ]
        pipeline_stats = {
            "arxiv_fetched": 50,
            "s2_fetched": 10,
            "candidates": 8,
            "llm_calls": 1,
            "duration_seconds": 4.2,
        }

        note_path = build_daily_note(
            "2025-01-15",
            papers,
            str(tmp_path),
            language="zh",
            pipeline_stats=pipeline_stats,
        )

        content = Path(note_path).read_text(encoding="utf-8")
        assert "unified_pipeline: true" in content
        assert "今日精选" in content
        assert "arXiv: 50" in content
        assert "推荐: 1 篇" in content
        assert "推荐理由" in content

    def test_renders_pipeline_stats_en(self, tmp_path: Path) -> None:
        from scholar_agent.engine.academic.daily_workflow import build_daily_note

        papers = [
            {
                "title": "Scored Paper",
                "arxiv_id": "2501.00001",
                "authors": ["Alice"],
                "recommendation_reason": "Novel method",
                "llm_novelty": 4,
                "llm_credibility": 5,
            },
        ]
        pipeline_stats = {
            "arxiv_fetched": 30,
            "s2_fetched": 5,
            "candidates": 6,
            "llm_calls": 1,
            "duration_seconds": 3.5,
        }

        note_path = build_daily_note(
            "2025-01-15",
            papers,
            str(tmp_path),
            language="en",
            pipeline_stats=pipeline_stats,
        )

        content = Path(note_path).read_text(encoding="utf-8")
        assert "Today's Top Papers" in content
        assert "arXiv: 30 + S2: 5" in content
        assert "Recommended: 1" in content

    def test_no_papers_renders_empty_message(self, tmp_path: Path) -> None:
        from scholar_agent.engine.academic.daily_workflow import build_daily_note

        pipeline_stats = {
            "arxiv_fetched": 20,
            "s2_fetched": 3,
            "candidates": 0,
            "llm_calls": 0,
            "duration_seconds": 2.0,
        }

        note_path = build_daily_note(
            "2025-01-15",
            [],
            str(tmp_path),
            language="zh",
            pipeline_stats=pipeline_stats,
        )

        content = Path(note_path).read_text(encoding="utf-8")
        assert "今日没有论文通过质量筛选" in content


# ---------------------------------------------------------------------------
# Phase 2: soft recency preference + full-history S2 (no hard age cutoff)
# ---------------------------------------------------------------------------


class TestConcurrentFetchS2FullHistory:
    """The daily feed must search the full S2 corpus, not a 365-day window."""

    def test_s2_uses_time_agnostic(self):
        from scholar_agent.engine.academic.unified_pipeline import concurrent_fetch

        with (
            patch("scholar_agent.engine.academic.arxiv_search.query_arxiv", return_value=[]),
            patch("scholar_agent.engine.academic.arxiv_search.collect_hot_papers", return_value=[]) as mock_s2,
        ):
            concurrent_fetch(arxiv_categories=["cs.AI"], config=_config())

        _, kwargs = mock_s2.call_args
        assert kwargs.get("time_agnostic") is True


class TestHeuristicSoftRecency:
    """heuristic_pre_filter applies a soft recency preference that favors new
    work but never hard-excludes classic papers by age."""

    def test_new_paper_preferred_over_identical_old(self):
        from datetime import datetime, timedelta

        now = datetime.now()
        shared = dict(
            title="Deep Reinforcement Learning Method",
            abstract=(
                "We propose a novel deep learning method for reinforcement learning "
                "using neural networks. State-of-the-art results on benchmarks with "
                "convergence proofs and ablation studies."
            ),
        )
        new = _paper(arxiv_id="2501.00001", published_date=now - timedelta(days=1), **shared)
        old = _paper(arxiv_id="2501.00002", published_date=now - timedelta(days=365 * 4), **shared)

        result = heuristic_pre_filter([new, old], _config())
        ids = [p["arxiv_id"] for p in result]
        # both survive — the old paper is NOT excluded by age
        assert "2501.00001" in ids
        assert "2501.00002" in ids
        # identical quality => newer ranks higher (soft recency preference)
        assert ids.index("2501.00001") < ids.index("2501.00002")
        scores = {p["arxiv_id"]: p["_heuristic_score"] for p in result}
        assert scores["2501.00001"] > scores["2501.00002"]

    def test_old_classic_still_surfaces_when_strong(self):
        """A 4-year-old highly-fit paper must not be hard-excluded by age."""
        from datetime import datetime, timedelta

        old_classic = _paper(
            arxiv_id="1706.03762",
            title="Attention Is All You Need: deep learning transformer",
            abstract=(
                "We propose a novel deep learning architecture based on attention for "
                "reinforcement learning. State-of-the-art results on benchmarks with "
                "strong convergence analysis and ablation studies."
            ),
            published_date=datetime.now() - timedelta(days=365 * 4),
        )
        result = heuristic_pre_filter([old_classic], _config())
        assert len(result) == 1  # not excluded despite being 4 years old
