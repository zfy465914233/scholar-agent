"""Tests for MCP server tool functions (logic only, no MCP transport)."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mcp_server import query_knowledge, save_research, list_knowledge


class QueryKnowledgeTest(unittest.TestCase):
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

        # Clean up
        card_path = Path(result["card_path"])
        if card_path.exists():
            card_path.unlink()
        # Reindex without test card
        import subprocess
        subprocess.run(
            [sys.executable, str(SCRIPTS / "local_index.py"),
             "--output", str(ROOT / "indexes" / "local" / "index.json")],
            capture_output=True, text=True, cwd=ROOT,
        )

    def test_save_invalid_json(self) -> None:
        result = json.loads(save_research("test", "not json at all"))
        self.assertIn("error", result)

    def test_save_missing_required_fields_warns(self) -> None:
        result = json.loads(save_research("test", json.dumps({"wrong": True})))
        self.assertEqual("ok", result["status"])
        self.assertGreater(len(result["schema_warnings"]), 0)

        # Clean up
        card_path = Path(result["card_path"])
        if card_path.exists():
            card_path.unlink()
        import subprocess
        subprocess.run(
            [sys.executable, str(SCRIPTS / "local_index.py"),
             "--output", str(ROOT / "indexes" / "local" / "index.json")],
            capture_output=True, text=True, cwd=ROOT,
        )


class ListKnowledgeTest(unittest.TestCase):
    def test_list_all_cards(self) -> None:
        result = json.loads(list_knowledge())
        self.assertIn("cards", result)
        self.assertGreater(result["total"], 0)
        for card in result["cards"]:
            self.assertIn("id", card)
            self.assertIn("topic", card)

    def test_list_filtered_by_topic(self) -> None:
        result = json.loads(list_knowledge(topic="qpe"))
        self.assertIn("cards", result)
        for card in result["cards"]:
            self.assertEqual("qpe", card.get("topic"))

    def test_list_nonexistent_topic_returns_empty(self) -> None:
        result = json.loads(list_knowledge(topic="nonexistent_xyz"))
        self.assertEqual(0, result["total"])


if __name__ == "__main__":
    unittest.main()
