"""Tests for scholar_agent.engine.academic.innovation_scorer pure functions."""

import json
import unittest

from scholar_agent.engine.academic.innovation_scorer import (
    _fallback_heuristic,
    _parse_llm_response,
    innovation_pre_filter,
)


class TestInnovationPreFilter(unittest.TestCase):
    """Tests for innovation_pre_filter(papers, config, max_candidates)."""

    def _make_config(self, keywords=None):
        """Build a minimal config dict with a single research domain."""
        return {
            "research_domains": {
                "test-domain": {
                    "keywords": keywords or [],
                },
            },
        }

    # ------------------------------------------------------------------
    # Basic scoring
    # ------------------------------------------------------------------

    def test_empty_papers_list(self):
        result = innovation_pre_filter([], self._make_config(["neural"]))
        self.assertEqual(result, [])

    def test_no_keywords_in_config(self):
        papers = [{"title": "Deep Learning", "summary": "A paper about deep learning."}]
        result = innovation_pre_filter(papers, self._make_config([]))
        self.assertEqual(len(result), 1)
        # No keyword boost, but might still get signal / red-flag scores
        self.assertIn("_heuristic_score", result[0])

    def test_title_keyword_boost_capped(self):
        """Title keyword boost should be capped at _MAX_HEURISTIC_TITLE_BOOST (4.0)."""
        keywords = [f"kw{i}" for i in range(10)]
        title = " ".join(keywords)
        papers = [{"title": title, "summary": "irrelevant " * 50}]
        result = innovation_pre_filter(papers, self._make_config(keywords))
        # Title boost contributes up to 4.0
        self.assertLessEqual(result[0]["_heuristic_score"], 4.0 + 10.0)  # plus possible signals

    def test_abstract_keyword_boost_capped(self):
        """Abstract keyword boost should be capped at _MAX_HEURISTIC_ABSTRACT_BOOST (3.0)."""
        keywords = [f"kw{i}" for i in range(10)]
        abstract = " ".join(keywords) + " " + ("padding " * 100)
        papers = [{"title": "some title", "summary": abstract}]
        result = innovation_pre_filter(papers, self._make_config(keywords))
        # Abstract boost max 3.0
        self.assertLessEqual(result[0]["_heuristic_score"], 3.0 + 10.0)

    def test_innovation_signal_boost(self):
        """Papers with innovation signal words in abstract get +3."""
        papers = [
            {"title": "Foo", "summary": "This is a novel approach to something. " + "padding " * 50},
        ]
        result = innovation_pre_filter(papers, self._make_config([]))
        # Should have at least 3.0 from innovation signals
        self.assertGreaterEqual(result[0]["_heuristic_score"], 3.0)

    def test_quantitative_signal_boost(self):
        """Papers with quantitative signals in abstract get +2."""
        papers = [
            {"title": "Foo", "summary": "Our method outperforms baseline. " + "padding " * 50},
        ]
        result = innovation_pre_filter(papers, self._make_config([]))
        self.assertGreaterEqual(result[0]["_heuristic_score"], 2.0)

    def test_red_flag_title_penalty(self):
        """Titles containing red-flag words get -5 penalty."""
        papers = [
            {"title": "A Survey of Deep Learning", "summary": "x " * 100},
        ]
        result = innovation_pre_filter(papers, self._make_config([]))
        self.assertLess(result[0]["_heuristic_score"], 0)

    def test_red_flag_abstract_penalty(self):
        """Abstracts containing red-flag phrases get -5 penalty."""
        papers = [
            {"title": "Some Title", "summary": "We present a survey of the field. " + "x " * 100},
        ]
        result = innovation_pre_filter(papers, self._make_config([]))
        self.assertLess(result[0]["_heuristic_score"], 0)

    def test_short_abstract_penalty(self):
        """Abstracts shorter than 200 chars get -5 penalty."""
        papers = [
            {"title": "Short Paper", "summary": "Too short"},
        ]
        result = innovation_pre_filter(papers, self._make_config([]))
        self.assertLess(result[0]["_heuristic_score"], 0)

    def test_max_candidates_limit(self):
        """Only max_candidates papers are returned."""
        papers = [{"title": f"Paper {i}", "summary": f"Abstract {i} " * 20} for i in range(30)]
        result = innovation_pre_filter(papers, self._make_config([]), max_candidates=5)
        self.assertEqual(len(result), 5)

    def test_sorted_by_score_desc(self):
        """Results should be sorted descending by heuristic score."""
        papers = [
            {"title": "Survey of Things", "summary": "We present a survey. " * 30},
            {"title": "Novel Method", "summary": "A novel approach that outperforms all. " * 20},
            {"title": "Average Paper", "summary": "Regular paper about methods. " * 20},
        ]
        config = self._make_config(["method"])
        result = innovation_pre_filter(papers, config)
        scores = [p["_heuristic_score"] for p in result]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_uses_abstract_field_as_fallback(self):
        """Should read from 'abstract' key when 'summary' is absent."""
        papers = [
            {"title": "Novel Work", "abstract": "A novel approach that achieves results. " * 20},
        ]
        result = innovation_pre_filter(papers, self._make_config([]))
        self.assertGreater(result[0]["_heuristic_score"], 0)

    def test_keyword_matching_is_case_insensitive(self):
        """Keywords should match case-insensitively."""
        papers = [
            {"title": "Deep Learning Methods", "summary": "x " * 50},
        ]
        result = innovation_pre_filter(papers, self._make_config(["deep learning"]))
        # Title match gives +2, abstract too short gives -5, net should be negative
        # but the keyword match should still be detected (score > pure -5)
        self.assertGreaterEqual(result[0]["_heuristic_score"], -3.0)

    def test_score_rounded_to_two_decimals(self):
        """Heuristic scores should be rounded to 2 decimal places."""
        papers = [{"title": "T", "summary": "A " * 100}]
        result = innovation_pre_filter(papers, self._make_config([]))
        for p in result:
            # Should have exactly 2 decimal places
            self.assertEqual(p["_heuristic_score"], round(p["_heuristic_score"], 2))


