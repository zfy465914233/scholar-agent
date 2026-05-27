import json
import subprocess
from pathlib import Path
import unittest
import sys

_ROOT = Path(__file__).resolve().parents[1]


INDEX_PATH = _ROOT / "indexes" / "local" / "index.json"


class DomainSeedCardsTest(unittest.TestCase):
    def setUp(self) -> None:
        build_result = subprocess.run(
            [sys.executable, "-m", "scholar_agent.engine.local_index", "--knowledge-root", "tests/fixtures", "--output", str(INDEX_PATH)],
            cwd=_ROOT,
            capture_output=True,
            text=True,
        )
        if build_result.returncode != 0:
            self.fail(
                f"failed to build index for domain card test: "
                f"stdout={build_result.stdout!r} stderr={build_result.stderr!r}"
            )

    def test_example_cards_are_indexed(self) -> None:
        payload = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        doc_ids = {doc["doc_id"] for doc in payload["documents"]}
        self.assertIn("example-markov-chain-definition", doc_ids)

    def test_example_cards_are_retrievable(self) -> None:
        command = [
            sys.executable,
            "-m", "scholar_agent.engine.local_retrieve",
            "Markov chain definition",
            "--index",
            str(INDEX_PATH),
            "--limit",
            "5",
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, msg=result.stderr)

        payload = json.loads(result.stdout)
        doc_ids = [item["doc_id"] for item in payload["results"]]
        self.assertIn("example-markov-chain-definition", doc_ids)


if __name__ == "__main__":
    unittest.main()
