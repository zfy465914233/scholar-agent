"""Unit tests for scholar_agent.engine.promote_draft pure functions.

Tests extract_section, parse_query, infer_card_type, collect_citation_ids,
and build_candidate_markdown using direct imports.
"""

import unittest

from scholar_agent.engine.common import safe_slug
from scholar_agent.engine.promote_draft import (
    build_candidate_markdown,
    collect_citation_ids,
    extract_section,
    infer_card_type,
    parse_query,
)

# ── extract_section ───────────────────────────────────────────────


class TestExtractSection(unittest.TestCase):
    def test_existing_section(self):
        text = "## Query\n\nWhat is markov chain?\n\n## Route\n\nmixed"
        lines = extract_section(text, "Query")
        self.assertEqual(lines, ["What is markov chain?"])

    def test_missing_section(self):
        text = "## Route\n\nmixed"
        lines = extract_section(text, "Query")
        self.assertEqual(lines, [])

    def test_multi_line_section(self):
        text = "## Query\n\nLine one\nLine two\nLine three\n\n## Route\n\nmixed"
        lines = extract_section(text, "Query")
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "Line one")
        self.assertEqual(lines[1], "Line two")
        self.assertEqual(lines[2], "Line three")

    def test_section_at_end_of_document(self):
        text = "## Citations\n\n`cite-001`\n`cite-002`"
        lines = extract_section(text, "Citations")
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "`cite-001`")
        self.assertEqual(lines[1], "`cite-002`")

    def test_empty_section(self):
        text = "## Query\n\n## Route\n\nmixed"
        lines = extract_section(text, "Query")
        self.assertEqual(lines, [])

    def test_section_with_blank_lines(self):
        text = "## Query\n\nFirst line\n\n\nSecond line\n\n## Route\n\nend"
        lines = extract_section(text, "Query")
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0], "First line")
        self.assertEqual(lines[1], "")
        self.assertEqual(lines[2], "")
        self.assertEqual(lines[3], "Second line")

    def test_lines_are_rstripped(self):
        text = "## Query\n\nLine with trailing spaces   \n\n## Route\n\nend"
        lines = extract_section(text, "Query")
        self.assertEqual(lines[0], "Line with trailing spaces")

    def test_different_heading_level_not_matched(self):
        text = "# Query\n\nNot matched\n\n## Query\n\nMatched"
        lines = extract_section(text, "Query")
        self.assertEqual(lines, ["Matched"])

    def test_no_headings_at_all(self):
        text = "Just plain text."
        lines = extract_section(text, "Query")
        self.assertEqual(lines, [])

    def test_heading_marker_includes_newline(self):
        """The marker is '## Heading\\n', so '## Heading' without trailing newline won't match."""
        text = "## Query"  # no trailing newline
        lines = extract_section(text, "Query")
        self.assertEqual(lines, [])

    def test_multiple_sections_extracts_correct_one(self):
        text = (
            "## Query\n\nFirst query\n\n"
            "## Route\n\nmixed\n\n"
            "## Direct Support\n\nSome support\n\n"
            "## Citations\n\n`cite-1`"
        )
        lines = extract_section(text, "Direct Support")
        self.assertEqual(lines, ["Some support"])


# ── parse_query ────────────────────────────────────────────────────


class TestParseQuery(unittest.TestCase):
    def test_extract_query_from_section(self):
        text = "## Query\n\nWhat is a markov chain?\n\n## Route\n\nmixed"
        result = parse_query(text)
        self.assertEqual(result, "What is a markov chain?")

    def test_missing_query_returns_default(self):
        text = "## Route\n\nmixed"
        result = parse_query(text)
        self.assertEqual(result, "untitled query")

    def test_empty_query_returns_default(self):
        text = "## Query\n\n## Route\n\nmixed"
        result = parse_query(text)
        self.assertEqual(result, "untitled query")

    def test_query_with_leading_whitespace(self):
        text = "## Query\n\n   what is this?   \n\n## Route\n\nmixed"
        result = parse_query(text)
        self.assertEqual(result, "what is this?")

    def test_multiline_query_takes_first_line(self):
        text = "## Query\n\nFirst line\nSecond line\n\n## Route\n\nmixed"
        result = parse_query(text)
        self.assertEqual(result, "First line")


# ── infer_card_type ────────────────────────────────────────────────


