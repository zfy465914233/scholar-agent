"""Tests for engineering card_type (改动 C): inference override + playbook rendering."""

import unittest

from scholar_agent.engine.close_knowledge_loop import (
    _build_body_sections,
    _card_id,
    _card_note_label,
    _card_note_tag,
    _infer_card_type,
)


class InferCardTypeTest(unittest.TestCase):
    def test_explicit_engineering_override(self):
        self.assertEqual(_infer_card_type("any query", {"card_type": "engineering"}), "engineering")

    def test_explicit_method_override(self):
        self.assertEqual(_infer_card_type("any query", {"card_type": "method"}), "method")

    def test_engineering_inferred_from_keyword_and_steps(self):
        answer = {"implementation_steps": [{"step": "do X"}]}
        self.assertEqual(_infer_card_type("how to implement verifier", answer), "engineering")

    def test_keyword_without_steps_falls_back_to_method(self):
        """how-to without structured steps -> method, not engineering (avoid false positives)."""
        self.assertEqual(_infer_card_type("how to implement verifier", {}), "method")

    def test_plain_query_is_knowledge(self):
        self.assertEqual(_infer_card_type("what is a markov chain", {}), "knowledge")


class CardMetadataEngineeringTest(unittest.TestCase):
    def test_label_id_tag_for_engineering(self):
        self.assertEqual(_card_note_label("engineering"), "Engineering Playbook")
        self.assertEqual(_card_id("engineering", "add-verifier"), "engineering-add-verifier")
        self.assertEqual(_card_note_tag("engineering"), "engineering-note")


class BuildBodyEngineeringTest(unittest.TestCase):
    def _eng(self):
        return {
            "prerequisites": ["Python 3.11", "docker running"],
            "implementation_steps": [
                {
                    "step": "Add verifier",
                    "files": ["app/x.py"],
                    "commands": ["pytest -q"],
                    "code": "def verify(): pass",
                },
                {"step": "Wire into loop"},
            ],
            "verification": "CI green and tests pass",
            "pitfalls": ["don't forget idempotency"],
            "rollback": "git revert the commit",
        }

    def test_engineering_renders_playbook_sections(self):
        e = self._eng()
        lines = _build_body_sections(
            "how to implement X",
            "Step-by-step landing guide.",
            [], [], [], [], [],
            "engineering",
            "", "",
            {},
            prerequisites=e["prerequisites"],
            implementation_steps=e["implementation_steps"],
            verification=e["verification"],
            pitfalls=e["pitfalls"],
            rollback=e["rollback"],
        )
        text = "\n".join(lines)
        self.assertIn("## 前置条件", text)
        self.assertIn("## 实现步骤", text)
        self.assertIn("### 步骤 1：Add verifier", text)
        self.assertIn("`app/x.py`", text)  # files rendered
        self.assertIn("```bash", text)  # commands rendered
        self.assertIn("```python", text)  # code rendered
        self.assertIn("def verify(): pass", text)
        self.assertIn("## 验收标准", text)
        self.assertIn("CI green", text)
        self.assertIn("## 陷阱与注意", text)
        self.assertIn("## 回滚方案", text)

    def test_knowledge_card_omits_engineering_sections(self):
        lines = _build_body_sections("what is X", "answer", [], [], [], [], [], "knowledge", "", "", {})
        text = "\n".join(lines)
        self.assertNotIn("## 实现步骤", text)
        self.assertNotIn("## 验收标准", text)

    def test_engineering_without_steps_skips_steps_section(self):
        # No implementation_steps -> no 实现步骤 heading, but other fields still render
        lines = _build_body_sections(
            "how to implement X", "guide", [], [], [], [], [], "engineering", "", "", {},
            prerequisites=["a"], implementation_steps=[], verification="ok", pitfalls=[], rollback="r",
        )
        text = "\n".join(lines)
        self.assertNotIn("## 实现步骤", text)
        self.assertIn("## 验收标准", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
