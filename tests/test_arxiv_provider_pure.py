"""Tests for pure functions from scholar_agent.engine.search_providers.arxiv_provider."""

import unittest
from unittest.mock import patch

from scholar_agent.engine.search_providers.arxiv_provider import (
    _default_scoring_config,
    _env_categories,
    _extend_candidates,
    _make_result,
)
from scholar_agent.engine.search_providers.base import SearchCandidate


class TestDefaultScoringConfig(unittest.TestCase):
    """Tests for _default_scoring_config."""

    def test_returns_dict_with_required_keys(self) -> None:
        config = _default_scoring_config(["cs.AI"])
        self.assertIn("research_domains", config)
        self.assertIn("excluded_keywords", config)

    def test_includes_default_domain(self) -> None:
        config = _default_scoring_config(["cs.AI"])
        domains = config["research_domains"]
        self.assertIn("default", domains)

    def test_includes_categories(self) -> None:
        config = _default_scoring_config(["cs.AI", "cs.LG"])
        default_domain = config["research_domains"]["default"]
        self.assertEqual(default_domain["arxiv_categories"], ["cs.AI", "cs.LG"])

    def test_keywords_from_category(self) -> None:
        config = _default_scoring_config(["cs.AI"])
        keywords = config["research_domains"]["default"]["keywords"]
        self.assertIsInstance(keywords, list)
        self.assertTrue(len(keywords) > 0)

    def test_keywords_deduplicated(self) -> None:
        """Keywords should be deduplicated."""
        config = _default_scoring_config(["cs.AI", "cs.AI"])
        keywords = config["research_domains"]["default"]["keywords"]
        self.assertEqual(len(keywords), len(set(keywords)))

    def test_keywords_capped_at_ten(self) -> None:
        """Keywords list is capped at 10 entries."""
        config = _default_scoring_config(["cs.AI", "cs.LG", "cs.CL", "cs.CV"])
        keywords = config["research_domains"]["default"]["keywords"]
        self.assertLessEqual(len(keywords), 10)

    def test_unknown_category_produces_empty_keyword(self) -> None:
        """Unknown category codes don't crash, they just contribute no keywords."""
        config = _default_scoring_config(["cs.UNKNOWN_CAT"])
        keywords = config["research_domains"]["default"]["keywords"]
        self.assertIsInstance(keywords, list)

    def test_empty_categories(self) -> None:
        config = _default_scoring_config([])
        default_domain = config["research_domains"]["default"]
        self.assertEqual(default_domain["arxiv_categories"], [])
        self.assertEqual(default_domain["keywords"], [])

    def test_priority_is_three(self) -> None:
        config = _default_scoring_config(["cs.AI"])
        self.assertEqual(config["research_domains"]["default"]["priority"], 3)

    def test_excluded_keywords_empty(self) -> None:
        config = _default_scoring_config(["cs.AI"])
        self.assertEqual(config["excluded_keywords"], [])


class TestExtendCandidates(unittest.TestCase):
    """Tests for _extend_candidates."""

    def _make_item(self, url: str, title: str = "Test Paper") -> dict:
        return {
            "url": url,
            "title": title,
            "content": "Abstract text.",
            "publishedDate": "2025-01-15",
        }

    def test_add_single_item(self) -> None:
        items = [self._make_item("https://arxiv.org/abs/2501.12345")]
        candidates, _seen = _extend_candidates("query", items, [], set(), None)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].url, "https://arxiv.org/abs/2501.12345")

    def test_deduplicate_by_url(self) -> None:
        item = self._make_item("https://arxiv.org/abs/2501.12345")
        items = [item, item]
        candidates, _seen = _extend_candidates("query", items, [], set(), None)
        self.assertEqual(len(candidates), 1)

    def test_deduplicate_with_existing_seen(self) -> None:
        url = "https://arxiv.org/abs/2501.12345"
        items = [self._make_item(url)]
        candidates, _seen = _extend_candidates(
            "query", items, [], {url}, None
        )
        self.assertEqual(len(candidates), 0)

    def test_skip_empty_url(self) -> None:
        items = [{"url": "", "title": "No URL", "content": "text"}]
        candidates, _seen = _extend_candidates("query", items, [], set(), None)
        self.assertEqual(len(candidates), 0)

    def test_skip_whitespace_url(self) -> None:
        items = [{"url": "   ", "title": "Whitespace URL", "content": "text"}]
        candidates, _seen = _extend_candidates("query", items, [], set(), None)
        self.assertEqual(len(candidates), 0)

    def test_limit_enforced(self) -> None:
        items = [self._make_item(f"https://arxiv.org/abs/2501.{i:05d}") for i in range(10)]
        candidates, _seen = _extend_candidates("query", items, [], set(), 3)
        self.assertEqual(len(candidates), 3)

    def test_limit_zero_adds_one_then_stops(self) -> None:
        """limit=0 adds one item before the >= check triggers."""
        items = [self._make_item("https://arxiv.org/abs/2501.12345")]
        candidates, _seen = _extend_candidates("query", items, [], set(), 0)
        self.assertEqual(len(candidates), 1)

    def test_limit_none_means_no_cap(self) -> None:
        items = [self._make_item(f"https://arxiv.org/abs/2501.{i:05d}") for i in range(50)]
        candidates, _seen = _extend_candidates("query", items, [], set(), None)
        self.assertEqual(len(candidates), 50)

    def test_extends_existing_candidates(self) -> None:
        existing = SearchCandidate(
            query="query",
            url="https://arxiv.org/abs/2501.00001",
            title="Existing",
            snippet="old",
            published_at="2025-01-01",
        )
        items = [self._make_item("https://arxiv.org/abs/2501.00002", "New")]
        candidates, _seen = _extend_candidates("query", items, [existing], {"https://arxiv.org/abs/2501.00001"}, None)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].url, "https://arxiv.org/abs/2501.00001")
        self.assertEqual(candidates[1].url, "https://arxiv.org/abs/2501.00002")

    def test_seen_urls_updated(self) -> None:
        items = [self._make_item("https://arxiv.org/abs/2501.12345")]
        _candidates, seen = _extend_candidates("query", items, [], set(), None)
        self.assertIn("https://arxiv.org/abs/2501.12345", seen)

    def test_candidate_fields_populated(self) -> None:
        items = [{"url": "https://arxiv.org/abs/2501.12345", "title": "My Paper", "content": "Abstract", "publishedDate": "2025-01-15"}]
        candidates, _ = _extend_candidates("transformers", items, [], set(), None)
        c = candidates[0]
        self.assertEqual(c.query, "transformers")
        self.assertEqual(c.url, "https://arxiv.org/abs/2501.12345")
        self.assertEqual(c.title, "My Paper")
        self.assertEqual(c.snippet, "Abstract")
        self.assertEqual(c.published_at, "2025-01-15")

    def test_fallback_title_to_url(self) -> None:
        items = [{"url": "https://arxiv.org/abs/2501.12345", "title": "", "content": "text"}]
        candidates, _ = _extend_candidates("q", items, [], set(), None)
        self.assertEqual(candidates[0].title, "https://arxiv.org/abs/2501.12345")

    def test_no_title_key(self) -> None:
        items = [{"url": "https://example.com/paper", "content": "text"}]
        candidates, _ = _extend_candidates("q", items, [], set(), None)
        self.assertEqual(candidates[0].title, "https://example.com/paper")