class TestInferCardType(unittest.TestCase):
    def test_how_to_keyword(self):
        self.assertEqual(infer_card_type("How to train a model"), "method")

    def test_implement_keyword(self):
        self.assertEqual(infer_card_type("Implement a linked list"), "method")

    def test_deploy_keyword(self):
        self.assertEqual(infer_card_type("Deploy to production"), "method")

    def test_train_keyword(self):
        self.assertEqual(infer_card_type("Train a neural network"), "method")

    def test_build_keyword(self):
        self.assertEqual(infer_card_type("Build a REST API"), "method")

    def test_configure_keyword(self):
        self.assertEqual(infer_card_type("Configure the system"), "method")

    def test_setup_keyword(self):
        self.assertEqual(infer_card_type("Setup the environment"), "method")

    def test_install_keyword(self):
        self.assertEqual(infer_card_type("Install dependencies"), "method")

    def test_run_keyword(self):
        self.assertEqual(infer_card_type("Run the server"), "method")

    def test_optimize_keyword(self):
        self.assertEqual(infer_card_type("Optimize the pipeline"), "method")

    def test_tune_keyword(self):
        self.assertEqual(infer_card_type("Tune hyperparameters"), "method")

    def test_debug_keyword(self):
        self.assertEqual(infer_card_type("Debug the error"), "method")

    def test_fix_keyword(self):
        self.assertEqual(infer_card_type("Fix the bug"), "method")

    def test_procedure_keyword(self):
        self.assertEqual(infer_card_type("Procedure for deployment"), "method")

    def test_algorithm_keyword(self):
        self.assertEqual(infer_card_type("Algorithm for sorting"), "method")

    def test_knowledge_default(self):
        self.assertEqual(infer_card_type("What is a markov chain"), "knowledge")

    def test_definition_query(self):
        self.assertEqual(infer_card_type("Define supervised learning"), "knowledge")

    def test_comparison_query(self):
        self.assertEqual(infer_card_type("Compare LSTM and GRU"), "knowledge")

    def test_case_insensitive(self):
        self.assertEqual(infer_card_type("HOW TO DEPLOY"), "method")

    def test_keyword_in_middle_of_query(self):
        self.assertEqual(infer_card_type("How do I implement a binary search tree"), "method")

    def test_empty_query(self):
        self.assertEqual(infer_card_type(""), "knowledge")

    def test_query_with_only_whitespace(self):
        self.assertEqual(infer_card_type("   "), "knowledge")


# ── collect_citation_ids ──────────────────────────────────────────


class TestCollectCitationIds(unittest.TestCase):
    def test_single_citation(self):
        text = "## Citations\n\n`cite-001` (local / definition): Title | /path"
        ids = collect_citation_ids(text)
        self.assertEqual(ids, ["cite-001"])

    def test_multiple_citations(self):
        text = (
            "## Citations\n\n"
            "`cite-001` (local / definition): Title A | /path/a\n"
            "`cite-002` (web / paper): Title B | https://example.com"
        )
        ids = collect_citation_ids(text)
        self.assertEqual(len(ids), 2)
        self.assertIn("cite-001", ids)
        self.assertIn("cite-002", ids)

    def test_no_citations_section(self):
        text = "## Query\n\nSome query"
        ids = collect_citation_ids(text)
        self.assertEqual(ids, [])

    def test_empty_citations_section(self):
        text = "## Citations\n\n## Other Section\n\ncontent"
        ids = collect_citation_ids(text)
        self.assertEqual(ids, [])

    def test_citations_with_complex_ids(self):
        text = "## Citations\n\n`example-markov-chain-definition` (local / definition): Title"
        ids = collect_citation_ids(text)
        self.assertEqual(ids, ["example-markov-chain-definition"])

    def test_backtick_content_extraction(self):
        """Only content inside backticks is extracted."""
        text = "## Citations\n\n`id-with-dashes` some text without backticks `not-a-citation`"
        ids = collect_citation_ids(text)
        self.assertEqual(len(ids), 2)
        self.assertIn("id-with-dashes", ids)
        self.assertIn("not-a-citation", ids)


# ── build_candidate_markdown ──────────────────────────────────────


