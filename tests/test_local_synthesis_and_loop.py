"""Tests for local answer mode and knowledge loop closing."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
ANSWER_SCHEMA_PATH = ROOT / "schemas" / "answer.schema.json"
RESEARCH_NOTE_TEMPLATE = ROOT / "templates" / "knowledge.md"


class LocalAnswerSynthesisTest(unittest.TestCase):
    """Test --local-answer mode in synthesize_answer.py."""

    def test_local_answer_mode(self) -> None:
        """Local answer mode skips API call and uses provided JSON."""
        prompt_bundle = {
            "system_prompt": "test",
            "user_prompt": "test query",
            "metadata": {"query": "test", "route": "local-led"},
            "citations": [{"evidence_id": "e1", "origin": "local", "title": "T", "source_type": "def"}],
        }
        local_answer = {
            "answer": "test answer",
            "supporting_claims": [{"claim": "c1", "evidence_ids": ["e1"], "confidence": "high"}],
            "inferences": [], "uncertainty": [], "missing_evidence": [], "suggested_next_steps": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_path = Path(tmpdir) / "bundle.json"
            answer_path = Path(tmpdir) / "answer.json"
            bundle_path.write_text(json.dumps(prompt_bundle))
            answer_path.write_text(json.dumps(local_answer))

            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "synthesize_answer.py"),
                 "--prompt-bundle", str(bundle_path),
                 "--local-answer", str(answer_path)],
                capture_output=True, text=True, cwd=SCRIPTS,
            )
            self.assertEqual(0, result.returncode, msg=result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual("test", output["query"])
            self.assertEqual("test answer", output["answer"]["answer"])
            self.assertEqual(1, len(output["answer"]["supporting_claims"]))
            self.assertEqual("local", output["synthesis_meta"]["usage"]["source"])


class CloseKnowledgeLoopTest(unittest.TestCase):
    """Test the close_knowledge_loop.py script."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.knowledge_root = Path(cls._tmpdir.name) / "knowledge"
        cls.index_path = Path(cls._tmpdir.name) / "indexes" / "local" / "index.json"
        shutil.copytree(ROOT / "tests" / "fixtures", cls.knowledge_root)

        # Build an isolated index so tests never rewrite the active project index.
        subprocess.run(
            [sys.executable, str(SCRIPTS / "local_index.py"), "--knowledge-root", str(cls.knowledge_root), "--output", str(cls.index_path)],
            capture_output=True, text=True, cwd=ROOT,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_close_loop_creates_card_and_reindexes(self) -> None:
        answer = {
            "answer": "Test answer for loop closing",
            "supporting_claims": [],
            "inferences": ["test inference"],
            "uncertainty": [],
            "missing_evidence": [],
            "suggested_next_steps": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            answer_path = Path(tmpdir) / "answer.json"
            answer_path.write_text(json.dumps(answer))

            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "close_knowledge_loop.py"),
                 "--query", "test loop closing query",
                 "--answer", str(answer_path),
                 "--knowledge-root", str(self.knowledge_root),
                 "--index-output", str(self.index_path)],
                capture_output=True, text=True, cwd=ROOT,
            )
            self.assertEqual(0, result.returncode, msg=result.stderr)
            self.assertIn("Knowledge card written", result.stderr)

            # Verify card exists (find actual path from stderr)
            card_path = None
            for line in result.stderr.splitlines():
                if "Knowledge card written:" in line:
                    card_path = Path(line.split("Knowledge card written:")[1].strip())
                    break
            self.assertIsNotNone(card_path, "Should find card path in log output")
            self.assertTrue(card_path.exists(), "Card should be written to knowledge tree")
            # Card should be routed to a folder derived from the query
            self.assertIn("test-loop-closing", card_path.name)

            # Verify it's in the index
            index = json.loads(self.index_path.read_text(encoding="utf-8"))
            doc_ids = [d["doc_id"] for d in index["documents"]]
            self.assertIn("knowledge-test-loop-closing-query", doc_ids)

            # Clean up
            card_path.unlink()
            # Remove empty parent directory if it was created by this test
            try:
                card_path.parent.rmdir()
            except OSError:
                pass
            # Reindex without the test card
            subprocess.run(
                [sys.executable, str(SCRIPTS / "local_index.py"), "--knowledge-root", str(self.knowledge_root), "--output", str(self.index_path)],
                capture_output=True, text=True, cwd=ROOT,
            )

    def test_close_loop_card_has_all_sections(self) -> None:
        """Card written by close_knowledge_loop must contain all standard sections."""
        answer = {
            "answer": "Test answer",
            "supporting_claims": [
                {"claim": "c1", "evidence_ids": ["e1"], "confidence": "high"},
            ],
            "inferences": ["inf1"],
            "uncertainty": ["unc1"],
            "missing_evidence": ["miss1"],
            "suggested_next_steps": ["step1"],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            answer_path = Path(tmpdir) / "answer.json"
            answer_path.write_text(json.dumps(answer))

            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "close_knowledge_loop.py"),
                 "--query", "test schema validation query",
                 "--answer", str(answer_path),
                 "--knowledge-root", str(self.knowledge_root),
                 "--index-output", str(self.index_path)],
                capture_output=True, text=True, cwd=ROOT,
            )
            self.assertEqual(0, result.returncode, msg=result.stderr)

            card_path = None
            for line in result.stderr.splitlines():
                if "Knowledge card written:" in line:
                    card_path = Path(line.split("Knowledge card written:")[1].strip())
                    break
            self.assertIsNotNone(card_path, "Should find card path in log output")
            self.assertTrue(card_path.exists())
            content = card_path.read_text(encoding="utf-8")

            for section in [
                "## 问题", "## 回答", "## 支撑论据",
                "## 推论", "## 不确定性", "## 缺失证据",
                "## 建议后续步骤",
            ]:
                self.assertIn(section, content, f"Missing section: {section}")

            # Schema validation should produce no warnings
            self.assertNotIn("Schema warning", result.stderr)

            # Clean up
            card_path.unlink()
            subprocess.run(
                [sys.executable, str(SCRIPTS / "local_index.py"), "--knowledge-root", str(self.knowledge_root), "--output", str(self.index_path)],
                capture_output=True, text=True, cwd=ROOT,
            )

    def test_close_loop_warns_on_invalid_answer(self) -> None:
        """Card creation warns when answer JSON doesn't match schema."""
        answer = {"wrong_field": "no answer or claims"}

        with tempfile.TemporaryDirectory() as tmpdir:
            answer_path = Path(tmpdir) / "answer.json"
            answer_path.write_text(json.dumps(answer))

            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "close_knowledge_loop.py"),
                 "--query", "test invalid schema query",
                 "--answer", str(answer_path),
                 "--knowledge-root", str(self.knowledge_root),
                 "--index-output", str(self.index_path)],
                capture_output=True, text=True, cwd=ROOT,
            )
            self.assertEqual(0, result.returncode, msg=result.stderr)
            self.assertIn("Schema warning", result.stderr)
            self.assertIn("Missing required field: answer", result.stderr)
            self.assertIn("Missing required field: supporting_claims", result.stderr)

            # Clean up
            card_path = None
            for line in result.stderr.splitlines():
                if "Knowledge card written:" in line:
                    card_path = Path(line.split("Knowledge card written:")[1].strip())
                    break
            if card_path and card_path.exists():
                card_path.unlink()
            subprocess.run(
                [sys.executable, str(SCRIPTS / "local_index.py"), "--knowledge-root", str(self.knowledge_root), "--output", str(self.index_path)],
                capture_output=True, text=True, cwd=ROOT,
            )


