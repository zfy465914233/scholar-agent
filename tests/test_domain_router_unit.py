"""Tests for domain_router pure functions."""

import tempfile
import unittest
from pathlib import Path

from scholar_agent.engine.domain_router import (
    _parse_frontmatter_title_tags,
    _score_tokens,
    _subdomain_tokens,
    _tokens_from_slug,
    get_domain_tree,
    match_existing_folders,
    match_route,
)


class TestTokensFromSlug(unittest.TestCase):
    def test_simple_slug(self) -> None:
        tokens = _tokens_from_slug("markov-chain")
        self.assertIn("markov-chain", tokens)
        self.assertIn("markov", tokens)
        self.assertIn("chain", tokens)

    def test_single_word(self) -> None:
        tokens = _tokens_from_slug("math")
        self.assertIn("math", tokens)

    def test_filters_short_parts(self) -> None:
        tokens = _tokens_from_slug("a-bc")
        self.assertNotIn("a", tokens)
        self.assertIn("bc", tokens)


class TestScoreTokens(unittest.TestCase):
    def test_exact_match(self) -> None:
        score = _score_tokens("markov chain", ["markov"])
        self.assertGreater(score, 0)

    def test_no_match(self) -> None:
        score = _score_tokens("completely different", ["markov"])
        self.assertEqual(score, 0)

    def test_empty_tokens(self) -> None:
        self.assertEqual(_score_tokens("query", []), 0)

    def test_empty_query(self) -> None:
        self.assertEqual(_score_tokens("", ["token"]), 0)

    def test_chinese_query(self) -> None:
        score = _score_tokens("马尔可夫链", ["马尔可夫"])
        self.assertGreater(score, 0)


class TestSubdomainTokens(unittest.TestCase):
    def test_empty_slug(self) -> None:
        self.assertEqual(_subdomain_tokens("", {}), [])

    def test_with_policy(self) -> None:
        tokens = _subdomain_tokens("lp", {"label": "Linear Programming", "aliases": ["LP"]})
        self.assertIn("lp", tokens)
        self.assertIn("linear programming", tokens)
        self.assertIn("lp", tokens)

    def test_deduplicates(self) -> None:
        tokens = _subdomain_tokens("test", {"aliases": ["test"]})
        self.assertEqual(tokens.count("test"), 1)


class TestParseFrontmatterTitleTags(unittest.TestCase):
    def test_basic_frontmatter(self) -> None:
        text = "---\ntitle: My Card\ntags: [a, b]\n---\nBody"
        title, tags = _parse_frontmatter_title_tags(text)
        self.assertEqual(title, "My Card")
        self.assertEqual(tags, ["a", "b"])

    def test_quoted_title(self) -> None:
        text = '---\ntitle: "Complex Title"\n---\nBody'
        title, _ = _parse_frontmatter_title_tags(text)
        self.assertEqual(title, "Complex Title")

    def test_block_tags(self) -> None:
        text = "---\ntitle: T\ntags:\n  - tag1\n  - tag2\n---\nBody"
        _, tags = _parse_frontmatter_title_tags(text)
        self.assertEqual(tags, ["tag1", "tag2"])

    def test_no_frontmatter(self) -> None:
        title, tags = _parse_frontmatter_title_tags("Just body text")
        self.assertEqual(title, "")
        self.assertEqual(tags, [])

    def test_unclosed_frontmatter(self) -> None:
        title, _tags = _parse_frontmatter_title_tags("---\ntitle: T\n")
        self.assertEqual(title, "")


class TestMatchExistingFolders(unittest.TestCase):
    def test_matches_by_slug(self) -> None:
        tree = {"operations-research": {"linear-programming": Path("/tmp/or/lp")}}
        result = match_existing_folders("linear programming basics", tree)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "operations-research")
        self.assertEqual(result[1], "linear-programming")

    def test_no_match(self) -> None:
        tree = {"physics": {"quantum": Path("/tmp/ph/q")}}
        result = match_existing_folders("cooking recipes", tree)
        self.assertIsNone(result)

    def test_empty_tree(self) -> None:
        self.assertIsNone(match_existing_folders("anything", {}))


class TestMatchRoute(unittest.TestCase):
    def test_matches_policy(self) -> None:
        policy = {
            "major_domains": {
                "ml": {"label": "Machine Learning", "subdomains": {"nlp": {"label": "NLP", "aliases": ["natural language processing"]}}},
            },
        }
        tree = {"ml": {"nlp": Path("/tmp/ml/nlp")}}
        result = match_route("natural language processing", policy, tree)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "ml")

    def test_empty_policy(self) -> None:
        self.assertIsNone(match_route("query", {}, {}))


class TestGetDomainTree(unittest.TestCase):
    def test_builds_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ml" / "nlp").mkdir(parents=True)
            (root / "ml" / "cv").mkdir(parents=True)
            tree = get_domain_tree(root)
            self.assertIn("ml", tree)
            self.assertIn("nlp", tree["ml"])
            self.assertIn("cv", tree["ml"])


if __name__ == "__main__":
    unittest.main()
