"""Unit tests for scholar_agent.engine.distill_knowledge build_markdown function.

Tests build_markdown with various payload shapes: all fields present, minimal
fields, empty lists, special characters, etc. Uses direct imports.
"""

import unittest

from scholar_agent.engine.distill_knowledge import build_markdown
from scholar_agent.engine.common import safe_slug


class TestBuildMarkdownAllFields(unittest.TestCase):
    """Tests with all payload fields populated."""

    def _full_payload(self):
        return {
            "query": "what is a markov chain",
            "route": "mixed",
            "direct_support": [
                {"evidence_id": "ev-001", "support": "Markov chains are stochastic processes"},
                {"evidence_id": "ev-002", "support": "They satisfy the Markov property"},
            ],
            "inference_notes": [
                "Markov chains are foundational in probability theory.",
                "They are used in MCMC sampling.",
            ],
            "uncertainty_notes": [
                "The exact convergence rate depends on the chain's properties.",
            ],
            "citations": [
                {
                    "evidence_id": "cite-001",
                    "origin": "local",
                    "source_type": "definition",
                    "title": "Markov Chain Definition",
                    "path": "/knowledge/markov-chain/definition.md",
                    "url": "",
                },
                {
                    "evidence_id": "cite-002",
                    "origin": "web",
                    "source_type": "paper",
                    "title": "Introduction to Stochastic Processes",
                    "path": "",
                    "url": "https://example.com/paper",
                },
            ],
        }

    def test_contains_frontmatter(self):
        md = build_markdown(self._full_payload())
        self.assertTrue(md.startswith("---\n"))
        self.assertIn("---\n\n## Query", md)

    def test_contains_id_with_slug(self):
        md = build_markdown(self._full_payload())
        expected_slug = safe_slug("what is a markov chain")
        self.assertIn(f"id: distilled-{expected_slug}", md)

    def test_contains_title(self):
        md = build_markdown(self._full_payload())
        self.assertIn("title: Distilled Note - what is a markov chain", md)

    def test_contains_type(self):
        md = build_markdown(self._full_payload())
        self.assertIn("type: distilled_note", md)

    def test_contains_confidence(self):
        md = build_markdown(self._full_payload())
        self.assertIn("confidence: draft", md)

    def test_contains_origin(self):
        md = build_markdown(self._full_payload())
        self.assertIn("origin: generated_from_answer_context", md)

    def test_query_section(self):
        md = build_markdown(self._full_payload())
        self.assertIn("## Query", md)
        self.assertIn("what is a markov chain", md)

    def test_route_section(self):
        md = build_markdown(self._full_payload())
        self.assertIn("## Route", md)
        self.assertIn("mixed", md)

    def test_direct_support_section(self):
        md = build_markdown(self._full_payload())
        self.assertIn("## Direct Support", md)
        self.assertIn("`ev-001`", md)
        self.assertIn("Markov chains are stochastic processes", md)
        self.assertIn("`ev-002`", md)

    def test_inference_notes_section(self):
        md = build_markdown(self._full_payload())
        self.assertIn("## Inference Notes", md)
        self.assertIn("Markov chains are foundational", md)
        self.assertIn("MCMC sampling", md)

    def test_uncertainty_notes_section(self):
        md = build_markdown(self._full_payload())
        self.assertIn("## Uncertainty Notes", md)
        self.assertIn("convergence rate", md)

    def test_citations_section(self):
        md = build_markdown(self._full_payload())
        self.assertIn("## Citations", md)
        self.assertIn("`cite-001`", md)
        self.assertIn("local / definition", md)
        self.assertIn("Markov Chain Definition", md)
        self.assertIn("/knowledge/markov-chain/definition.md", md)

    def test_citation_uses_url_when_no_path(self):
        md = build_markdown(self._full_payload())
        self.assertIn("`cite-002`", md)
        self.assertIn("web / paper", md)
        self.assertIn("https://example.com/paper", md)


class TestBuildMarkdownMinimalFields(unittest.TestCase):
    """Tests with minimal or empty payload fields."""

    def test_empty_payload(self):
        md = build_markdown({})
        self.assertIn("## Query", md)
        # Query should be empty string
        self.assertIn("## Route", md)
        self.assertIn("## Direct Support", md)
        self.assertIn("## Inference Notes", md)
        self.assertIn("## Uncertainty Notes", md)
        self.assertIn("## Citations", md)

    def test_query_only(self):
        md = build_markdown({"query": "test query"})
        self.assertIn("test query", md)
        self.assertIn("id: distilled-test-query", md)

    def test_empty_direct_support_list(self):
        md = build_markdown({"query": "q", "direct_support": []})
        # Should have the section heading but no items
        self.assertIn("## Direct Support", md)
        lines_after_ds = md.split("## Direct Support")[1].split("##")[0]
        self.assertNotIn("`", lines_after_ds)

    def test_empty_inference_notes(self):
        md = build_markdown({"query": "q", "inference_notes": []})
        self.assertIn("## Inference Notes", md)
        lines_after = md.split("## Inference Notes")[1].split("##")[0]
        self.assertNotIn("- ", lines_after.strip().split("\n")[0] if lines_after.strip() else "")

    def test_empty_uncertainty_notes(self):
        md = build_markdown({"query": "q", "uncertainty_notes": []})
        self.assertIn("## Uncertainty Notes", md)

    def test_empty_citations(self):
        md = build_markdown({"query": "q", "citations": []})
        self.assertIn("## Citations", md)

    def test_missing_query_defaults_to_empty(self):
        md = build_markdown({"route": "local"})
        slug = safe_slug("")
        self.assertIn(f"id: distilled-{slug}", md)


