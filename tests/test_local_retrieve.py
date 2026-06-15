import json
import subprocess
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


INDEX_PATH = _ROOT / "indexes" / "local" / "index.json"


class LocalRetrieveTest(unittest.TestCase):
    def setUp(self) -> None:
        build_command = [
            sys.executable,
            "-m",
            "scholar_agent.engine.local_index",
            "--knowledge-root",
            "tests/fixtures",
            "--output",
            str(INDEX_PATH),
        ]
        build_result = subprocess.run(build_command, capture_output=True, text=True, encoding="utf-8")
        if build_result.returncode != 0:
            self.fail(
                f"failed to build local index for retrieval test: "
                f"stdout={build_result.stdout!r} stderr={build_result.stderr!r}"
            )

    def test_local_retrieve_returns_ranked_citation_friendly_results(self) -> None:
        command = [
            sys.executable,
            "-m",
            "scholar_agent.engine.local_retrieve",
            "what is a markov chain",
            "--index",
            str(INDEX_PATH),
            "--limit",
            "3",
        ]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")

        self.assertEqual(
            0,
            result.returncode,
            msg=f"retrieve failed unexpectedly: stdout={result.stdout!r} stderr={result.stderr!r}",
        )

        payload = json.loads(result.stdout)
        self.assertIn("results", payload)
        self.assertGreaterEqual(len(payload["results"]), 1)

        top = payload["results"][0]
        # Top-1 must be a markov-chain card; the exact one depends on ranking
        # details (shipped dictionary is domain-agnostic, no markov synonym boost).
        self.assertIn("markov", top["doc_id"].lower())
        self.assertEqual("knowledge", top["type"])
        self.assertIn("markov", top["matched_terms"])
        self.assertGreater(top["score"], 0)
        doc_ids = {item["doc_id"] for item in payload["results"]}
        self.assertNotIn("README", doc_ids)


if __name__ == "__main__":
    unittest.main()
