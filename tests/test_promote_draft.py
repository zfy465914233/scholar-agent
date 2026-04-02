import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "indexes" / "local" / "index.json"
FAKE_HARNESS = ROOT / "tests" / "fake_research_harness.py"


class PromoteDraftTest(unittest.TestCase):
    def setUp(self) -> None:
        build_index = subprocess.run(
            [sys.executable, "scripts/local_index.py", "--knowledge-root", "tests/fixtures", "--output", str(INDEX_PATH)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if build_index.returncode != 0:
            self.fail(
                f"failed to build local index for promotion test: "
                f"stdout={build_index.stdout!r} stderr={build_index.stderr!r}"
            )

    def test_promote_draft_writes_card_candidate_into_knowledge_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            answer_context_path = temp_root / "answer-context.json"
            draft_path = temp_root / "distilled-markov-note.md"
            promoted_root = temp_root / "knowledge"

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
            answer_context_path.write_text(answer_result.stdout, encoding="utf-8")

            distill_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/distill_knowledge.py",
                    "--answer-context",
                    str(answer_context_path),
                    "--output",
                    str(draft_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, distill_result.returncode, msg=distill_result.stderr)

            promote_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/promote_draft.py",
                    "--draft",
                    str(draft_path),
                    "--knowledge-root",
                    str(promoted_root),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, promote_result.returncode, msg=promote_result.stderr)

            promoted_path = promoted_root / "markov_chain" / "candidate-what-is-a-markov-chain.md"
            self.assertTrue(promoted_path.exists(), "promoted card candidate should be written")

            text = promoted_path.read_text(encoding="utf-8")
            self.assertIn("type: definition", text)
            self.assertIn("origin: promoted_from_distilled_note", text)
            self.assertIn("source_refs:", text)
            self.assertIn("example-markov-chain-definition", text)
            self.assertIn("## Candidate Summary", text)

    def test_promote_draft_routes_additional_card_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            cases = [
                ("lp duality theorem", temp_root / "knowledge" / "linear_programming" / "candidate-lp-duality-theorem.md"),
                (
                    "compare qpe and iterative qpe",
                    temp_root / "knowledge" / "quantum_phase_estimation" / "candidate-compare-qpe-and-iterative-qpe.md",
                ),
                (
                    "decision on quantization deployment",
                    temp_root / "knowledge" / "model_quantization" / "candidate-decision-on-quantization-deployment.md",
                ),
            ]

            for query, expected_path in cases:
                draft_path = temp_root / f"{expected_path.stem}.md"
                draft_path.write_text(
                    "\n".join(
                        [
                            "---",
                            "id: temp",
                            f"title: Distilled Note - {query}",
                            "type: distilled_note",
                            "topic: research_distillation",
                            "source_refs:",
                            "  - answer_context",
                            "confidence: draft",
                            "updated_at: 2026-04-02",
                            "origin: generated_from_answer_context",
                            "---",
                            "",
                            "## Query",
                            "",
                            query,
                            "",
                            "## Route",
                            "",
                            "mixed",
                            "",
                            "## Direct Support",
                            "",
                            "- `seed-id`: placeholder support",
                            "",
                            "## Citations",
                            "",
                            "- `seed-id` (local / definition): Placeholder | /tmp/source.md",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )

                promote_result = subprocess.run(
                    [
                        sys.executable,
                        "scripts/promote_draft.py",
                        "--draft",
                        str(draft_path),
                        "--knowledge-root",
                        str(temp_root / "knowledge"),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, promote_result.returncode, msg=promote_result.stderr)
                self.assertTrue(expected_path.exists(), f"expected promoted path missing for query: {query}")


if __name__ == "__main__":
    unittest.main()