class AnswerSchemaTest(unittest.TestCase):
    """Test the answer schema file and knowledge note template."""

    def test_answer_schema_file_exists_and_is_valid_json(self) -> None:
        self.assertTrue(ANSWER_SCHEMA_PATH.exists(), "schemas/answer.schema.json must exist")
        schema = json.loads(ANSWER_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertIn("required", schema)
        self.assertIn("answer", schema["required"])
        self.assertIn("supporting_claims", schema["required"])

    def test_answer_schema_has_all_standard_fields(self) -> None:
        schema = json.loads(ANSWER_SCHEMA_PATH.read_text(encoding="utf-8"))
        props = schema["properties"]
        for field in [
            "answer", "supporting_claims", "inferences",
            "uncertainty", "missing_evidence", "suggested_next_steps",
        ]:
            self.assertIn(field, props, f"Schema missing field: {field}")

    def test_knowledge_template_exists_and_has_sections(self) -> None:
        self.assertTrue(RESEARCH_NOTE_TEMPLATE.exists(), "knowledge.md template must exist")
        content = RESEARCH_NOTE_TEMPLATE.read_text(encoding="utf-8")
        for section in [
            "## 目录", "## 第一节", "## 第二节",
            "## 公式速查表", "## 参考文献", "## See Also",
        ]:
            self.assertIn(section, content, f"Template missing section: {section}")


if __name__ == "__main__":
    unittest.main()
