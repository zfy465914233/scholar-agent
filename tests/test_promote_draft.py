import subprocess
import tempfile
from pathlib import Path
import unittest
import sys

_ROOT = Path(__file__).resolve().parents[1]


INDEX_PATH = _ROOT / "indexes" / "local" / "index.json"
FAKE_HARNESS = _ROOT / "tests" / "fake_research_harness.py"


def _make_draft(path: Path, query: str) -> None:
    """Write a minimal distilled-note draft for the given query."""
    path.write_text(
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


class PromoteDraftTest(unittest.TestCase):
    def setUp(self) -> None:
        build_index = subprocess.run(
            [sys.executable, "-m", "scholar_agent.engine.local_index", "--knowledge-root", "tests/fixtures", "--output", str(INDEX_PATH)],
            cwd=_ROOT,
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
            # markov-chain is a major domain in the routing policy
            (promoted_root / "markov-chain").mkdir(parents=True)

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
                text=True,
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
                    str(draft_path),
                ],
                cwd=_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, distill_result.returncode, msg=distill_result.stderr)

            promote_result = subprocess.run(
                [
                    sys.executable,
                    "-m", "scholar_agent.engine.promote_draft",
                    "--draft",
                    str(draft_path),
                    "--knowledge-root",
                    str(promoted_root),
                ],
                cwd=_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, promote_result.returncode, msg=promote_result.stderr)

            promoted_path = promoted_root / "markov-chain" / "candidate-what-is-a-markov-chain.md"
            self.assertTrue(promoted_path.exists(), "promoted card candidate should be written")

            text = promoted_path.read_text(encoding="utf-8")
            self.assertIn("origin: promoted_from_distilled_note", text)
            self.assertIn("source_refs:", text)
            self.assertIn("example-markov-chain-definition", text)
            self.assertIn("## Candidate Summary", text)

    def test_promote_draft_routes_via_dynamic_matching(self) -> None:
        """Dynamic routing matches queries to pre-existing folders."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            knowledge_root = temp_root / "knowledge"
            # Create major domain folders matching the routing policy
            (knowledge_root / "operations-research" / "linear-programming").mkdir(parents=True)
            (knowledge_root / "qpe").mkdir(parents=True)
            (knowledge_root / "model-quantization").mkdir(parents=True)

            cases = [
                ("linear programming duality theorem", "operations-research/linear-programming"),
                ("qpe radar rainfall estimation", "qpe"),
                ("quantization compression deployment", "model-quantization"),
            ]

            for query, expected_folder in cases:
                draft_path = temp_root / f"draft-{query.replace(' ', '-')}.md"
                _make_draft(draft_path, query)

                promote_result = subprocess.run(
                    [
                        sys.executable,
                        "-m", "scholar_agent.engine.promote_draft",
                        "--draft",
                        str(draft_path),
                        "--knowledge-root",
                        str(knowledge_root),
                    ],
                    cwd=_ROOT,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, promote_result.returncode, msg=promote_result.stderr)
                expected_path = knowledge_root / expected_folder / f"candidate-{query.replace(' ', '-')}.md"
                self.assertTrue(expected_path.exists(), f"expected promoted path missing for query: {query}")


if __name__ == "__main__":
    unittest.main()
