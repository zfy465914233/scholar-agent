"""Tests for validate_card_quality (F2 knowledge-card quality gate)."""

import tempfile
import unittest
from pathlib import Path

from scholar_agent.engine.knowledge_lifecycle import validate_card_quality


def _write_card(dir_: str, frontmatter: dict[str, object], body: str) -> str:
    fm_lines = ["---"]
    for k, v in frontmatter.items():
        fm_lines.append(f"{k}: {v}")
    fm_lines.append("---")
    content = "\n".join(fm_lines) + "\n" + body
    p = Path(dir_) / "card.md"
    p.write_text(content, encoding="utf-8")
    return str(p)


_VALID_FM: dict[str, object] = {
    "id": "c1",
    "title": "T",
    "type": "knowledge",
    "topic": "x",
    "confidence": "confirmed",
    "updated_at": "2026-06-17",
}


class TestValidateCardQuality(unittest.TestCase):
    def test_valid_card_no_errors(self) -> None:
        body = "## 回答\n" + "正文内容足够长。" * 30
        with tempfile.TemporaryDirectory() as tmp:
            q = validate_card_quality(_write_card(tmp, _VALID_FM, body))
            self.assertEqual(q["errors"], [])

    def test_engineering_type_accepted(self) -> None:
        # F2: CARD_TYPES was missing 'engineering' (schema lagged behind usage).
        fm = {**_VALID_FM, "type": "engineering"}
        body = "## 回答\n" + "正文内容足够长。" * 30
        with tempfile.TemporaryDirectory() as tmp:
            q = validate_card_quality(_write_card(tmp, fm, body))
            type_errors = [e for e in q["errors"] if e["field"] == "type"]
            self.assertEqual(type_errors, [])

    def test_missing_required_field_errors(self) -> None:
        fm = {k: v for k, v in _VALID_FM.items() if k != "topic"}
        body = "## 回答\n" + "x" * 400
        with tempfile.TemporaryDirectory() as tmp:
            q = validate_card_quality(_write_card(tmp, fm, body))
            self.assertTrue(any(e["field"] == "topic" for e in q["errors"]))

    def test_thin_body_warns(self) -> None:
        body = "短"
        with tempfile.TemporaryDirectory() as tmp:
            q = validate_card_quality(_write_card(tmp, _VALID_FM, body))
            self.assertTrue(any(w["field"] == "body" for w in q["warnings"]))

    def test_missing_file_returns_error(self) -> None:
        q = validate_card_quality("/nonexistent/card.md")
        self.assertEqual(len(q["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