class TestParseLlmResponse(unittest.TestCase):
    """Tests for _parse_llm_response(raw, expected)."""

    def test_valid_json_in_markdown_fences(self):
        raw = '```json\n{"evaluations": [{"index": 1, "novelty": 4, "credibility": 5, "comment": "good"}]}\n```'
        result = _parse_llm_response(raw, 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["novelty"], 4)

    def test_valid_json_without_fences(self):
        raw = '{"evaluations": [{"index": 1, "novelty": 3, "credibility": 4, "comment": "ok"}]}'
        result = _parse_llm_response(raw, 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["credibility"], 4)

    def test_no_json_found_returns_defaults(self):
        raw = "This is just plain text with no JSON at all."
        result = _parse_llm_response(raw, 3)
        self.assertEqual(len(result), 3)
        for ev in result:
            self.assertEqual(ev["novelty"], 3)
            self.assertEqual(ev["credibility"], 3)

    def test_empty_evaluations_returns_defaults(self):
        raw = '{"evaluations": []}'
        result = _parse_llm_response(raw, 2)
        self.assertEqual(len(result), 2)
        for ev in result:
            self.assertEqual(ev["novelty"], 3)

    def test_well_formed_multiple_evaluations(self):
        data = {
            "evaluations": [
                {"index": 1, "novelty": 5, "credibility": 4, "comment": "excellent"},
                {"index": 2, "novelty": 2, "credibility": 3, "comment": "average"},
            ]
        }
        raw = json.dumps(data)
        result = _parse_llm_response(raw, 2)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["novelty"], 5)
        self.assertEqual(result[1]["comment"], "average")

    def test_json_with_leading_whitespace(self):
        raw = '   \n  {"evaluations": [{"index": 1, "novelty": 3, "credibility": 3, "comment": ""}]}'
        result = _parse_llm_response(raw, 1)
        self.assertEqual(len(result), 1)

    def test_invalid_json_returns_defaults(self):
        raw = '{"evaluations": [{"index": 1, "novelty": broken'
        result = _parse_llm_response(raw, 2)
        self.assertEqual(len(result), 2)

    def test_fenced_with_language_label(self):
        raw = '```json\n{"evaluations": [{"index": 1, "novelty": 5, "credibility": 5, "comment": "great"}]}\n```'
        result = _parse_llm_response(raw, 1)
        self.assertEqual(result[0]["novelty"], 5)

    def test_fenced_without_language_label(self):
        raw = '```\n{"evaluations": [{"index": 1, "novelty": 1, "credibility": 2, "comment": "weak"}]}\n```'
        result = _parse_llm_response(raw, 1)
        self.assertEqual(result[0]["novelty"], 1)


class TestFallbackHeuristic(unittest.TestCase):
    """Tests for _fallback_heuristic(candidates)."""

    def test_sets_llm_score_to_zero(self):
        candidates = [
            {"title": "A", "_heuristic_score": 5.0},
            {"title": "B", "_heuristic_score": 3.0},
        ]
        result = _fallback_heuristic(candidates)
        for p in result:
            self.assertEqual(p["_llm_score"], 0.0)

    def test_sets_heuristic_only_comment(self):
        candidates = [
            {"title": "A", "_heuristic_score": 5.0},
        ]
        result = _fallback_heuristic(candidates)
        self.assertEqual(result[0]["_llm_comment"], "(heuristic-only)")

    def test_normalizes_final_score(self):
        candidates = [
            {"title": "A", "_heuristic_score": 10.0},
            {"title": "B", "_heuristic_score": 5.0},
        ]
        result = _fallback_heuristic(candidates)
        # max_h = 10.0, so A should get 1.0, B should get 0.5
        scores = {p["title"]: p["_innovation_final_score"] for p in result}
        self.assertAlmostEqual(scores["A"], 1.0, places=3)
        self.assertAlmostEqual(scores["B"], 0.5, places=3)

    def test_sorted_by_final_score_desc(self):
        candidates = [
            {"title": "Low", "_heuristic_score": 1.0},
            {"title": "High", "_heuristic_score": 10.0},
            {"title": "Mid", "_heuristic_score": 5.0},
        ]
        result = _fallback_heuristic(candidates)
        titles = [p["title"] for p in result]
        self.assertEqual(titles, ["High", "Mid", "Low"])

    def test_empty_candidates(self):
        result = _fallback_heuristic([])
        self.assertEqual(result, [])

    def test_zero_heuristic_scores(self):
        """All zero scores should not cause division by zero."""
        candidates = [
            {"title": "A", "_heuristic_score": 0.0},
            {"title": "B", "_heuristic_score": 0.0},
        ]
        result = _fallback_heuristic(candidates)
        for p in result:
            self.assertEqual(p["_innovation_final_score"], 0.0)

    def test_missing_heuristic_score_treated_as_zero(self):
        candidates = [{"title": "No Score"}]
        result = _fallback_heuristic(candidates)
        self.assertEqual(result[0]["_innovation_final_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
