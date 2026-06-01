"""Tests for MCP server tool functions (logic only, no MCP transport)."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

ENGINE = _ROOT / "src" / "scholar_agent" / "engine"

from scholar_agent.engine import scholar_config
from scholar_agent.engine.close_knowledge_loop import (
    QUALITY_THRESHOLD_SAVE_RESEARCH,
    quality_score_answer_data,
)
from scholar_agent.server import capture_answer, list_knowledge, query_knowledge, save_research

# Force config to always resolve to scholar-agent's own directories
# regardless of cwd, so tests don't leak files into parent projects.
_TEST_INDEX = _ROOT / "indexes" / "local" / "index.json"
_TEST_KNOWLEDGE = _ROOT / "tests" / "fixtures"
scholar_config._config_cache = {
    "knowledge_dir": str(_TEST_KNOWLEDGE),
    "index_path": str(_TEST_INDEX),
    "scholar_dir": str(_ROOT),
}


def tearDownModule() -> None:
    scholar_config.clear_cache()


def _build_index() -> None:
    # Ensure config cache points to test fixtures (may have been cleared by
    # another test file's tearDownModule).
    scholar_config._config_cache = {
        "knowledge_dir": str(_TEST_KNOWLEDGE),
        "index_path": str(_TEST_INDEX),
        "scholar_dir": str(_ROOT),
    }
    _TEST_INDEX.parent.mkdir(parents=True, exist_ok=True)
    stale_marker = _TEST_INDEX.with_suffix(_TEST_INDEX.suffix + ".stale")
    if stale_marker.exists():
        stale_marker.unlink()
    subprocess.run(
        [
            sys.executable,
            str(ENGINE / "local_index.py"),
            "--knowledge-root",
            str(_TEST_KNOWLEDGE),
            "--full-rebuild",
            "--output",
            str(_TEST_INDEX),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_ROOT,
    )


def _cleanup_card(card_path_str: str) -> None:
    card_path = Path(card_path_str)
    if card_path.exists():
        card_path.unlink()
    # Remove empty parent dirs including knowledge root
    parent = card_path.parent
    while parent.exists() and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent
    _build_index()


class QueryKnowledgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _build_index()

    def test_query_returns_results(self) -> None:
        result = json.loads(query_knowledge("Markov chain"))
        self.assertIn("results", result)
        self.assertGreater(len(result["results"]), 0)

    def test_query_missing_index(self) -> None:
        result = json.loads(query_knowledge("test", limit=1))
        self.assertIn("results", result)

    def test_query_with_limit(self) -> None:
        result = json.loads(query_knowledge("Markov chain", limit=2))
        self.assertLessEqual(len(result["results"]), 2)


class SaveResearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _build_index()

    def test_save_valid_research(self) -> None:
        answer = {
            "answer": "This is a test answer that is long enough to pass the quality gate threshold of 200 characters. It includes substantive content about testing the save_research function in the MCP server, including validation and card building.",
            "supporting_claims": [
                {
                    "claim": "The save_research function creates knowledge cards from structured JSON data",
                    "evidence_ids": ["e1"],
                    "confidence": "high",
                },
            ],
            "inferences": ["test inference"],
            "uncertainty": [],
            "missing_evidence": [],
            "suggested_next_steps": [],
        }
        result = json.loads(save_research("test mcp save query", json.dumps(answer)))
        self.assertEqual("ok", result["status"])
        self.assertEqual([], result["schema_warnings"])
        _cleanup_card(result["card_path"])

    def test_save_invalid_json(self) -> None:
        result = json.loads(save_research("test", "not json at all"))
        self.assertIn("error", result)

    def test_save_missing_required_fields_rejected(self) -> None:
        result = json.loads(save_research("test", json.dumps({"wrong": True})))
        self.assertIn("error", result)
        self.assertIn("Quality gate failed", result["error"])


class ListKnowledgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _build_index()

    def test_list_all_cards(self) -> None:
        result = json.loads(list_knowledge())
        self.assertIn("cards", result)
        self.assertGreater(result["total"], 0)
        for card in result["cards"]:
            self.assertIn("id", card)
            self.assertIn("topic", card)

    def test_list_filtered_by_topic(self) -> None:
        result = json.loads(list_knowledge(topic="examples"))
        self.assertIn("cards", result)
        for card in result["cards"]:
            self.assertEqual("examples", card.get("topic"))

    def test_list_nonexistent_topic_returns_empty(self) -> None:
        result = json.loads(list_knowledge(topic="nonexistent_xyz"))
        self.assertEqual(0, result["total"])


class CaptureAnswerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _build_index()

    def test_empty_query_rejected(self) -> None:
        result = json.loads(capture_answer("", "some answer"))
        self.assertIn("error", result)

    def test_empty_answer_rejected(self) -> None:
        result = json.loads(capture_answer("what is BM25", ""))
        self.assertIn("error", result)

    def test_success_creates_card(self) -> None:
        result = json.loads(
            capture_answer(
                "test capture query",
                "BM25 is a probabilistic ranking function used in information retrieval systems to estimate the relevance of documents to a given search query based on term frequency and document length.",
            )
        )
        self.assertEqual("ok", result["status"])
        self.assertIn("card_path", result)
        _cleanup_card(result["card_path"])

    def test_tags_passthrough(self) -> None:
        result = json.loads(
            capture_answer(
                "test tags capture",
                "This is a substantive test answer that exceeds the minimum character threshold for the capture_answer quality gate to ensure tags are properly passed through.",
                tags="ml, search",
            )
        )
        self.assertEqual("ok", result["status"])
        # Verify tags appear in the card content
        card_path = Path(result["card_path"])
        if card_path.exists():
            content = card_path.read_text(encoding="utf-8")
            self.assertIn("ml", content)
            self.assertIn("search", content)
        _cleanup_card(result["card_path"])


class QualityGateTest(unittest.TestCase):
    """Tests for the quality gate enforcement on card creation."""

    def test_save_research_rejects_thin_answer(self) -> None:
        answer = {
            "answer": "Too short",
            "supporting_claims": [
                {
                    "claim": "this claim is substantive enough to pass validation",
                    "evidence_ids": ["e1"],
                    "confidence": "high",
                },
            ],
        }
        result = json.loads(save_research("thin answer test", json.dumps(answer)))
        self.assertIn("error", result)
        self.assertIn("Quality gate failed", result["error"])
        self.assertIn("violations", result)
        self.assertGreater(len(result["violations"]), 0)

    def test_save_research_rejects_zero_claims(self) -> None:
        answer = {
            "answer": "This answer is long enough but has no supporting claims at all, which means it should be rejected by the quality gate since claims are required.",
            "supporting_claims": [],
        }
        result = json.loads(save_research("zero claims test", json.dumps(answer)))
        self.assertIn("error", result)
        self.assertIn("Quality gate failed", result["error"])

    def test_save_research_rejects_short_claims(self) -> None:
        answer = {
            "answer": "This answer is long enough and has claims but the claim text is too short to be meaningful, so the quality gate should reject it.",
            "supporting_claims": [
                {"claim": "short", "evidence_ids": ["e1"], "confidence": "high"},
            ],
        }
        result = json.loads(save_research("short claim test", json.dumps(answer)))
        self.assertIn("error", result)
        self.assertIn("Quality gate failed", result["error"])

    def test_capture_answer_rejects_brief_answer(self) -> None:
        result = json.loads(capture_answer("brief test", "Too short"))
        self.assertIn("error", result)
        self.assertIn("Quality gate failed", result["error"])

    def test_save_research_accepts_quality_answer(self) -> None:
        answer = {
            "answer": "This is a high-quality answer with sufficient length to pass all quality gates. It provides substantive content about the topic being researched and includes enough detail for a useful knowledge card.",
            "supporting_claims": [
                {
                    "claim": "Quality gates enforce minimum content standards on knowledge cards",
                    "evidence_ids": ["e1"],
                    "confidence": "high",
                },
                {
                    "claim": "The scoring function evaluates answer length, claim count, claim depth, and structural richness",
                    "evidence_ids": ["e2"],
                    "confidence": "high",
                },
            ],
            "inferences": ["Quality gates should reduce the number of thin, uninformative cards"],
            "uncertainty": ["Threshold values may need tuning based on real-world usage"],
            "suggested_next_steps": ["Monitor rejection rates and adjust thresholds"],
        }
        result = json.loads(save_research("quality answer test", json.dumps(answer)))
        self.assertEqual("ok", result["status"])
        _cleanup_card(result["card_path"])

    def test_quality_score_calculation(self) -> None:
        # A fully-populated answer should score well
        full_answer = {
            "answer": "A" * 500,
            "supporting_claims": [
                {"claim": "B" * 50, "evidence_ids": ["e1"], "confidence": "high"},
                {"claim": "C" * 50, "evidence_ids": ["e2"], "confidence": "medium"},
                {"claim": "D" * 50, "evidence_ids": ["e3"], "confidence": "low"},
            ],
            "inferences": ["inf1"],
            "uncertainty": ["unc1"],
            "missing_evidence": ["miss1"],
            "suggested_next_steps": ["step1"],
        }
        quality = quality_score_answer_data(full_answer, source="save_research")
        self.assertTrue(quality["passed"])
        self.assertGreaterEqual(quality["score"], QUALITY_THRESHOLD_SAVE_RESEARCH)
        self.assertEqual(0, len(quality["violations"]))

        # A minimal answer should fail
        thin_answer = {
            "answer": "short",
            "supporting_claims": [],
        }
        quality = quality_score_answer_data(thin_answer, source="save_research")
        self.assertFalse(quality["passed"])
        self.assertGreater(len(quality["violations"]), 0)


if __name__ == "__main__":
    unittest.main()