class TestBuildMarkdownEdgeCases(unittest.TestCase):
    """Tests for edge cases and special characters."""

    def test_query_with_special_characters(self):
        md = build_markdown({"query": "what is X? (detailed analysis)"})
        self.assertIn("what is X? (detailed analysis)", md)

    def test_long_query(self):
        long_query = "This is a very long query " * 10
        md = build_markdown({"query": long_query})
        self.assertIn(long_query.strip(), md)

    def test_unicode_query(self):
        md = build_markdown({"query": "马尔可夫链是什么"})
        self.assertIn("马尔可夫链是什么", md)

    def test_direct_support_item_format(self):
        payload = {
            "query": "q",
            "direct_support": [{"evidence_id": "abc-123", "support": "Test support text"}],
        }
        md = build_markdown(payload)
        self.assertIn("- `abc-123`: Test support text", md)

    def test_inference_notes_format(self):
        md = build_markdown({"query": "q", "inference_notes": ["First note", "Second note"]})
        self.assertIn("- First note", md)
        self.assertIn("- Second note", md)

    def test_uncertainty_notes_format(self):
        md = build_markdown({"query": "q", "uncertainty_notes": ["Uncertain about X"]})
        self.assertIn("- Uncertain about X", md)

    def test_citation_with_both_path_and_url_uses_path(self):
        payload = {
            "query": "q",
            "citations": [
                {
                    "evidence_id": "c1",
                    "origin": "local",
                    "source_type": "definition",
                    "title": "Title",
                    "path": "/local/path.md",
                    "url": "https://example.com",
                },
            ],
        }
        md = build_markdown(payload)
        # path is preferred (uses "or" logic: path or url)
        self.assertIn("/local/path.md", md)
        # URL is not included when path is present
        self.assertNotIn("https://example.com", md)

    def test_citation_with_no_path_or_url(self):
        payload = {
            "query": "q",
            "citations": [
                {
                    "evidence_id": "c1",
                    "origin": "local",
                    "source_type": "definition",
                    "title": "Title",
                },
            ],
        }
        md = build_markdown(payload)
        self.assertIn("`c1` (local / definition)", md)
        self.assertIn("Title", md)

    def test_output_ends_with_newline(self):
        md = build_markdown({"query": "q"})
        self.assertTrue(md.endswith("\n"))

    def test_frontmatter_is_complete(self):
        md = build_markdown({"query": "test"})
        parts = md.split("---\n")
        # Should have: empty, frontmatter block, then body
        self.assertGreaterEqual(len(parts), 3)


class TestBuildMarkdownStructure(unittest.TestCase):
    """Tests for structural integrity of the generated markdown."""

    def test_all_sections_present(self):
        md = build_markdown({"query": "q", "route": "r"})
        required_sections = [
            "## Query",
            "## Route",
            "## Direct Support",
            "## Inference Notes",
            "## Uncertainty Notes",
            "## Citations",
        ]
        for section in required_sections:
            with self.subTest(section=section):
                self.assertIn(section, md)

    def test_section_ordering(self):
        md = build_markdown({"query": "q", "route": "r"})
        query_pos = md.index("## Query")
        route_pos = md.index("## Route")
        ds_pos = md.index("## Direct Support")
        inf_pos = md.index("## Inference Notes")
        unc_pos = md.index("## Uncertainty Notes")
        cit_pos = md.index("## Citations")
        self.assertLess(query_pos, route_pos)
        self.assertLess(route_pos, ds_pos)
        self.assertLess(ds_pos, inf_pos)
        self.assertLess(inf_pos, unc_pos)
        self.assertLess(unc_pos, cit_pos)

    def test_tags_in_frontmatter(self):
        md = build_markdown({"query": "q"})
        self.assertIn("tags:", md)
        self.assertIn("  - distilled", md)
        self.assertIn("  - answer-context", md)

    def test_source_refs_in_frontmatter(self):
        md = build_markdown({"query": "q"})
        self.assertIn("source_refs:", md)
        self.assertIn("  - answer_context", md)

    def test_topic_in_frontmatter(self):
        md = build_markdown({"query": "q"})
        self.assertIn("topic: research_distillation", md)


class TestParseArgs(unittest.TestCase):
    """Tests for parse_args."""

    def test_required_args(self) -> None:
        from unittest.mock import patch
        from scholar_agent.engine.distill_knowledge import parse_args
        from pathlib import Path

        with patch("sys.argv", ["distill", "--answer-context", "/tmp/ctx.json", "--output", "/tmp/out.md"]):
            args = parse_args()
        self.assertEqual(Path(args.answer_context), Path("/tmp/ctx.json"))
        self.assertEqual(Path(args.output), Path("/tmp/out.md"))


class TestMain(unittest.TestCase):
    """Tests for the main() entry point."""

    def test_main_writes_markdown(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from scholar_agent.engine.distill_knowledge import main

        payload = {
            "query": "test query",
            "route": "local",
            "direct_support": [],
            "inference_notes": [],
            "uncertainty_notes": [],
            "citations": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            ctx = Path(tmp) / "ctx.json"
            ctx.write_text(json.dumps(payload), encoding="utf-8")
            out = Path(tmp) / "output.md"
            with patch("sys.argv", ["distill", "--answer-context", str(ctx), "--output", str(out)]):
                ret = main()
            self.assertEqual(ret, 0)
            self.assertTrue(out.exists())
            text = out.read_text(encoding="utf-8")
            self.assertIn("test query", text)
            self.assertIn("## Query", text)


if __name__ == "__main__":
    unittest.main()
