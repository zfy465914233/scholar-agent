import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "indexes" / "local" / "index.json"


class HybridEvidencePackTest(unittest.TestCase):
    def setUp(self) -> None:
        build_index = subprocess.run(
            [sys.executable, "scripts/local_index.py", "--output", str(INDEX_PATH)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if build_index.returncode != 0:
            self.fail(
                f"failed to build local index for hybrid evidence test: "
                f"stdout={build_index.stdout!r} stderr={build_index.stderr!r}"
            )

    def test_hybrid_evidence_pack_merges_local_and_web_evidence(self) -> None:
        web_payload = {
            "query": "markov chain latest tutorial",
            "depth": "quick",
            "generated_at": "2026-04-01T00:00:00+00:00",
            "summary": {"total_evidence": 1},
            "validation": {"ok": True, "errors": []},
            "evidence": [
                {
                    "query": "markov chain latest tutorial",
                    "source_type": "docs",
                    "url": "https://example.com/markov-guide",
                    "title": "Markov Chain Guide",
                    "summary": "A concise guide to Markov chains.",
                    "retrieved_at": "2026-04-01T00:00:00+00:00",
                    "retrieval_status": "succeeded",
                }
            ],
        }

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(web_payload, handle)
            web_path = Path(handle.name)

        command = [
            sys.executable,
            "scripts/build_evidence_pack.py",
            "what is a markov chain",
            "--index",
            str(INDEX_PATH),
            "--web-evidence",
            str(web_path),
            "--local-limit",
            "2",
        ]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        web_path.unlink(missing_ok=True)

        self.assertEqual(
            0,
            result.returncode,
            msg=f"hybrid evidence build failed unexpectedly: stdout={result.stdout!r} stderr={result.stderr!r}",
        )

        payload = json.loads(result.stdout)
        self.assertEqual("what is a markov chain", payload["query"])
        self.assertIn("items", payload)
        self.assertGreaterEqual(len(payload["items"]), 2)

        origins = {item["origin"] for item in payload["items"]}
        self.assertIn("local", origins)
        self.assertIn("web", origins)

        local_item = next(item for item in payload["items"] if item["origin"] == "local")
        self.assertEqual("markov-chain-definition", local_item["evidence_id"])
        self.assertEqual("definition", local_item["source_type"])
        self.assertIn("matched_terms", local_item)

        web_item = next(item for item in payload["items"] if item["origin"] == "web")
        self.assertEqual("https://example.com/markov-guide", web_item["url"])
        self.assertEqual("docs", web_item["source_type"])
        self.assertEqual("Markov Chain Guide", web_item["title"])
        self.assertRegex(web_item["evidence_id"], r"^web-[0-9a-f]{8}$")


if __name__ == "__main__":
    unittest.main()
