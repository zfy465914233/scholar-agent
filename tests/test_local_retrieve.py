import json
import subprocess
from pathlib import Path
import unittest
import sys

_ROOT = Path(__file__).resolve().parents[1]


INDEX_PATH = _ROOT / "indexes" / "local" / "index.json"


class LocalRetrieveTest(unittest.TestCase):
    def setUp(self) -> None:
        build_command = [sys.executable, "scholar_agent/engine/local_index.py", "--knowledge-root", "tests/fixtures", "--output", str(INDEX_PATH)]
        build_result = subprocess.run(build_command, cwd=_ROOT, capture_output=True, text=True)
        if build_result.returncode != 0:
            self.fail(
                f"failed to build local index for retrieval test: "
                f"stdout={build_result.stdout!r} stderr={build_result.stderr!r}"
            )

    def test_local_retrieve_returns_ranked_citation_friendly_results(self) -> None:
        command = [
            sys.executable,
            "scholar_agent/engine/local_retrieve.py",
            "what is a markov chain",
            "--index",
            str(INDEX_PATH),
            "--limit",
            "3",
        ]
        result = subprocess.run(command, cwd=_ROOT, capture_output=True, text=True)

        self.assertEqual(
            0,
            result.returncode,
            msg=f"retrieve failed unexpectedly: stdout={result.stdout!r} stderr={result.stderr!r}",
        )

        payload = json.loads(result.stdout)
        self.assertIn("results", payload)
        self.assertGreaterEqual(len(payload["results"]), 1)

        top = payload["results"][0]
        self.assertEqual("example-markov-chain-definition", top["doc_id"])
        self.assertEqual("knowledge", top["type"])
        self.assertEqual("examples", top["topic"])
        self.assertIn("markov", top["matched_terms"])
        self.assertGreater(top["score"], 0)
        self.assertTrue(top["path"].endswith("tests/fixtures/example-markov-chain.md"))
        doc_ids = {item["doc_id"] for item in payload["results"]}
        self.assertNotIn("README", doc_ids)


if __name__ == "__main__":
    unittest.main()
