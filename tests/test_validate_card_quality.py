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


class TestDomainFreshness(unittest.TestCase):
    """F4: freshness threshold varies by domain."""

    def test_ai_domain_short_threshold_stale(self) -> None:
        # AI/ML threshold is 0.5y; a 1-year-old source should be flagged stale.
        fm = {**_VALID_FM, "domain": "ai", "source_date": "2025"}
        body = "## 回答\n" + "x" * 400
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_card(tmp, fm, body)
            q = validate_card_quality(p, now_year=2026)  # default freshness_years
            self.assertTrue(
                any(w["field"] == "source_date" for w in q["warnings"]),
                "AI-domain card with 1y-old source should be stale",
            )

    def test_ai_domain_case_insensitive(self) -> None:
        fm = {**_VALID_FM, "domain": "Machine-Learning", "source_date": "2025"}
        body = "## 回答\n" + "x" * 400
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_card(tmp, fm, body)
            q = validate_card_quality(p, now_year=2026)
            self.assertTrue(any(w["field"] == "source_date" for w in q["warnings"]))

    def test_default_domain_3y_not_stale(self) -> None:
        # Unknown domain -> 3y default; 1-year-old source stays fresh.
        fm = {**_VALID_FM, "domain": "economics", "source_date": "2025"}
        body = "## 回答\n" + "x" * 400
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_card(tmp, fm, body)
            q = validate_card_quality(p, now_year=2026)
            self.assertFalse(any(w["field"] == "source_date" for w in q["warnings"]))

    def test_default_domain_no_domain_field(self) -> None:
        # No domain field at all -> 3y default; 1y old stays fresh.
        fm = {**_VALID_FM, "source_date": "2025"}
        body = "## 回答\n" + "x" * 400
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_card(tmp, fm, body)
            q = validate_card_quality(p, now_year=2026)
            self.assertFalse(any(w["field"] == "source_date" for w in q["warnings"]))

    def test_history_domain_5y_not_stale(self) -> None:
        # History threshold is 5y; 3-year-old source stays fresh.
        fm = {**_VALID_FM, "domain": "history", "source_date": "2023"}
        body = "## 回答\n" + "x" * 400
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_card(tmp, fm, body)
            q = validate_card_quality(p, now_year=2026)
            self.assertFalse(any(w["field"] == "source_date" for w in q["warnings"]))

    def test_history_domain_stale_beyond_5y(self) -> None:
        fm = {**_VALID_FM, "domain": "math", "source_date": "2018"}
        body = "## 回答\n" + "x" * 400
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_card(tmp, fm, body)
            q = validate_card_quality(p, now_year=2026)
            self.assertTrue(any(w["field"] == "source_date" for w in q["warnings"]))

    def test_explicit_freshness_overrides_domain(self) -> None:
        # Caller passes freshness_years explicitly (even if == 3.0) ->
        # domain lookup is skipped; explicit value wins.
        # 1y old with explicit 0.5 threshold -> stale even for default domain.
        fm = {**_VALID_FM, "domain": "economics", "source_date": "2025"}
        body = "## 回答\n" + "x" * 400
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_card(tmp, fm, body)
            q = validate_card_quality(p, freshness_years=0.5, now_year=2026)
            self.assertTrue(any(w["field"] == "source_date" for w in q["warnings"]))

    def test_helper_defaults(self) -> None:
        from scholar_agent.engine.knowledge_lifecycle import _freshness_years_for

        self.assertEqual(_freshness_years_for(None), 3.0)
        self.assertEqual(_freshness_years_for("unknown-domain"), 3.0)
        self.assertEqual(_freshness_years_for("AI"), 0.5)
        self.assertEqual(_freshness_years_for("history"), 5.0)


def _fm_text(lines: list[str]) -> str:
    """Join frontmatter-builder lines and slice the YAML block between the fences."""
    joined = "\n".join(lines)
    start = joined.index("---\n") + 4
    end = joined.index("\n---", start)
    return joined[start:end]


