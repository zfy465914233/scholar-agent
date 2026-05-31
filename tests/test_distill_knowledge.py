import subprocess
import tempfile
from pathlib import Path
import unittest
import sys

_ROOT = Path(__file__).resolve().parents[1]


INDEX_PATH = _ROOT / "indexes" / "local" / "index.json"
FAKE_HARNESS = _ROOT / "tests" / "fake_research_harness.py"


class DistillKnowledgeTest(unittest.TestCase):
    def setUp(self) -> None:
        build_index = subprocess.run(
            [sys.executable, "-m", "scholar_agent.engine.local_index", "--knowledge-root", "tests/fixtures", "--output", str(INDEX_PATH)],
            cwd=_ROOT,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        if build_index.returncode != 0:
            self.fail(
                f"failed to build local index for distillation test: "
                f"stdout={build_index.stdout!r} stderr={build_index.stderr!r}"
            )

    def test_distill_knowledge_writes_reusable_markdown_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            answer_context_path = Path(temp_dir) / "answer-context.json"
            draft_output_path = Path(temp_dir) / "distilled-markov-note.md"

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
            answer_context_path.write_text(answer_result.stdout, encoding="utf-8")

            distill_result = subprocess.run(
                [
                    sys.executable,
                    "-m", "scholar_agent.engine.distill_knowledge",
                    "--answer-context",
                    str(answer_context_path),
                    "--output",
                    str(draft_output_path),
                ],
                cwd=_ROOT,
                capture_output=True,
                text=True, encoding="utf-8",
            )

            self.assertEqual(0, distill_result.returncode, msg=distill_result.stderr)
            self.assertTrue(draft_output_path.exists(), "distilled markdown draft should be created")

            text = draft_output_path.read_text(encoding="utf-8")
            self.assertIn("title: Distilled Note - what is a markov chain", text)
            self.assertIn("type: distilled_note", text)
            self.assertIn("confidence: draft", text)
            self.assertIn("## Direct Support", text)
            self.assertIn("example-markov-chain-definition", text)
            self.assertIn("## Citations", text)


if __name__ == "__main__":
    unittest.main()
