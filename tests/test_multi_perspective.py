"""Tests for multi-perspective research and contradiction detection."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from research_harness import PERSPECTIVES, run_multi_perspective
from close_knowledge_loop import check_contradictions


class MultiPerspectiveTest(unittest.TestCase):
    def test_perspectives_dict(self) -> None:
        self.assertIn("academic", PERSPECTIVES)
        self.assertIn("technical", PERSPECTIVES)
        self.assertIn("contrarian", PERSPECTIVES)
        self.assertTrue(len(PERSPECTIVES) >= 4)

    @patch("research_harness.run_discovery")
    def test_run_returns_per_perspective(self, mock_discovery: MagicMock) -> None:
        mock_discovery.return_value = [{"url": "https://example.com", "title": "test"}]
        results = run_multi_perspective("transformers", perspectives=["academic", "technical"], limit_per_perspective=1)
        self.assertIn("academic", results)
        self.assertIn("technical", results)
        # Each perspective should have evidence tagged
        for evidence_list in results.values():
            for item in evidence_list:
                self.assertIn("perspective", item)

    @patch("research_harness.run_discovery")
    def test_handles_discovery_failure(self, mock_discovery: MagicMock) -> None:
        mock_discovery.side_effect = RuntimeError("No search results")
        results = run_multi_perspective("test", perspectives=["academic"])
        self.assertEqual({"academic": []}, results)


class ContradictionDetectionTest(unittest.TestCase):
    def test_no_index_returns_empty(self) -> None:
        result = check_contradictions("test query", [{"claim": "x"}], Path("/nonexistent/index.json"))
        self.assertEqual([], result)

    def test_no_claims_returns_empty(self) -> None:
        tmpdir = tempfile.mkdtemp()
        index_path = Path(tmpdir) / "index.json"
        index_path.write_text(json.dumps({"documents": []}), encoding="utf-8")
        result = check_contradictions("test", [], index_path)
        self.assertEqual([], result)

    @patch("close_knowledge_loop.bm25_retrieve")
    def test_returns_related_cards(self, mock_retrieve: MagicMock) -> None:
        tmpdir = tempfile.mkdtemp()
        index_path = Path(tmpdir) / "index.json"
        index_path.write_text("{}", encoding="utf-8")
        mock_retrieve.return_value = {
            "results": [
                {"doc_id": "card-1", "title": "Existing Card", "score": 5.2},
                {"doc_id": "card-2", "title": "Another", "score": 0.3},  # below threshold
            ]
        }
        result = check_contradictions("test query", [{"claim": "x"}], index_path)
        self.assertEqual(1, len(result))
        self.assertEqual("card-1", result[0]["card_id"])

    @patch("close_knowledge_loop.bm25_retrieve")
    def test_retrieve_exception_returns_empty(self, mock_retrieve: MagicMock) -> None:
        tmpdir = tempfile.mkdtemp()
        index_path = Path(tmpdir) / "index.json"
        index_path.write_text("{}", encoding="utf-8")
        mock_retrieve.side_effect = Exception("BM25 error")
        result = check_contradictions("test", [{"claim": "x"}], index_path)
        self.assertEqual([], result)


if __name__ == "__main__":
    unittest.main()
