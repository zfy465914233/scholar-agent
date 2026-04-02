import json
import subprocess
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "indexes" / "local" / "index.json"
FAKE_HARNESS = ROOT / "tests" / "fake_research_harness.py"


class RenderAnswerBundleTest(unittest.TestCase):
    def setUp(self) -> None:
        build_index = subprocess.run(
            [sys.executable, "scripts/local_index.py", "--output", str(INDEX_PATH)],
            cwd=ROOT,
            capture_output=True,
            text=True,
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
                "scripts/build_answer_context.py",
                "what is a markov chain",
                "--mode",
                "mixed",
                "--index",
                str(INDEX_PATH),
                "--research-script",
                str(FAKE_HARNESS),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, answer_result.returncode, msg=answer_result.stderr)

        bundle_result = subprocess.run(
            [
                sys.executable,
                "scripts/render_answer_bundle.py",
                "--answer-context-json",
                "-",
            ],
            cwd=ROOT,
            input=answer_result.stdout,
            capture_output=True,
            text=True,
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
