import json
import subprocess
from pathlib import Path
import unittest
import sys

_ROOT = Path(__file__).resolve().parents[1]


INDEX_PATH = _ROOT / "indexes" / "local" / "index.json"
FAKE_HARNESS = _ROOT / "tests" / "fake_research_harness.py"


class RenderAnswerBundleTest(unittest.TestCase):
    def setUp(self) -> None:
        build_index = subprocess.run(
            [sys.executable, "-m", "scholar_agent.engine.local_index", "--knowledge-root", "tests/fixtures", "--output", str(INDEX_PATH)],
            cwd=_ROOT,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        if build_index.returncode != 0:
            self.fail(
                f"failed to build local index for render bundle test: "
                f"stdout={build_index.stdout!r} stderr={build_index.stderr!r}"
            )

    def test_render_answer_bundle_outputs_model_facing_prompt_package(self) -> None:
        answer_result = subprocess.run(
            [
                sys.executable,
                "-m", "scholar_agent.engine.build_answer_context",
                "what is a markov chain",
                "--mode",
                "mixed",
                "--index",
                str(INDEX_PATH),
                "--research-script",
                str(FAKE_HARNESS),
            ],
            cwd=_ROOT,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(0, answer_result.returncode, msg=answer_result.stderr)

        bundle_result = subprocess.run(
            [
                sys.executable,
                "-m", "scholar_agent.engine.render_answer_bundle",
                "--answer-context-json",
                "-",
            ],
            cwd=_ROOT,
            input=answer_result.stdout,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(0, bundle_result.returncode, msg=bundle_result.stderr)

        payload = json.loads(bundle_result.stdout)
        self.assertIn("system_prompt", payload)
        self.assertIn("user_prompt", payload)
        self.assertIn("metadata", payload)
        self.assertIn("citations", payload)
        self.assertEqual("what is a markov chain", payload["metadata"]["query"])
        self.assertIn("direct support", payload["user_prompt"].lower())
        self.assertIn("uncertainty", payload["user_prompt"].lower())
        self.assertGreaterEqual(len(payload["citations"]), 1)


if __name__ == "__main__":
    unittest.main()
