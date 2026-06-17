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


class TestExtractSourceYear(unittest.TestCase):
    """F4: source-year extraction for freshness tracking."""

    def test_explicit_year_in_answer(self) -> None:
        from scholar_agent.engine.close_knowledge_loop import _extract_source_year

        self.assertEqual(_extract_source_year({"answer": "Per Smith (2019)..."}, []), "2019")

    def test_picks_earliest_year(self) -> None:
        from scholar_agent.engine.close_knowledge_loop import _extract_source_year

        self.assertEqual(_extract_source_year({"answer": "results from 2019 then 2022"}, []), "2019")

    def test_arxiv_id_fallback(self) -> None:
        from scholar_agent.engine.close_knowledge_loop import _extract_source_year

        # 2303.11366 -> 2023 when no explicit year is present.
        self.assertEqual(
            _extract_source_year({"answer": "see paper"}, ["https://arxiv.org/abs/2303.11366"]),
            "2023",
        )

    def test_no_year_returns_empty(self) -> None:
        from scholar_agent.engine.close_knowledge_loop import _extract_source_year

        self.assertEqual(_extract_source_year({"answer": "no year here"}, []), "")


class TestSourceFreshness(unittest.TestCase):
    """F4: validate_card_quality flags stale sources."""

    def test_old_source_warns(self) -> None:
        fm = {**_VALID_FM, "source_date": "2018"}
        body = "## 回答\n" + "x" * 400
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_card(tmp, fm, body)
            q = validate_card_quality(p, freshness_years=3.0, now_year=2026)
            self.assertTrue(any(w["field"] == "source_date" for w in q["warnings"]))

    def test_fresh_source_no_warn(self) -> None:
        fm = {**_VALID_FM, "source_date": "2025"}
        body = "## 回答\n" + "x" * 400
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_card(tmp, fm, body)
            q = validate_card_quality(p, freshness_years=3.0, now_year=2026)
            self.assertFalse(any(w["field"] == "source_date" for w in q["warnings"]))


if __name__ == "__main__":
    unittest.main()
