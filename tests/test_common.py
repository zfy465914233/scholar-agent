"""Tests for the shared common.py utilities."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common import extract_entities, extract_wiki_links, load_json, normalize_date, now_iso, parse_frontmatter, resolve_link_target, safe_slug, slugify, write_json


class ParseFrontmatterTest(unittest.TestCase):
    def test_basic_scalar(self) -> None:
        raw = "---\ntitle: Hello\nid: card-1\n---\nBody text"
        meta, body = parse_frontmatter(raw)
        self.assertEqual("Hello", meta["title"])
        self.assertEqual("card-1", meta["id"])
        self.assertEqual("Body text", body)

    def test_list_values(self) -> None:
        raw = "---\ntags:\n  - alpha\n  - beta\n---\nBody"
        meta, body = parse_frontmatter(raw)
        self.assertEqual(["alpha", "beta"], meta["tags"])
        self.assertEqual("Body", body)

    def test_no_frontmatter(self) -> None:
        meta, body = parse_frontmatter("Just a body")
        self.assertEqual({}, meta)
        self.assertEqual("Just a body", body)

    def test_unclosed_frontmatter(self) -> None:
        meta, body = parse_frontmatter("---\ntitle: Oops\n")
        self.assertEqual({}, meta)

    def test_quoted_values(self) -> None:
        raw = "---\ntitle: 'Hello World'\n---\nBody"
        meta, _ = parse_frontmatter(raw)
        self.assertEqual("Hello World", meta["title"])

    def test_empty_list_value(self) -> None:
        raw = "---\ntags:\n---\nBody"
        meta, body = parse_frontmatter(raw)
        self.assertEqual([], meta["tags"])

    def test_mixed_scalars_and_lists(self) -> None:
        raw = "---\ntitle: Test\ntags:\n  - a\n  - b\nid: x\n---\nBody"
        meta, _ = parse_frontmatter(raw)
        self.assertEqual("Test", meta["title"])
        self.assertEqual(["a", "b"], meta["tags"])
        self.assertEqual("x", meta["id"])


class SlugifyTest(unittest.TestCase):
    def test_basic(self) -> None:
        self.assertEqual("hello-world", slugify("Hello World"))

    def test_special_chars(self) -> None:
        self.assertEqual("what-is-a-markov-chain", slugify("What is a Markov chain?"))

    def test_empty_fallback(self) -> None:
        self.assertEqual("untitled", slugify(""))

    def test_custom_fallback(self) -> None:
        self.assertEqual("note", slugify("", fallback="note"))

    def test_unicode(self) -> None:
        result = slugify("QPE雷达降雨估计")
        self.assertTrue(len(result) > 0)

    def test_leading_trailing_dashes(self) -> None:
        self.assertEqual("hello", slugify("---hello---"))


class SafeSlugTest(unittest.TestCase):
    def test_removes_dots(self) -> None:
        self.assertNotIn(".", safe_slug("../../etc/passwd"))

    def test_removes_slashes(self) -> None:
        self.assertNotIn("/", safe_slug("foo/bar/baz"))
        self.assertNotIn("\\", safe_slug("foo\\bar"))

    def test_normal_text(self) -> None:
        self.assertEqual("hello-world", safe_slug("Hello World"))

    def test_empty_input(self) -> None:
        self.assertEqual("untitled", safe_slug(""))


class LoadJsonTest(unittest.TestCase):
    def test_valid_file(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"key": "value"}, f)
            f.flush()
            result = load_json(Path(f.name))
        self.assertEqual({"key": "value"}, result)
        Path(f.name).unlink()

    def test_missing_file(self) -> None:
        result = load_json(Path("/tmp/nonexistent_lore_test.json"))
        self.assertEqual({}, result)

    def test_invalid_json(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("not json")
            f.flush()
            result = load_json(Path(f.name))
        self.assertEqual({}, result)
        Path(f.name).unlink()


class WriteJsonTest(unittest.TestCase):
    def test_creates_dirs_and_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "dir" / "test.json"
            write_json(path, {"a": 1})
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual({"a": 1}, loaded)

    def test_unicode_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.json"
            write_json(path, {"text": "中文测试"})
            content = path.read_text(encoding="utf-8")
            self.assertIn("中文测试", content)


class NormalizeDateTest(unittest.TestCase):
    def test_iso_date(self) -> None:
        self.assertEqual("2026-04-01", normalize_date("2026-04-01"))

    def test_iso_datetime(self) -> None:
        result = normalize_date("2026-04-01T12:30:00")
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("2026-04-01"))

    def test_slash_date(self) -> None:
        result = normalize_date("2026/04/01")
        self.assertIsNotNone(result)

    def test_none(self) -> None:
        self.assertIsNone(normalize_date(None))

    def test_empty(self) -> None:
        self.assertIsNone(normalize_date(""))
        self.assertIsNone(normalize_date("  "))

    def test_unparseable(self) -> None:
        result = normalize_date("not-a-date")
        self.assertEqual("not-a-date", result)


class NowIsoTest(unittest.TestCase):
    def test_returns_string(self) -> None:
        result = now_iso()
        self.assertIsInstance(result, str)
        self.assertIn("T", result)  # ISO format has T separator

    def test_recent_timestamp(self) -> None:
        result = now_iso()
        parsed = datetime.fromisoformat(result)
        self.assertIsNotNone(parsed.tzinfo)  # must be timezone-aware


class ExtractWikiLinksTest(unittest.TestCase):
    def test_single_link(self) -> None:
        self.assertEqual(["markov-chain"], extract_wiki_links("see [[markov-chain]] for details"))

    def test_multiple_links(self) -> None:
        result = extract_wiki_links("see [[a]] and [[b]] and [[a]]")
        self.assertEqual(["a", "b"], result)

    def test_no_links(self) -> None:
        self.assertEqual([], extract_wiki_links("no links here"))

    def test_preserves_order(self) -> None:
        result = extract_wiki_links("[[z]] [[a]] [[m]]")
        self.assertEqual(["z", "a", "m"], result)


class ResolveLinkTargetTest(unittest.TestCase):
    def test_exact_match(self) -> None:
        self.assertEqual("markov-chain", resolve_link_target("markov-chain", {"markov-chain", "other"}))

    def test_partial_match(self) -> None:
        self.assertEqual("markov-chain", resolve_link_target("chain", {"markov-chain", "other"}))

    def test_no_match(self) -> None:
        self.assertIsNone(resolve_link_target("quantum", {"markov-chain", "other"}))

    def test_exact_preferred_over_partial(self) -> None:
        self.assertEqual("chain", resolve_link_target("chain", {"chain", "markov-chain"}))

    def test_empty_ids(self) -> None:
        self.assertIsNone(resolve_link_target("anything", set()))


class ExtractEntitiesTest(unittest.TestCase):
    def test_capitalized_phrases(self) -> None:
        text = "The Transformer Architecture changed Natural Language Processing."
        entities = extract_entities(text)
        self.assertIn("The Transformer Architecture", entities)
        self.assertIn("Natural Language Processing", entities)

    def test_backtick_terms(self) -> None:
        text = "Use `torch.nn.Module` for layers and `Adam` optimizer."
        entities = extract_entities(text)
        self.assertIn("torch.nn.Module", entities)

    def test_dedup(self) -> None:
        text = "Monte Carlo is great. Monte Carlo is probabilistic."
        entities = extract_entities(text)
        self.assertEqual(entities.count("Monte Carlo"), 1)

    def test_stop_entities_filtered(self) -> None:
        text = "See Also more about Key Findings in the report."
        entities = extract_entities(text)
        self.assertNotIn("See Also", entities)
        self.assertNotIn("Key Findings", entities)

    def test_empty_text(self) -> None:
        self.assertEqual([], extract_entities(""))


if __name__ == "__main__":
    unittest.main()
