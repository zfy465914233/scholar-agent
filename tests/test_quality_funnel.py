"""Tests for QualityFunnel — 4-stage precision pipeline."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scholar_agent.engine.academic.quality_funnel import (
    FunnelResult,
    QualityFunnel,
    _parse_stage3_response,
    _parse_stage4_response,
)
from scholar_agent.engine.paper_store import PaperStore


@pytest.fixture
def store(tmp_path: Path) -> PaperStore:
    s = PaperStore(tmp_path / "test.db")
    s.initialize()
    yield s
    s.close()


@pytest.fixture
def config() -> dict:
    return {
        "research_domains": {
            "ai": {
                "keywords": ["deep learning", "neural network", "reinforcement learning"],
                "arxiv_categories": ["cs.AI", "cs.LG"],
            },
        },
        "excluded_keywords": [],
        "precision_funnel": {
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
        },
    }


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


def _store_papers(store: PaperStore, papers: list[dict]) -> list[dict]:
    """Upsert papers and attach _db_id for funnel tracking."""
    result = []
    for p in papers:
        row_id = store.upsert_paper(p)
        p["_db_id"] = row_id
        result.append(p)
    return result


def _mock_llm_stage3(
    all_passed=True, novelty=4, credibility=4, depth=4, rigor=4
):
    """Create a mock call_llm that returns valid Stage 3 responses."""
    checks = [
        {"question": "PROBLEM_DEFINED", "passed": all_passed, "evidence": "clear"},
        {"question": "METHOD_SPECIFIC", "passed": all_passed, "evidence": "detailed"},
        {"question": "RESULTS_CONCRETE", "passed": True, "evidence": "numbers"},
        {"question": "CONTRIBUTION_GENUISE", "passed": all_passed, "evidence": "novel"},
        {"question": "NO_RED_FLAGS", "passed": all_passed, "evidence": "clean"},
    ]
    response = json.dumps({
        "checks": checks,
        "novelty": novelty,
        "credibility": credibility,
        "depth": depth,
        "rigor": rigor,
    })

    def _call(payload):
        return {
            "raw_content": response,
            "model": "test",
            "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
        }
    return _call


def _mock_llm_stage4(selected_indices=None):
    """Create a mock call_llm for Stage 4."""
    if selected_indices is None:
        selected_indices = [1]

    selected = [{"index": i, "reason": f"Paper {i} is excellent", "priority": j + 1}
                for j, i in enumerate(selected_indices)]
    response = json.dumps({
        "selected": selected,
        "rationale": "Selected based on novelty and rigor.",
    })

    call_count = [0]
    stage3_fn = _mock_llm_stage3()

    def _call(payload):
        call_count[0] += 1
        # First N calls are Stage 3, last is Stage 4
        user_msg = payload["messages"][-1]["content"]
        if "Select at most" in user_msg or "Candidates:" in user_msg:
            return {
                "raw_content": response,
                "model": "test",
                "usage": {"prompt_tokens": 200, "completion_tokens": 300, "total_tokens": 500},
            }
        return stage3_fn(payload)

    return _call


# ---------------------------------------------------------------------------
# Stage 1 tests
# ---------------------------------------------------------------------------


class TestStage1:
    def test_relevant_paper_passes(self, store: PaperStore, config: dict) -> None:
        papers = _store_papers(store, [_paper()])
        funnel = QualityFunnel(store, config)
        passed = funnel.stage1_relevance_filter(papers)
        assert len(passed) == 1
        assert passed[0]["relevance_score"] > 0

    def test_irrelevant_paper_filtered(self, store: PaperStore, config: dict) -> None:
        papers = _store_papers(store, [_paper(
            title="Improved Water Distribution in Agricultural Fields",
            abstract="We propose a method for optimizing water distribution in agricultural settings. "
                     "Our system uses soil moisture sensors and weather data to reduce water waste.",
            arxiv_id="2501.99999",
            categories=["physics.geo-ph"],
        )])
        funnel = QualityFunnel(store, config)
        passed = funnel.stage1_relevance_filter(papers)
        assert len(passed) == 0

    def test_excluded_keyword_filters(self, store: PaperStore, config: dict) -> None:
        config["excluded_keywords"] = ["survey"]
        papers = _store_papers(store, [_paper(
            title="A Survey of Deep Learning Methods",
            abstract="We survey deep learning approaches for NLP and computer vision. "
                     "This comprehensive survey covers 200 papers from the past decade.",
            arxiv_id="2501.00002",
        )])
        funnel = QualityFunnel(store, config)
        passed = funnel.stage1_relevance_filter(papers)
        assert len(passed) == 0

    def test_empty_input(self, store: PaperStore, config: dict) -> None:
        funnel = QualityFunnel(store, config)
        passed = funnel.stage1_relevance_filter([])
        assert passed == []


# ---------------------------------------------------------------------------
# Stage 2 tests
# ---------------------------------------------------------------------------


class TestStage2:
    def test_normal_paper_passes(self, store: PaperStore, config: dict) -> None:
        papers = [_paper()]
        funnel = QualityFunnel(store, config)
        passed = funnel.stage2_hard_negative_filter(papers)
        assert len(passed) == 1

    def test_short_abstract_filtered(self, store: PaperStore, config: dict) -> None:
        papers = [_paper(abstract="Short.")]
        funnel = QualityFunnel(store, config)
        passed = funnel.stage2_hard_negative_filter(papers)
        assert len(passed) == 0

    def test_survey_title_filtered(self, store: PaperStore, config: dict) -> None:
        papers = [_paper(
            title="A Survey of Deep Learning",
            abstract="x" * 200,
        )]
        funnel = QualityFunnel(store, config)
        passed = funnel.stage2_hard_negative_filter(papers)
        assert len(passed) == 0

    def test_survey_abstract_starter_filtered(self, store: PaperStore, config: dict) -> None:
        papers = [_paper(
            abstract="We present a survey of recent advances in deep learning. " + "x" * 200,
        )]
        funnel = QualityFunnel(store, config)
        passed = funnel.stage2_hard_negative_filter(papers)
        assert len(passed) == 0


# ---------------------------------------------------------------------------
# Stage 3 tests
# ---------------------------------------------------------------------------


class TestStage3:
    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_paper_passes_review(self, store: PaperStore, config: dict) -> None:
        papers = _store_papers(store, [_paper()])
        funnel = QualityFunnel(store, config)

        with patch("scholar_agent.engine.synthesize_answer.call_llm") as mock_llm:
            mock_llm.side_effect = _mock_llm_stage3(all_passed=True)
            passed, calls, tokens = funnel.stage3_llm_review(papers)

        assert len(passed) == 1
        assert calls == 1
        assert tokens > 0

    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_paper_fails_review(self, store: PaperStore, config: dict) -> None:
        papers = _store_papers(store, [_paper()])
        funnel = QualityFunnel(store, config)

        with patch("scholar_agent.engine.synthesize_answer.call_llm") as mock_llm:
            mock_llm.side_effect = _mock_llm_stage3(all_passed=False)
            passed, calls, tokens = funnel.stage3_llm_review(papers)

        assert len(passed) == 0

    def test_no_api_key_skips_stage(self, store: PaperStore, config: dict) -> None:
        papers = _store_papers(store, [_paper()])
        funnel = QualityFunnel(store, config)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_API_KEY", None)
            passed, calls, tokens = funnel.stage3_llm_review(papers)

        assert len(passed) == 1  # passes through without LLM check
        assert calls == 0

    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_survivors_capped(self, store: PaperStore, config: dict) -> None:
        config["precision_funnel"]["llm_review"]["max_survivors"] = 3
        papers = _store_papers(store, [
            _paper(arxiv_id=f"2501.{i:05d}", title=f"Paper {i}") for i in range(5)
        ])
        funnel = QualityFunnel(store, config)

        with patch("scholar_agent.engine.synthesize_answer.call_llm") as mock_llm:
            mock_llm.side_effect = _mock_llm_stage3(all_passed=True)
            passed, calls, tokens = funnel.stage3_llm_review(papers)

        assert len(passed) == 3

    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_llm_error_skips_conservatively(self, store: PaperStore, config: dict) -> None:
        papers = _store_papers(store, [_paper()])
        funnel = QualityFunnel(store, config)

        with patch("scholar_agent.engine.synthesize_answer.call_llm") as mock_llm:
            mock_llm.side_effect = RuntimeError("LLM down")
            passed, calls, tokens = funnel.stage3_llm_review(papers)

        assert len(passed) == 0


# ---------------------------------------------------------------------------
# Stage 4 tests
# ---------------------------------------------------------------------------


class TestStage4:
    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_selects_top_papers(self, store: PaperStore, config: dict) -> None:
        papers = [
            _paper(arxiv_id="2501.00001", title="Paper A"),
            _paper(arxiv_id="2501.00002", title="Paper B"),
        ]
        for p in papers:
            p["_llm_review"] = {"novelty": 4, "credibility": 4}

        funnel = QualityFunnel(store, config)

        with patch("scholar_agent.engine.synthesize_answer.call_llm") as mock_llm:
            mock_llm.side_effect = _mock_llm_stage4(selected_indices=[1])
            passed, calls, tokens = funnel.stage4_cross_comparison(papers)

        assert len(passed) == 1
        assert passed[0]["title"] == "Paper A"

    def test_empty_input(self, store: PaperStore, config: dict) -> None:
        funnel = QualityFunnel(store, config)
        passed, calls, tokens = funnel.stage4_cross_comparison([])
        assert passed == []
        assert calls == 0

    def test_no_api_key_uses_relevance(self, store: PaperStore, config: dict) -> None:
        papers = [
            {"title": "Low", "relevance_score": 1.0},
            {"title": "High", "relevance_score": 5.0},
        ]
        funnel = QualityFunnel(store, config)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_API_KEY", None)
            passed, calls, tokens = funnel.stage4_cross_comparison(papers)

        assert len(passed) == 2
        assert passed[0]["title"] == "High"


# ---------------------------------------------------------------------------
# Full pipeline tests
# ---------------------------------------------------------------------------


class TestFullPipeline:
    @patch.dict(os.environ, {"LLM_API_KEY": "test-key"})
    def test_end_to_end(self, store: PaperStore, config: dict) -> None:
        good = _paper(
            title="Novel Deep Learning Architecture",
            abstract=(
                "We propose a novel neural network architecture for reinforcement learning. "
                "Our method introduces a hierarchical attention mechanism that achieves "
                "state-of-the-art performance on three benchmarks, improving by 15%. "
                "We provide convergence proofs and extensive ablation studies."
            ),
        )
        bad = _paper(
            title="A Survey of Machine Learning",
            abstract="We present a survey of machine learning methods. " + "x" * 200,
            arxiv_id="2501.00002",
        )
        papers = _store_papers(store, [good, bad])
        funnel = QualityFunnel(store, config)

        with patch("scholar_agent.engine.synthesize_answer.call_llm") as mock_llm:
            mock_llm.side_effect = _mock_llm_stage4(selected_indices=[1])
            result = funnel.run_daily(papers)

        assert isinstance(result, FunnelResult)
        assert len(result.recommended) == 1
        assert result.stage_counts["input"] == 2
        assert result.stage_counts["stage1_passed"] >= 1

    def test_empty_pipeline(self, store: PaperStore, config: dict) -> None:
        funnel = QualityFunnel(store, config)
        result = funnel.run_daily([])
        assert result.recommended == []
        assert result.stage_counts["input"] == 0


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParsers:
    def test_parse_stage3_valid(self) -> None:
        raw = json.dumps({
            "checks": [{"question": "Q1", "passed": True, "evidence": "text"}],
            "novelty": 4, "credibility": 3, "depth": 5, "rigor": 2,
        })
        result = _parse_stage3_response(raw)
        assert result["novelty"] == 4
        assert result["depth"] == 5
        assert len(result["checks"]) == 1

    def test_parse_stage3_with_fences(self) -> None:
        raw = '```json\n{"checks": [], "novelty": 3, "credibility": 3, "depth": 3, "rigor": 3}\n```'
        result = _parse_stage3_response(raw)
        assert result["novelty"] == 3

    def test_parse_stage3_invalid(self) -> None:
        result = _parse_stage3_response("not json at all")
        assert result["novelty"] == 3  # defaults
        assert result["checks"] == []

    def test_parse_stage3_clamps_values(self) -> None:
        raw = json.dumps({"checks": [], "novelty": 10, "credibility": -1})
        result = _parse_stage3_response(raw)
        assert result["novelty"] == 5
        assert result["credibility"] == 1

    def test_parse_stage4_valid(self) -> None:
        raw = json.dumps({
            "selected": [{"index": 1, "reason": "great", "priority": 1}],
            "rationale": "test",
        })
        result = _parse_stage4_response(raw)
        assert len(result["selected"]) == 1
        assert result["rationale"] == "test"

    def test_parse_stage4_invalid(self) -> None:
        result = _parse_stage4_response("bad json")
        assert result["selected"] == []
