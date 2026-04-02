import json
import subprocess
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "indexes" / "local" / "index.json"


class LocalRagSmokeTest(unittest.TestCase):
    def test_seed_cards_can_be_indexed_and_retrieved_end_to_end(self) -> None:
        index_result = subprocess.run(
            [sys.executable, "scripts/local_index.py", "--output", str(INDEX_PATH)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            0,
            index_result.returncode,
            msg=f"index build failed: stdout={index_result.stdout!r} stderr={index_result.stderr!r}",
        )

        retrieve_result = subprocess.run(
            [
                sys.executable,
                "scripts/local_retrieve.py",
                "stationary distribution derivation",
                "--index",
                str(INDEX_PATH),
                "--limit",
                "2",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            0,
            retrieve_result.returncode,
            msg=f"retrieval failed: stdout={retrieve_result.stdout!r} stderr={retrieve_result.stderr!r}",
        )

        payload = json.loads(retrieve_result.stdout)
        doc_ids = [item["doc_id"] for item in payload["results"]]
        self.assertIn("stationary-distribution-derivation", doc_ids)


if __name__ == "__main__":
    unittest.main()
