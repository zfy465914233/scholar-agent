import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "indexes" / "local" / "index.json"
FAKE_HARNESS = ROOT / "tests" / "fake_research_harness.py"


class AnswerContextTest(unittest.TestCase):
    def setUp(self) -> None:
        build_index = subprocess.run(
            [sys.executable, "scripts/local_index.py", "--output", str(INDEX_PATH)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if build_index.returncode != 0:
            self.fail(
                f"failed to build local index for answer context test: "
                f"stdout={build_index.stdout!r} stderr={build_index.stderr!r}"
            )

    def test_answer_context_separates_direct_support_inference_and_uncertainty(self) -> None:
        command = [
            sys.executable,
            "scripts/build_answer_context.py",
            "what is a markov chain",
            "--index",
            str(INDEX_PATH),
            "--mode",
            "mixed",
            "--research-script",
            str(FAKE_HARNESS),
        ]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)

        self.assertEqual("what is a markov chain", payload["query"])
        self.assertIn("direct_support", payload)
        self.assertIn("inference_notes", payload)
        self.assertIn("uncertainty_notes", payload)
        self.assertIn("citations", payload)
        self.assertGreaterEqual(len(payload["direct_support"]), 1)
        self.assertGreaterEqual(len(payload["citations"]), 1)

        citation_ids = {item["evidence_id"] for item in payload["citations"]}
        self.assertIn("markov-chain-definition", citation_ids)

        direct_ids = {item["evidence_id"] for item in payload["direct_support"]}
        self.assertIn("markov-chain-definition", direct_ids)

        self.assertTrue(
            any("web evidence" in note.lower() or "web source" in note.lower() for note in payload["uncertainty_notes"])
        )

    def test_answer_context_flags_limited_support_when_no_evidence_is_found(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            empty_knowledge = temp_root / "knowledge"
            empty_knowledge.mkdir(parents=True, exist_ok=True)
            empty_index = temp_root / "indexes" / "local" / "index.json"

            build_index = subprocess.run(
                [
                    sys.executable,
                    "scripts/local_index.py",
                    "--knowledge-root",
                    str(empty_knowledge),
                    "--output",
                    str(empty_index),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, build_index.returncode, msg=build_index.stderr)

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_answer_context.py",
                    "what is qpe",
                    "--mode",
                    "local-led",
                    "--index",
                    str(empty_index),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, result.returncode, msg=result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual([], payload["direct_support"])
            self.assertTrue(any("limited" in note.lower() for note in payload["inference_notes"]))
            self.assertTrue(any("no direct evidence" in note.lower() for note in payload["uncertainty_notes"]))


if __name__ == "__main__":
    unittest.main()
