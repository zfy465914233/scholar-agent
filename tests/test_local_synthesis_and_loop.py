"""Tests for local answer mode and knowledge loop closing."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
INDEX_PATH = ROOT / "indexes" / "local" / "index.json"


class LocalAnswerSynthesisTest(unittest.TestCase):
    """Test --local-answer mode in synthesize_answer.py."""

    def test_local_answer_mode(self) -> None:
        """Local answer mode skips API call and uses provided JSON."""
        prompt_bundle = {
            "system_prompt": "test",
            "user_prompt": "test query",
            "metadata": {"query": "test", "route": "local-led"},
            "citations": [{"evidence_id": "e1", "origin": "local", "title": "T", "source_type": "def"}],
        }
        local_answer = {
            "answer": "test answer",
            "supporting_claims": [{"claim": "c1", "evidence_ids": ["e1"], "confidence": "high"}],
            "inferences": [], "uncertainty": [], "missing_evidence": [], "suggested_next_steps": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_path = Path(tmpdir) / "bundle.json"
            answer_path = Path(tmpdir) / "answer.json"
            bundle_path.write_text(json.dumps(prompt_bundle))
            answer_path.write_text(json.dumps(local_answer))

            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "synthesize_answer.py"),
                 "--prompt-bundle", str(bundle_path),
                 "--local-answer", str(answer_path)],
                capture_output=True, text=True, cwd=SCRIPTS,
            )
            self.assertEqual(0, result.returncode, msg=result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual("test", output["query"])
            self.assertEqual("test answer", output["answer"]["answer"])
            self.assertEqual(1, len(output["answer"]["supporting_claims"]))
            self.assertEqual("local", output["synthesis_meta"]["usage"]["source"])


class CloseKnowledgeLoopTest(unittest.TestCase):
    """Test the close_knowledge_loop.py script."""

    @classmethod
    def setUpClass(cls) -> None:
        # Rebuild index to include any new cards
        subprocess.run(
            [sys.executable, str(SCRIPTS / "local_index.py"), "--output", str(INDEX_PATH)],
            capture_output=True, text=True, cwd=ROOT,
        )

    def test_close_loop_creates_card_and_reindexes(self) -> None:
        answer = {
            "answer": "Test answer for loop closing",
            "supporting_claims": [],
            "inferences": ["test inference"],
            "uncertainty": [],
            "missing_evidence": [],
            "suggested_next_steps": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            answer_path = Path(tmpdir) / "answer.json"
            answer_path.write_text(json.dumps(answer))

            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "close_knowledge_loop.py"),
                 "--query", "test loop closing query",
                 "--answer", str(answer_path)],
                capture_output=True, text=True, cwd=ROOT,
            )
            self.assertEqual(0, result.returncode, msg=result.stderr)
            self.assertIn("Knowledge card written", result.stderr)

            # Verify card exists
            card_path = ROOT / "knowledge" / "general" / "research-test-loop-closing-query.md"
            self.assertTrue(card_path.exists(), "Card should be written to knowledge tree")

            # Verify it's in the index
            index = json.loads(INDEX_PATH.read_text())
            doc_ids = [d["doc_id"] for d in index["documents"]]
            self.assertIn("research-test-loop-closing-query", doc_ids)

            # Clean up
            card_path.unlink()
            # Reindex without the test card
            subprocess.run(
                [sys.executable, str(SCRIPTS / "local_index.py"), "--output", str(INDEX_PATH)],
                capture_output=True, text=True, cwd=ROOT,
            )

    def test_xgboost_qpe_card_is_retrievable(self) -> None:
        """Verify the real XGBoost QPE research card is retrievable."""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "local_retrieve.py"),
             "XGBoost radar QPE", "--index", str(INDEX_PATH), "--limit", "3"],
            capture_output=True, text=True, cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertGreater(len(payload["results"]), 0)
        self.assertIn("xgboost", payload["results"][0]["doc_id"].lower())


if __name__ == "__main__":
    unittest.main()
