"""Tests for MCP server tool functions (logic only, no MCP transport)."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lore_config
from mcp_server import query_knowledge, save_research, list_knowledge, capture_answer

# Force config to always resolve to lore-agent's own directories
# regardless of cwd, so tests don't leak files into parent projects.
_TEST_INDEX = ROOT / "indexes" / "local" / "index.json"
_TEST_KNOWLEDGE = ROOT / "knowledge"
lore_config._config_cache = {
    "knowledge_dir": str(_TEST_KNOWLEDGE),
    "index_path": str(_TEST_INDEX),
    "lore_dir": str(ROOT),
}


def _build_index() -> None:
    _TEST_INDEX.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, str(SCRIPTS / "local_index.py"),
         "--knowledge-root", str(ROOT / "tests" / "fixtures"),
         "--output", str(_TEST_INDEX)],
        capture_output=True, text=True, cwd=ROOT,
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
            "answer": "Test answer from MCP",
            "supporting_claims": [
                {"claim": "test claim", "evidence_ids": ["e1"], "confidence": "high"},
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

    def test_save_missing_required_fields_warns(self) -> None:
        result = json.loads(save_research("test", json.dumps({"wrong": True})))
        self.assertEqual("ok", result["status"])
        self.assertGreater(len(result["schema_warnings"]), 0)
        _cleanup_card(result["card_path"])


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

    def test_path_traversal_rejected(self) -> None:
        result = json.loads(capture_answer("../../etc/passwd", "answer"))
        self.assertIn("error", result)

    def test_success_creates_card(self) -> None:
        result = json.loads(capture_answer("test capture query", "BM25 is a ranking function used in information retrieval."))
        self.assertEqual("ok", result["status"])
        self.assertIn("card_path", result)
        _cleanup_card(result["card_path"])

    def test_tags_passthrough(self) -> None:
        result = json.loads(capture_answer("test tags capture", "Some answer text.", tags="ml, search"))
        self.assertEqual("ok", result["status"])
        # Verify tags appear in the card content
        card_path = Path(result["card_path"])
        if card_path.exists():
            content = card_path.read_text(encoding="utf-8")
            self.assertIn("ml", content)
            self.assertIn("search", content)
        _cleanup_card(result["card_path"])


if __name__ == "__main__":
    unittest.main()
