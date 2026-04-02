"""Tests for run_pipeline.py and run_eval.py — end-to-end integration."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
INDEX_PATH = ROOT / "indexes" / "local" / "index.json"
FAKE_HARNESS = ROOT / "tests" / "fake_research_harness.py"


def _ensure_index() -> None:
    if INDEX_PATH.exists():
        return
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "local_index.py"), "--output", str(INDEX_PATH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Index build failed: {result.stderr}"


class PipelineDryRunTest(unittest.TestCase):
    """Test the full pipeline in dry-run mode (no LLM calls)."""

    @classmethod
    def setUpClass(cls) -> None:
        _ensure_index()

    def test_pipeline_dry_run_local_led(self) -> None:
        result = subprocess.run(
            [
                sys.executable, str(SCRIPTS / "run_pipeline.py"),
                "what is a markov chain",
                "--mode", "auto",
                "--index", str(INDEX_PATH),
                "--research-script", str(FAKE_HARNESS),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)

        self.assertEqual("what is a markov chain", payload["query"])
        self.assertEqual("dry_run", payload["pipeline_status"])
        self.assertEqual("local-led", payload["route"])
        self.assertGreaterEqual(payload["answer_context_summary"]["direct_support_count"], 1)
        self.assertIn("prompt_bundle", payload)
        self.assertIn("system_prompt", payload["prompt_bundle"])

    def test_pipeline_dry_run_web_led(self) -> None:
        result = subprocess.run(
            [
                sys.executable, str(SCRIPTS / "run_pipeline.py"),
                "latest SOTA quantization methods",
                "--mode", "auto",
                "--index", str(INDEX_PATH),
                "--research-script", str(FAKE_HARNESS),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("web-led", payload["route"])

    def test_pipeline_keep_intermediate(self) -> None:
        result = subprocess.run(
            [
                sys.executable, str(SCRIPTS / "run_pipeline.py"),
                "what is a markov chain",
                "--mode", "local-led",
                "--index", str(INDEX_PATH),
                "--dry-run",
                "--keep-intermediate",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("intermediate", payload)
        self.assertIn("answer_context", payload["intermediate"])
        self.assertIn("prompt_bundle", payload["intermediate"])


class EvalRunnerTest(unittest.TestCase):
    """Test the evaluation runner."""

    @classmethod
    def setUpClass(cls) -> None:
        _ensure_index()

    def test_eval_dry_run_all(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "run_eval.py"), "--dry-run"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        report = json.loads(result.stdout)

        summary = report["summary"]
        self.assertTrue(summary["dry_run"])
        self.assertGreaterEqual(summary["total_cases"], 5)
        self.assertGreater(summary["route_accuracy"], 0.5)
        self.assertGreater(summary["retrieval_hit_rate"], 0.1)

    def test_eval_dry_run_single_category(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "run_eval.py"), "--dry-run", "--category", "definition"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(3, report["summary"]["total_cases"])
        # All definition cases should route to local-led
        self.assertEqual(1.0, report["summary"]["route_accuracy"])

    def test_eval_by_category_breakdown(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "run_eval.py"), "--dry-run"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        report = json.loads(result.stdout)
        self.assertIn("by_category", report)
        self.assertIn("definition", report["by_category"])


if __name__ == "__main__":
    unittest.main()
