"""Tests for BM25 retrieval and hybrid retrieval."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
INDEX_PATH = ROOT / "indexes" / "local" / "index.json"


class BM25UnitTest(unittest.TestCase):
    """Unit tests for the BM25 scorer."""

    def test_bm25_ranks_relevant_docs_higher(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", """
from bm25 import BM25

docs = [
    {"doc_id": "a", "search_text": "Markov chains are stochastic processes"},
    {"doc_id": "b", "search_text": "Linear programming optimization"},
    {"doc_id": "c", "search_text": "Markov chain stationary distribution derivation"},
]
bm25 = BM25(docs)
results = bm25.top_k("Markov chain", k=3)
print([r[0] for r in results])
"""],
            capture_output=True,
            text=True,
            cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        indices = eval(result.stdout.strip())
        # LP doc is index 1; it should NOT be the top result
        self.assertNotEqual(indices[0], 1, "LP doc should not rank first for a Markov query")

    def test_bm25_handles_empty_query(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", """
from bm25 import BM25
docs = [{"doc_id": "a", "search_text": "test content"}]
bm25 = BM25(docs)
results = bm25.score("")
print(len(results))
"""],
            capture_output=True,
            text=True,
            cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertEqual("0", result.stdout.strip())

    def test_bm25_handles_empty_corpus(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", """
from bm25 import BM25
bm25 = BM25([])
results = bm25.score("test query")
print(len(results))
"""],
            capture_output=True,
            text=True,
            cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertEqual("0", result.stdout.strip())


class BM25CLIIntegrationTest(unittest.TestCase):
    """Integration tests for BM25 retrieval via CLI."""

    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(
            [sys.executable, str(SCRIPTS / "local_index.py"), "--output", str(INDEX_PATH)],
            capture_output=True, text=True, cwd=ROOT,
        )

    def test_bm25_retrieves_example_card(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "local_retrieve.py"), "what is a markov chain",
             "--index", str(INDEX_PATH)],
            capture_output=True, text=True, cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertGreaterEqual(len(payload["results"]), 1)
        top = payload["results"][0]
        self.assertIn("markov", top["doc_id"].lower())
        self.assertEqual("bm25", top["source"])
        self.assertGreater(top["score"], 0)

    def test_bm25_weight_parameter(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "local_retrieve.py"), "markov chain",
             "--index", str(INDEX_PATH), "--bm25-weight", "0.8"],
            capture_output=True, text=True, cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)

    def test_no_embedding_index_falls_back_to_bm25(self) -> None:
        """When embedding index path doesn't exist, should still return BM25 results."""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "local_retrieve.py"), "markov chain",
             "--index", str(INDEX_PATH),
             "--embedding-index", "/nonexistent/embeddings.json"],
            capture_output=True, text=True, cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertGreaterEqual(len(payload["results"]), 1)
        self.assertEqual("bm25", payload["results"][0]["source"])


class BM25ScoreQualityTest(unittest.TestCase):
    """Test that BM25 scores are reasonable for known queries."""

    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(
            [sys.executable, str(SCRIPTS / "local_index.py"), "--output", str(INDEX_PATH)],
            capture_output=True, text=True, cwd=ROOT,
        )

    def test_definition_query_ranks_definition_first(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "local_retrieve.py"),
             "what is a markov chain definition",
             "--index", str(INDEX_PATH), "--limit", "3"],
            capture_output=True, text=True, cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("markov", payload["results"][0]["doc_id"].lower())

    def test_scores_decrease_with_rank(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "local_retrieve.py"),
             "markov chain stationary distribution",
             "--index", str(INDEX_PATH), "--limit", "5"],
            capture_output=True, text=True, cwd=SCRIPTS,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        scores = [r["score"] for r in payload["results"]]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])


if __name__ == "__main__":
    unittest.main()
