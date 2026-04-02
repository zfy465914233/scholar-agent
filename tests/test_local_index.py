import json
import subprocess
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "indexes" / "local" / "index.json"


class LocalIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        INDEX_PATH.unlink(missing_ok=True)

    def test_local_index_builder_creates_json_index_from_knowledge_cards(self) -> None:
        command = [sys.executable, "scripts/local_index.py", "--output", str(INDEX_PATH)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)

        self.assertEqual(
            0,
            result.returncode,
            msg=f"index build failed unexpectedly: stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        self.assertTrue(INDEX_PATH.exists(), "index.json should be created")

        payload = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        self.assertIn("documents", payload)
        self.assertGreaterEqual(len(payload["documents"]), 2)

        doc_ids = {doc["doc_id"] for doc in payload["documents"]}
        self.assertIn("markov-chain-definition", doc_ids)
        self.assertIn("stationary-distribution-derivation", doc_ids)

        definition_doc = next(doc for doc in payload["documents"] if doc["doc_id"] == "markov-chain-definition")
        self.assertEqual("definition", definition_doc["type"])
        self.assertEqual("stochastic_processes", definition_doc["topic"])
        self.assertIn("markov-chain", definition_doc["tags"])
        self.assertIn("Markov chain is a stochastic process", definition_doc["search_text"])


if __name__ == "__main__":
    unittest.main()
