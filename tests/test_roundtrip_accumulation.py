import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FAKE_HARNESS = ROOT / "tests" / "fake_research_harness.py"


class RoundTripAccumulationTest(unittest.TestCase):
    def test_promoted_candidate_is_reindexed_and_retrievable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            knowledge_root = temp_root / "knowledge"
            index_path = temp_root / "indexes" / "local" / "index.json"
            answer_context_path = temp_root / "answer-context.json"
            draft_path = temp_root / "distilled-markov-note.md"

            scaffold_dirs = [
                knowledge_root / "cards" / "definitions",
                knowledge_root / "cards" / "methods",
                knowledge_root / "cards" / "theorems",
                knowledge_root / "cards" / "derivations",
                knowledge_root / "cards" / "comparisons",
                knowledge_root / "cards" / "decision_records",
            ]
            for path in scaffold_dirs:
                path.mkdir(parents=True, exist_ok=True)

            seed_card = knowledge_root / "cards" / "definitions" / "markov-chain-definition.md"
            seed_card.write_text(
                """---
id: markov-chain-definition
title: Markov Chain Definition
type: definition
topic: stochastic_processes
tags:
  - markov-chain
  - probability
source_refs:
  - local:seed-card
confidence: confirmed
updated_at: 2026-04-01
origin: local_seed
---

## Core Statement

A Markov chain is a stochastic process whose next-state distribution depends only on the current state.
""",
                encoding="utf-8",
            )

            build_index_result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "local_index.py"),
                    "--knowledge-root",
                    str(knowledge_root),
                    "--output",
                    str(index_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, build_index_result.returncode, msg=build_index_result.stderr)

            answer_result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_answer_context.py"),
                    "what is a markov chain",
                    "--mode",
                    "mixed",
                    "--index",
                    str(index_path),
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
                    str(ROOT / "scripts" / "distill_knowledge.py"),
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
                    str(ROOT / "scripts" / "promote_draft.py"),
                    "--draft",
                    str(draft_path),
                    "--knowledge-root",
                    str(knowledge_root),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, promote_result.returncode, msg=promote_result.stderr)

            rebuild_index_result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "local_index.py"),
                    "--knowledge-root",
                    str(knowledge_root),
                    "--output",
                    str(index_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, rebuild_index_result.returncode, msg=rebuild_index_result.stderr)

            retrieve_result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "local_retrieve.py"),
                    "distilled markov chain",
                    "--index",
                    str(index_path),
                    "--limit",
                    "5",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, retrieve_result.returncode, msg=retrieve_result.stderr)

            payload = json.loads(retrieve_result.stdout)
            doc_ids = [item["doc_id"] for item in payload["results"]]
            self.assertIn("distilled-what-is-a-markov-chain", doc_ids)


if __name__ == "__main__":
    unittest.main()