class TestBuildFrontmatterG4Fields(unittest.TestCase):
    """G4: _build_frontmatter emits source_years / info_freshness / version."""

    @staticmethod
    def _call(answer_data: dict, major_domain: str = "economics") -> list[str]:
        from scholar_agent.engine.close_knowledge_loop import _build_frontmatter

        return _build_frontmatter(
            card_id="test-card",
            note_label="知识卡片",
            query="test query",
            card_type="knowledge",
            major_domain=major_domain,
            topic="t",
            tags=["t"],
            source_urls=answer_data.get("sources", []),
            now="2026-06-18",
            answer_data=answer_data,
            confidence="draft",
        )

    def test_three_g4_fields_present_single_year(self) -> None:
        lines = self._call({"answer": "Per Smith (2024)...", "sources": []})
        fm = _fm_text(lines)
        self.assertIn("source_years:", fm)
        self.assertIn('source_years: "2024"', fm)
        self.assertIn("info_freshness:", fm)
        self.assertIn("version:", fm)
        self.assertIn('version: "1.0"', fm)

    def test_source_years_range_for_multiple_years(self) -> None:
        lines = self._call({"answer": "results from 2022 then 2026", "sources": []})
        fm = _fm_text(lines)
        self.assertIn('source_years: "2022~2026"', fm)
        # source_date (F4) still present and keeps the earliest year.
        self.assertIn("source_date: 2022", fm)

    def test_source_years_unknown_when_no_year(self) -> None:
        lines = self._call({"answer": "no year here", "sources": []})
        fm = _fm_text(lines)
        self.assertIn('source_years: "unknown"', fm)
        # source_date omitted when no year; the new G4 fields still present.
        self.assertNotIn("source_date:", fm)
        self.assertIn("info_freshness:", fm)
        self.assertIn("未标定源年份", fm)

    def test_info_freshness_fast_change_domain(self) -> None:
        lines = self._call(
            {"answer": "GPT results in 2024", "sources": []},
            major_domain="machine-learning",
        )
        fm = _fm_text(lines)
        self.assertIn("变化较快", fm)
        self.assertIn("建议每 6 个月复核", fm)

    def test_info_freshness_slow_change_domain(self) -> None:
        lines = self._call(
            {"answer": "Per Smith (2024)", "sources": []},
            major_domain="economics",
        )
        fm = _fm_text(lines)
        self.assertIn("变化较慢", fm)
        self.assertNotIn("变化较快", fm)

    def test_version_always_present(self) -> None:
        # version: "1.0" regardless of source vintage.
        for answer in [{"answer": "2024"}, {"answer": "no year"}]:
            fm = _fm_text(self._call(answer))
            self.assertIn('version: "1.0"', fm)


class TestBuildKnowledgeCardG4Fields(unittest.TestCase):
    """G4: end-to-end — build_knowledge_card writes the three G4 fields to disk."""

    def test_card_file_has_g4_frontmatter(self) -> None:
        from scholar_agent.engine.close_knowledge_loop import build_knowledge_card

        with tempfile.TemporaryDirectory() as tmp:
            kr = Path(tmp) / "knowledge"
            kr.mkdir()
            answer_data = {
                "answer": "贝叶斯优化的核心是代理模型(2024 综述所述)。",
                "supporting_claims": [],
                "sources": ["https://arxiv.org/abs/2401.12345"],
                "language": "zh",
            }
            card_path = build_knowledge_card(
                "什么是贝叶斯优化",
                answer_data,
                None,
                kr,
            )
            content = card_path.read_text(encoding="utf-8")
            frontmatter = content.split("---", 2)[1]
            self.assertIn("source_years:", frontmatter)
            self.assertIn("info_freshness:", frontmatter)
            self.assertIn('version: "1.0"', frontmatter)


if __name__ == "__main__":
    unittest.main()