class TestBuildCandidateMarkdown(unittest.TestCase):
    def test_basic_output(self):
        md = build_candidate_markdown(
            "What is a markov chain",
            "knowledge",
            ["cite-001"],
            ["Support line one", "Support line two"],
        )
        self.assertIn("---", md)
        self.assertIn("## Candidate Summary", md)
        self.assertIn("## Direct Support", md)

    def test_contains_id_with_slug(self):
        md = build_candidate_markdown("test query", "knowledge", [], [])
        slug = safe_slug("test query")
        self.assertIn(f"id: distilled-{slug}", md)

    def test_contains_title(self):
        md = build_candidate_markdown("test query", "knowledge", [], [])
        self.assertIn("title: Test Query", md)

    def test_contains_type(self):
        md = build_candidate_markdown("q", "method", [], [])
        self.assertIn("type: method", md)

    def test_contains_topic(self):
        md = build_candidate_markdown("q", "knowledge", [], [])
        self.assertIn("topic: promoted_distillation", md)

    def test_contains_tags(self):
        md = build_candidate_markdown("q", "knowledge", [], [])
        self.assertIn("tags:", md)
        self.assertIn("  - promoted", md)
        self.assertIn("  - distilled", md)

    def test_citation_ids_in_source_refs(self):
        md = build_candidate_markdown("q", "knowledge", ["ref-1", "ref-2"], [])
        self.assertIn("source_refs:", md)
        self.assertIn("  - ref-1", md)
        self.assertIn("  - ref-2", md)

    def test_empty_citations(self):
        md = build_candidate_markdown("q", "knowledge", [], [])
        self.assertIn("source_refs:", md)
        # After source_refs there should be no list items before confidence
        source_refs_section = md.split("source_refs:")[1].split("confidence:")[0]
        self.assertNotIn("  -", source_refs_section)

    def test_confidence(self):
        md = build_candidate_markdown("q", "knowledge", [], [])
        self.assertIn("confidence: draft", md)

    def test_origin(self):
        md = build_candidate_markdown("q", "knowledge", [], [])
        self.assertIn("origin: promoted_from_distilled_note", md)

    def test_candidate_summary_mentions_query(self):
        md = build_candidate_markdown("what is markov chain", "knowledge", [], [])
        self.assertIn("what is markov chain", md)
        self.assertIn("Promoted candidate derived from the distilled note", md)

    def test_direct_support_lines(self):
        md = build_candidate_markdown("q", "knowledge", [], ["Support A", "Support B"])
        self.assertIn("Support A", md)
        self.assertIn("Support B", md)

    def test_empty_direct_support(self):
        md = build_candidate_markdown("q", "knowledge", [], [])
        self.assertIn("## Direct Support", md)

    def test_frontmatter_closed(self):
        md = build_candidate_markdown("q", "knowledge", [], [])
        # Count the --- delimiters
        parts = md.split("---\n")
        self.assertGreaterEqual(len(parts), 3)

    def test_method_type(self):
        md = build_candidate_markdown("how to train", "method", [], [])
        self.assertIn("type: method", md)

    def test_unicode_query(self):
        md = build_candidate_markdown("马尔可夫链", "knowledge", [], [])
        self.assertIn("马尔可夫链", md)

    def test_output_ends_with_newline(self):
        md = build_candidate_markdown("q", "knowledge", [], [])
        self.assertTrue(md.endswith("\n"))

    def test_multiple_citations_and_support(self):
        md = build_candidate_markdown(
            "test",
            "knowledge",
            ["c1", "c2", "c3"],
            ["s1", "s2"],
        )
        for c in ["c1", "c2", "c3"]:
            self.assertIn(f"  - {c}", md)
        for s in ["s1", "s2"]:
            self.assertIn(s, md)


class TestParseArgs(unittest.TestCase):
    """Tests for parse_args."""

    def test_required_args(self) -> None:
        from pathlib import Path

        from scholar_agent.engine.promote_draft import parse_args

        with unittest.mock.patch("sys.argv", ["promote_draft", "--draft", "/tmp/draft.md"]):
            args = parse_args()
        self.assertEqual(Path(args.draft), Path("/tmp/draft.md"))
        self.assertEqual(Path(args.knowledge_root), Path("knowledge"))

    def test_custom_knowledge_root(self) -> None:
        from pathlib import Path

        from scholar_agent.engine.promote_draft import parse_args

        with unittest.mock.patch("sys.argv", ["promote_draft", "--draft", "/tmp/d.md", "--knowledge-root", "/data/kb"]):
            args = parse_args()
        self.assertEqual(Path(args.knowledge_root), Path("/data/kb"))


class TestInferDomainFolder(unittest.TestCase):
    """Tests for infer_domain_folder."""

    def test_basic_call(self) -> None:
        import tempfile
        from pathlib import Path

        from scholar_agent.engine.promote_draft import infer_domain_folder

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slug = infer_domain_folder("what is markov chain", root)
            self.assertIsInstance(slug, str)
            self.assertTrue(len(slug) > 0)


class TestMain(unittest.TestCase):
    """Tests for the main() entry point."""

    def test_main_creates_candidate(self) -> None:
        import tempfile
        from pathlib import Path

        from scholar_agent.engine.promote_draft import main

        draft_content = (
            "## Query\n\nWhat is markov chain\n\n"
            "## Route\n\nmixed\n\n"
            "## Direct Support\n\n- Evidence A\n\n"
            "## Citations\n\n`cite-001` (local / def): Title | /path\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "draft.md"
            draft.write_text(draft_content, encoding="utf-8")
            kb = root / "kb"

            with unittest.mock.patch("sys.argv", ["promote_draft", "--draft", str(draft), "--knowledge-root", str(kb)]):
                ret = main()
            self.assertEqual(ret, 0)
            # Should have created a candidate file
            candidates = list(kb.rglob("candidate-*.md"))
            self.assertGreater(len(candidates), 0)


if __name__ == "__main__":
    unittest.main()
