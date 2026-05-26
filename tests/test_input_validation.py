"""Tests for MCP server input validation."""

import json
import subprocess
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

ENGINE = _ROOT / "scholar_agent" / "engine"

from scholar_agent.engine import scholar_config
from mcp_server import list_knowledge, query_knowledge, save_research
import sys

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
    _TEST_INDEX.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, str(ENGINE / "local_index.py"),
         "--knowledge-root", str(_ROOT / "tests" / "fixtures"),
         "--output", str(_TEST_INDEX)],
        capture_output=True, text=True, cwd=_ROOT,
    )


def _cleanup_card(card_path_str: str) -> None:
    card_path = Path(card_path_str)
    if card_path.exists():
        card_path.unlink()
    parent = card_path.parent
    while parent.exists() and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent
    _build_index()


class QueryKnowledgeValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _build_index()

    def test_limit_too_low(self) -> None:
        result = json.loads(query_knowledge("test", limit=0))
        self.assertIn("error", result)

    def test_limit_too_high(self) -> None:
        result = json.loads(query_knowledge("test", limit=100))
        self.assertIn("error", result)

    def test_limit_valid(self) -> None:
        result = json.loads(query_knowledge("test", limit=5))
        # Should not contain validation error (may have index not found error)
        self.assertNotIn("limit must be", result.get("error", ""))


class SaveResearchValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _build_index()

    def _valid_answer(self) -> dict:
        return {
            "answer": "This is a test answer with enough content to pass the quality gate threshold for minimum answer length requirements. It must be at least 200 characters long to be accepted by the quality gate in the save_research function.",
            "supporting_claims": [{"claim": "This is a test claim with enough substance to pass validation checks", "evidence_ids": ["e1"], "confidence": "high"}],
            "inferences": [],
            "uncertainty": [],
            "missing_evidence": [],
            "suggested_next_steps": [],
        }

    def test_empty_query(self) -> None:
        result = json.loads(save_research("", json.dumps(self._valid_answer())))
        self.assertIn("error", result)

    def test_valid_query(self) -> None:
        result = json.loads(save_research("normal query", json.dumps(self._valid_answer())))
        self.assertEqual("ok", result.get("status"))
        _cleanup_card(result["card_path"])


class ListKnowledgeValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _build_index()

    def test_path_traversal_topic(self) -> None:
        result = json.loads(list_knowledge(topic="../secret"))
        self.assertIn("error", result)
        self.assertIn("path separators", result["error"])

    def test_normal_topic(self) -> None:
        result = json.loads(list_knowledge(topic="examples"))
        self.assertNotIn("error", result.get("", ""))
        # Should have cards or total, not validation error
        self.assertIn("total", result)

    def test_no_topic(self) -> None:
        result = json.loads(list_knowledge())
        self.assertIn("total", result)


if __name__ == "__main__":
    unittest.main()