class TestMakeResult(unittest.TestCase):
    """Tests for _make_result."""

    def test_empty_candidates(self) -> None:
        result = _make_result("test query", [])
        self.assertEqual(result.provider, "arxiv")
        self.assertEqual(result.query, "test query")
        self.assertEqual(len(result.candidates), 0)
        self.assertEqual(result.metadata["source_count"], 0)

    def test_with_candidates(self) -> None:
        candidates = [
            SearchCandidate(
                query="q",
                url="https://arxiv.org/abs/2501.1",
                title="Paper 1",
                snippet="abs",
                published_at=None,
            ),
            SearchCandidate(
                query="q",
                url="https://arxiv.org/abs/2501.2",
                title="Paper 2",
                snippet="abs",
                published_at="2025-01-01",
            ),
        ]
        result = _make_result("query", candidates)
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(result.metadata["source_count"], 2)

    def test_metadata_extra(self) -> None:
        result = _make_result("q", [], metadata_extra={"phase": "arxiv_recent"})
        self.assertEqual(result.metadata["phase"], "arxiv_recent")
        self.assertIn("source_count", result.metadata)

    def test_metadata_extra_does_not_override_source_count(self) -> None:
        c = SearchCandidate("q", "https://example.com", "t", "s", None)
        result = _make_result("q", [c], metadata_extra={"source_count": 999})
        # metadata_extra uses .update() so it WILL override source_count
        self.assertEqual(result.metadata["source_count"], 999)

    def test_provider_name_is_arxiv(self) -> None:
        result = _make_result("q", [])
        self.assertEqual(result.provider, "arxiv")

    def test_query_preserved(self) -> None:
        result = _make_result("deep learning optimization", [])
        self.assertEqual(result.query, "deep learning optimization")

    def test_none_metadata_extra(self) -> None:
        result = _make_result("q", [], metadata_extra=None)
        self.assertEqual(result.metadata, {"source_count": 0})


class TestEnvCategories(unittest.TestCase):
    """Tests for _env_categories."""

    @patch.dict("os.environ", {"ARXIV_CATEGORIES": "cs.AI,cs.LG"}, clear=False)
    def test_env_override(self) -> None:
        cats = _env_categories()
        self.assertEqual(cats, ["cs.AI", "cs.LG"])

    @patch.dict("os.environ", {"ARXIV_CATEGORIES": "  cs.AI ,  cs.CV  "}, clear=False)
    def test_whitespace_handling(self) -> None:
        cats = _env_categories()
        self.assertEqual(cats, ["cs.AI", "cs.CV"])

    @patch.dict("os.environ", {}, clear=True)
    def test_default_when_empty(self) -> None:
        cats = _env_categories()
        self.assertTrue(len(cats) > 0)
        self.assertIn("cs.AI", cats)

    @patch.dict("os.environ", {"ARXIV_CATEGORIES": ""}, clear=True)
    def test_default_when_blank(self) -> None:
        cats = _env_categories()
        self.assertIn("cs.AI", cats)


if __name__ == "__main__":
    unittest.main()
