"""Unit tests for scholar_agent.validation.validate_note pure functions.

Tests split_frontmatter, extract_sections, find_section, has_substantive_text,
collect_forbidden_errors, collect_unknown_metadata_errors, validate_core_sections,
count_quantitative_results, type_specific_checks, provenance_checks,
math_depth_checks, and content_density_checks using direct imports.
"""

import unittest

from scholar_agent.validation.validate_note import (
    SECTION_ALIASES,
    collect_forbidden_errors,
    collect_unknown_metadata_errors,
    content_density_checks,
    count_quantitative_results,
    extract_sections,
    find_section,
    has_substantive_text,
    math_depth_checks,
    provenance_checks,
    split_frontmatter,
    type_specific_checks,
    validate_core_sections,
)

# ── split_frontmatter ─────────────────────────────────────────────


class TestSplitFrontmatter(unittest.TestCase):
    def test_basic_frontmatter_and_body(self):
        text = "---\ntitle: My Title\ntype: knowledge\n---\n\n## Section\n\nBody text."
        metadata, body, errors = split_frontmatter(text)
        self.assertEqual(metadata["title"], "My Title")
        self.assertEqual(metadata["type"], "knowledge")
        self.assertIn("## Section", body)
        self.assertEqual(len(errors), 0)

    def test_no_frontmatter(self):
        text = "Just some body text without frontmatter."
        metadata, body, errors = split_frontmatter(text)
        self.assertEqual(metadata, {})
        self.assertEqual(body, text)
        self.assertEqual(len(errors), 0)

    def test_unterminated_frontmatter(self):
        text = "---\ntitle: My Title\ntype: knowledge\n\nNo closing marker."
        metadata, _body, errors = split_frontmatter(text)
        self.assertIn("unterminated_frontmatter", errors)
        self.assertEqual(metadata, {})

    def test_empty_frontmatter_block_treated_as_unterminated(self):
        # "---\n---\n..." has no "\n---\n" after position 4, so it's unterminated
        text = "---\n---\n\n## Body"
        _metadata, _body, errors = split_frontmatter(text)
        self.assertIn("unterminated_frontmatter", errors)

    def test_frontmatter_strips_quotes(self):
        text = "---\ntitle: \"My Title\"\nauthor: 'Author Name'\n---\nBody"
        metadata, _body, _errors = split_frontmatter(text)
        self.assertEqual(metadata["title"], "My Title")
        self.assertEqual(metadata["author"], "Author Name")

    def test_skips_comments_and_blank_lines(self):
        text = "---\n# comment line\n  \ntitle: Hello\n---\nBody"
        metadata, _body, _errors = split_frontmatter(text)
        self.assertEqual(metadata["title"], "Hello")
        self.assertEqual(len(metadata), 1)

    def test_duplicate_frontmatter_in_body_flagged(self):
        text = "---\ntitle: Hello\n---\n\n---\ntitle: Duplicate\n---\nBody"
        _metadata, _body, errors = split_frontmatter(text)
        self.assertIn("duplicated_frontmatter", errors)

    def test_non_key_value_lines_ignored(self):
        text = "---\ntitle: Hello\njust a plain line\n---\nBody"
        metadata, _body, _errors = split_frontmatter(text)
        self.assertEqual(len(metadata), 1)
        self.assertEqual(metadata["title"], "Hello")

    def test_multiple_keys(self):
        text = "---\ntitle: T\nauthor: A\ndate: 2026-01-01\nconfidence: confirmed\n---\nBody"
        metadata, _body, _errors = split_frontmatter(text)
        self.assertEqual(len(metadata), 4)

    def test_keys_with_hyphens_and_underscores(self):
        text = "---\narxiv_id: 1234.5678\nsource_pdf: /path/to/pdf\n---\nBody"
        metadata, _body, _errors = split_frontmatter(text)
        self.assertIn("arxiv_id", metadata)
        self.assertIn("source_pdf", metadata)


# ── extract_sections ───────────────────────────────────────────────


class TestExtractSections(unittest.TestCase):
    def test_single_section(self):
        body = "## Method\n\nThis is the method section."
        sections = extract_sections(body)
        self.assertIn("Method", sections)
        self.assertIn("method section", sections["Method"])

    def test_multiple_sections(self):
        body = "## Motivation\n\nMotivation text.\n\n## Method\n\nMethod text.\n\n## Results\n\nResults text."
        sections = extract_sections(body)
        self.assertEqual(len(sections), 3)
        self.assertIn("Motivation", sections)
        self.assertIn("Method", sections)
        self.assertIn("Results", sections)

    def test_nested_headings(self):
        # B1: level-3+ headings fold into their parent level-1/2 section.
        # Previously ### was a standalone section, truncating the parent's content.
        body = "## Method\n\n### Subsection\n\nSub text.\n\n## Results\n\nResults."
        sections = extract_sections(body)
        self.assertIn("Method", sections)
        self.assertIn("Results", sections)
        self.assertNotIn("Subsection", sections)  # folded into Method
        self.assertIn("Sub text", sections["Method"])  # child content lives in parent

    def test_no_headings(self):
        body = "Just plain text without any headings."
        sections = extract_sections(body)
        self.assertEqual(len(sections), 0)

    def test_empty_body(self):
        sections = extract_sections("")
        self.assertEqual(len(sections), 0)

    def test_chinese_headings(self):
        body = "## 研究动机\n\n这是研究动机。\n\n## 方法论\n\n这是方法论。"
        sections = extract_sections(body)
        self.assertIn("研究动机", sections)
        self.assertIn("方法论", sections)

    def test_h1_heading(self):
        body = "# Title\n\nBody text.\n\n## Section\n\nSection text."
        sections = extract_sections(body)
        self.assertIn("Title", sections)
        self.assertIn("Section", sections)


# ── find_section ───────────────────────────────────────────────────


class TestFindSection(unittest.TestCase):
    def test_exact_alias_match(self):
        sections = {"Method": "Method content here."}
        title, content = find_section(sections, ["method"])
        self.assertEqual(title, "Method")
        self.assertIn("Method content", content)

    def test_alias_in_title(self):
        sections = {"Research Motivation": "Motivation content."}
        title, _content = find_section(sections, ["motivation"])
        self.assertEqual(title, "Research Motivation")

    def test_chinese_alias(self):
        sections = {"研究动机": "Chinese motivation."}
        title, _content = find_section(sections, ["研究动机", "motivation"])
        self.assertIsNotNone(title)

    def test_no_match(self):
        sections = {"Results": "Results content."}
        title, content = find_section(sections, ["motivation"])
        self.assertIsNone(title)
        self.assertIsNone(content)

    def test_first_alias_wins(self):
        sections = {"Approach": "Approach content."}
        title, _content = find_section(sections, ["method", "approach"])
        self.assertEqual(title, "Approach")

    def test_empty_sections(self):
        title, _content = find_section({}, ["method"])
        self.assertIsNone(title)

    def test_case_insensitive_match(self):
        sections = {"MY METHOD": "content"}
        title, _content = find_section(sections, ["method"])
        self.assertEqual(title, "MY METHOD")

    def test_prefers_main_section_over_lookalike(self):
        # B5: "方法" should match "方法概述" (starts-with) over "基线方法" (substring).
        sections = {"基线方法": "baseline", "方法概述": "main method"}
        title, _content = find_section(sections, SECTION_ALIASES["method"])
        self.assertEqual(title, "方法概述")

    def test_findings_alias_includes_zh_result(self):
        # B5: "主要结果" is now a findings alias (previously only 主要结论).
        sections = {"主要结果": "results here"}
        title, _content = find_section(sections, SECTION_ALIASES["findings"])
        self.assertEqual(title, "主要结果")


# ── has_substantive_text ──────────────────────────────────────────


class TestHasSubstantiveText(unittest.TestCase):
    def test_substantive_english_text(self):
        self.assertTrue(has_substantive_text("This is a substantive piece of text with enough content."))

    def test_substantive_chinese_text(self):
        self.assertTrue(has_substantive_text("这是一段足够长的中文文本，包含了足够多的字符来通过验证检查。"))

    def test_too_short(self):
        self.assertFalse(has_substantive_text("short"))

    def test_empty_string(self):
        self.assertFalse(has_substantive_text(""))

    def test_whitespace_only(self):
        self.assertFalse(has_substantive_text("   \n\t   "))

    def test_mostly_symbols(self):
        # Even if long enough in characters, must have enough letters
        self.assertFalse(has_substantive_text("$$$ %%% !!! @@@ *** ^^^"))

    def test_exactly_at_minimum_boundary(self):
        # 24 chars of letters should pass
        text = "a" * 24
        self.assertTrue(has_substantive_text(text))

    def test_just_below_minimum(self):
        text = "a" * 23
        self.assertFalse(has_substantive_text(text))


# ── collect_forbidden_errors ──────────────────────────────────────


class TestCollectForbiddenErrors(unittest.TestCase):
    def test_skeleton_status(self):
        text = "status: skeleton"
        errors = collect_forbidden_errors(text)
        self.assertIn("skeleton_status", errors)

    def test_placeholder_score(self):
        text = "[SCORE] / 10"
        errors = collect_forbidden_errors(text)
        self.assertIn("placeholder_score", errors)

    def test_llm_comment(self):
        text = "<!-- LLM: some placeholder -->"
        errors = collect_forbidden_errors(text)
        self.assertIn("llm_placeholder_comment", errors)

    def test_pdf_placeholder(self):
        text = "PDF 片段未直接抽取"
        errors = collect_forbidden_errors(text)
        self.assertIn("pdf_placeholder_text", errors)

    def test_clean_text_no_errors(self):
        text = "This is a perfectly valid research note."
        errors = collect_forbidden_errors(text)
        self.assertEqual(len(errors), 0)

    def test_multiple_forbidden_patterns(self):
        text = "status: skeleton\n<!-- LLM: placeholder -->"
        errors = collect_forbidden_errors(text)
        self.assertEqual(len(errors), 2)

    def test_case_insensitive(self):
        text = "STATUS: Skeleton"
        errors = collect_forbidden_errors(text)
        self.assertIn("skeleton_status", errors)


# ── collect_unknown_metadata_errors ──────────────────────────────


class TestCollectUnknownMetadataErrors(unittest.TestCase):
    def test_unknown_value(self):
        metadata = {"author": "unknown", "title": "My Paper"}
        errors = collect_unknown_metadata_errors(metadata)
        self.assertIn("metadata_unknown:author", errors)

    def test_tbd_value(self):
        metadata = {"result": "tbd"}
        errors = collect_unknown_metadata_errors(metadata)
        self.assertIn("metadata_unknown:result", errors)

    def test_na_value(self):
        metadata = {"field": "n/a"}
        errors = collect_unknown_metadata_errors(metadata)
        self.assertIn("metadata_unknown:field", errors)

    def test_none_string_value(self):
        metadata = {"field": "none"}
        errors = collect_unknown_metadata_errors(metadata)
        self.assertIn("metadata_unknown:field", errors)

    def test_null_string(self):
        metadata = {"field": "null"}
        errors = collect_unknown_metadata_errors(metadata)
        self.assertIn("metadata_unknown:field", errors)

    def test_valid_values_no_errors(self):
        metadata = {"author": "John Doe", "title": "My Paper", "date": "2026-01-01"}
        errors = collect_unknown_metadata_errors(metadata)
        self.assertEqual(len(errors), 0)

    def test_empty_metadata(self):
        errors = collect_unknown_metadata_errors({})
        self.assertEqual(len(errors), 0)

    def test_bracket_unknown(self):
        metadata = {"field": "[unknown]"}
        errors = collect_unknown_metadata_errors(metadata)
        self.assertIn("metadata_unknown:field", errors)

    def test_case_insensitive(self):
        metadata = {"field": "Unknown"}
        errors = collect_unknown_metadata_errors(metadata)
        self.assertIn("metadata_unknown:field", errors)

    def test_math_depth_none_not_unknown(self):
        # B4: math_depth=none is legitimate (paper has no math), not "unknown".
        errors = collect_unknown_metadata_errors({"math_depth": "none"})
        self.assertNotIn("metadata_unknown:math_depth", errors)

    def test_other_field_none_still_flagged(self):
        # Only math_depth is exempted; "none" elsewhere stays unknown.
        errors = collect_unknown_metadata_errors({"author": "none"})
        self.assertIn("metadata_unknown:author", errors)


# ── validate_core_sections ────────────────────────────────────────


class TestValidateCoreSections(unittest.TestCase):
    def _make_body(self, include_all=True, overrides=None):
        """Build a body with all core sections."""
        overrides = overrides or {}
        sections = {
            "motivation": "## Motivation\n\nThis section describes the research motivation in enough detail to pass validation checks.\n\nAdditional context here.",
            "method": "## Method\n\nThe method section describes the approach used. It has substantive text that is long enough to be meaningful.\n\nDetails follow.",
            "dataset": "## Dataset\n\nThe dataset section describes the data used for experiments. It provides details on data collection and processing.",
            "findings": "## Findings\n\nThe findings section presents the main results. Key findings are described with enough context and detail.\n\nImplications are discussed.",
            "limitations": "## Limitations\n\nThe limitations section acknowledges the constraints and weaknesses of this study in adequate detail.",
        }
        if not include_all:
            return ""
        parts = []
        for key in ["motivation", "method", "dataset", "findings", "limitations"]:
            if key in overrides:
                parts.append(overrides[key])
            else:
                parts.append(sections[key])
        return "\n\n".join(parts)

    def test_all_sections_present_no_errors(self):
        body = self._make_body()
        sections = extract_sections(body)
        errors, _warnings, _resolved = validate_core_sections(sections, "required", body)
        self.assertEqual(len(errors), 0)

    def test_missing_motivation(self):
        body = self._make_body(overrides={"motivation": ""})
        sections = extract_sections(body)
        errors, _warnings, _resolved = validate_core_sections(sections, "required", body)
        self.assertTrue(any("missing_section:motivation" in e for e in errors))

    def test_missing_method(self):
        body = self._make_body(overrides={"method": ""})
        sections = extract_sections(body)
        errors, _warnings, _resolved = validate_core_sections(sections, "required", body)
        self.assertTrue(any("missing_section:method" in e for e in errors))

    def test_missing_dataset_required_policy(self):
        body = self._make_body(overrides={"dataset": ""})
        sections = extract_sections(body)
        errors, _warnings, _resolved = validate_core_sections(sections, "required", body)
        self.assertTrue(any("missing_section:dataset" in e for e in errors))

    def test_thin_section_flagged(self):
        thin_method = "## Method\n\nshort"
        body = self._make_body(overrides={"method": thin_method})
        sections = extract_sections(body)
        errors, _warnings, _resolved = validate_core_sections(sections, "required", body)
        self.assertTrue(any("thin_section:method" in e for e in errors))

    def test_fallback_policy_omits_dataset_from_mandatory(self):
        body = self._make_body(overrides={"dataset": ""})
        sections = extract_sections(body)
        errors, _warnings, _resolved = validate_core_sections(sections, "fallback", body)
        # With fallback, missing dataset should not produce a hard error for the core keys
        core_missing = [e for e in errors if e.startswith("missing_section:") and "dataset" not in e]
        self.assertEqual(len(core_missing), 0)

    def test_fallback_policy_uses_alternative_section(self):
        body = (
            "## Motivation\n\nEnough motivation text to pass the validation checks for substantive content.\n\n"
            "## Method\n\nEnough method text to pass the validation checks for substantive content.\n\n"
            "## Findings\n\nEnough findings text to pass the validation checks for substantive content.\n\n"
            "## Limitations\n\nEnough limitations text to pass the validation checks for substantive content.\n\n"
            "## Problem Definition\n\nThis is a problem definition section that serves as a dataset fallback with enough text to be substantive.\n\n"
        )
        sections = extract_sections(body)
        errors, warnings, _resolved = validate_core_sections(sections, "fallback", body)
        # Should resolve dataset via fallback
        dataset_errors = [e for e in errors if "dataset" in e]
        self.assertEqual(len(dataset_errors), 0)
        self.assertIn("dataset_fallback_used", warnings)

    def test_resolved_sections_contain_actual_titles(self):
        body = self._make_body()
        sections = extract_sections(body)
        _errors, _warnings, resolved = validate_core_sections(sections, "required", body)
        self.assertIn("motivation", resolved)
        self.assertEqual(resolved["motivation"], "Motivation")


# ── count_quantitative_results ─────────────────────────────────────


class TestCountQuantitativeResults(unittest.TestCase):
    def test_percentage(self):
        text = "The model achieved 95.3% accuracy."
        self.assertGreaterEqual(count_quantitative_results(text), 1)

    def test_multiple_metrics(self):
        text = "AUC 0.92, F1 0.88, accuracy 95%"
        count = count_quantitative_results(text)
        self.assertGreaterEqual(count, 2)

    def test_no_metrics(self):
        text = "This paper discusses theoretical aspects."
        self.assertEqual(count_quantitative_results(text), 0)

    def test_times_multiplier(self):
        text = "3x faster than baseline"
        self.assertGreaterEqual(count_quantitative_results(text), 1)

    def test_points(self):
        text = "improved by 5 points"
        self.assertGreaterEqual(count_quantitative_results(text), 1)

    def test_metric_with_value_after(self):
        text = "accuracy of 0.95"
        self.assertGreaterEqual(count_quantitative_results(text), 1)

    def test_empty_text(self):
        self.assertEqual(count_quantitative_results(""), 0)

    def test_percentage_followed_by_space_or_eol(self):
        # B2: the old trailing \b dropped "% SR" (% + space) and end-of-line "%"
        # because there's no word boundary after %. (?![\d.]) now counts them.
        self.assertGreaterEqual(count_quantitative_results("achieved 40.0% SR"), 1)
        self.assertGreaterEqual(count_quantitative_results("accuracy 95%"), 1)


# ── type_specific_checks ─────────────────────────────────────────


class TestTypeSpecificChecks(unittest.TestCase):
    def test_empirical_with_enough_quantitative(self):
        sections = {"Findings": "AUC 0.92 and F1 0.88 and accuracy 95%"}
        resolved = {"findings": "Findings"}
        errors = type_specific_checks("empirical", sections, resolved)
        self.assertNotIn("empirical_requires_two_quantitative_results", errors)

    def test_empirical_without_enough_quantitative(self):
        sections = {"Findings": "Some qualitative results here with no numbers."}
        resolved = {"findings": "Findings"}
        errors = type_specific_checks("empirical", sections, resolved)
        self.assertIn("empirical_requires_two_quantitative_results", errors)

    def test_theory_with_problem_definition(self):
        sections = {"Theory": "We define the problem definition and prove our theorem."}
        resolved = {}
        errors = type_specific_checks("theory", sections, resolved)
        self.assertNotIn("theory_requires_problem_definition_or_mechanism", errors)

    def test_theory_without_markers(self):
        sections = {"Approach": "We use a novel approach based on some ideas."}
        resolved = {}
        errors = type_specific_checks("theory", sections, resolved)
        self.assertIn("theory_requires_problem_definition_or_mechanism", errors)

    def test_survey_with_taxonomy_and_consensus(self):
        sections = {"Overview": "We provide a taxonomy and identify consensus and disagreement."}
        resolved = {}
        errors = type_specific_checks("survey", sections, resolved)
        self.assertNotIn("survey_requires_taxonomy", errors)
        self.assertNotIn("survey_requires_consensus_or_disagreement", errors)

    def test_survey_without_taxonomy(self):
        sections = {"Overview": "We identify consensus in the field."}
        resolved = {}
        errors = type_specific_checks("survey", sections, resolved)
        self.assertIn("survey_requires_taxonomy", errors)

    def test_survey_without_consensus(self):
        sections = {"Overview": "We provide a taxonomy of methods."}
        resolved = {}
        errors = type_specific_checks("survey", sections, resolved)
        self.assertIn("survey_requires_consensus_or_disagreement", errors)

    def test_benchmark_with_markers(self):
        sections = {"Setup": "We compare baselines using our evaluation protocol and analyze bias."}
        resolved = {}
        errors = type_specific_checks("benchmark", sections, resolved)
        self.assertNotIn("benchmark_requires_protocol_baseline_and_risk", errors)

    def test_benchmark_without_markers(self):
        sections = {"Setup": "We run experiments."}
        resolved = {}
        errors = type_specific_checks("benchmark", sections, resolved)
        self.assertIn("benchmark_requires_protocol_baseline_and_risk", errors)

    def test_generic_type_no_errors(self):
        sections = {"Introduction": "Some intro."}
        resolved = {}
        errors = type_specific_checks("generic", sections, resolved)
        self.assertEqual(len(errors), 0)

    def test_empirical_falls_back_to_combined_text(self):
        """When findings is not resolved, combined text is used."""
        sections = {
            "Method": "We report AUC of 0.95 and F1 of 0.90 in our method.",
        }
        resolved = {}
        errors = type_specific_checks("empirical", sections, resolved)
        self.assertNotIn("empirical_requires_two_quantitative_results", errors)

    def test_theory_chinese_markers(self):
        sections = {"Theory": "我们给出了问题定义和机制分析。"}
        resolved = {}
        errors = type_specific_checks("theory", sections, resolved)
        self.assertNotIn("theory_requires_problem_definition_or_mechanism", errors)


# ── provenance_checks ─────────────────────────────────────────────


class TestProvenanceChecks(unittest.TestCase):
    def test_with_source_key(self):
        metadata = {"pdf_path": "/path/to/paper.pdf"}
        errors = provenance_checks(metadata, "No evidence markers here.")
        self.assertEqual(len(errors), 0)

    def test_with_arxiv_id(self):
        metadata = {"arxiv_id": "2401.12345"}
        errors = provenance_checks(metadata, "Body text.")
        self.assertEqual(len(errors), 0)

    def test_with_evidence_marker_figure(self):
        metadata = {}
        body = "As shown in Figure 1, the results improve."
        errors = provenance_checks(metadata, body)
        self.assertEqual(len(errors), 0)

    def test_with_evidence_marker_table(self):
        metadata = {}
        body = "See Table 3 for details."
        errors = provenance_checks(metadata, body)
        self.assertEqual(len(errors), 0)

    def test_with_evidence_marker_section(self):
        metadata = {}
        body = "Discussed in Section 2."
        errors = provenance_checks(metadata, body)
        self.assertEqual(len(errors), 0)

    def test_chinese_evidence_markers(self):
        metadata = {}
        body = "如图 2 所示，结果表明改善。"
        errors = provenance_checks(metadata, body)
        self.assertEqual(len(errors), 0)

    def test_no_evidence_at_all(self):
        metadata = {}
        body = "This is just regular text without any evidence."
        errors = provenance_checks(metadata, body)
        self.assertIn("missing_evidence_markers", errors)

    def test_doi_source_key(self):
        metadata = {"doi": "10.1234/test"}
        errors = provenance_checks(metadata, "Body text.")
        self.assertEqual(len(errors), 0)

    def test_paper_id_source_key(self):
        metadata = {"paper_id": "abc123"}
        errors = provenance_checks(metadata, "Body text.")
        self.assertEqual(len(errors), 0)


# ── math_depth_checks ─────────────────────────────────────────────


class TestMathDepthChecks(unittest.TestCase):
    def test_no_math_depth_no_errors(self):
        metadata = {}
        errors = math_depth_checks(metadata, "Body with $x = 1$.", {"Method": "content"})
        self.assertEqual(len(errors), 0)

    def test_heavy_math_with_latex(self):
        metadata = {"math_depth": "heavy"}
        body = "We define $\\alpha = 0.5$ and use $$E = mc^2$$"
        sections = {"Method": "Method content with $\\beta = 0.3$"}
        errors = math_depth_checks(metadata, body, sections)
        self.assertNotIn("heavy_math_requires_latex_formulas", errors)

    def test_heavy_math_without_latex(self):
        metadata = {"math_depth": "heavy"}
        body = "We define alpha as a parameter."
        sections = {"Method": "No LaTeX here."}
        errors = math_depth_checks(metadata, body, sections)
        self.assertIn("heavy_math_requires_latex_formulas", errors)

    def test_light_math_with_inline_latex(self):
        metadata = {"math_depth": "light"}
        body = "The value is $x = 1$."
        sections = {}
        errors = math_depth_checks(metadata, body, sections)
        self.assertEqual(len(errors), 0)

    def test_light_math_without_latex(self):
        metadata = {"math_depth": "light"}
        body = "No formulas here."
        sections = {}
        errors = math_depth_checks(metadata, body, sections)
        self.assertIn("light_math_requires_latex_formulas", errors)

    def test_heavy_math_with_symbol_table(self):
        metadata = {"math_depth": "heavy"}
        body = "| Symbol | Meaning |\n| $\\alpha$ | Learning rate |\n| $\\beta$ | Momentum |"
        sections = {"Method": "content"}
        errors = math_depth_checks(metadata, body, sections)
        symbol_errors = [e for e in errors if "symbol_definitions" in e]
        self.assertEqual(len(symbol_errors), 0)

    def test_heavy_math_without_symbol_definitions(self):
        metadata = {"math_depth": "heavy"}
        body = "We define $x = 1$ and $$y = 2$$"
        sections = {"Method": "No Greek letters or symbols here."}
        errors = math_depth_checks(metadata, body, sections)
        self.assertIn("heavy_math_requires_symbol_definitions", errors)

    def test_heavy_math_with_inline_symbols_in_method(self):
        metadata = {"math_depth": "heavy"}
        body = "We define $x = 1$ and $$y = 2$$"
        sections = {"Method": "Using $\\alpha$ as the learning rate and $\\lambda$ for regularization."}
        errors = math_depth_checks(metadata, body, sections)
        symbol_errors = [e for e in errors if "symbol_definitions" in e]
        self.assertEqual(len(symbol_errors), 0)

    def test_heavy_math_with_equation_env(self):
        metadata = {"math_depth": "heavy"}
        body = "\\begin{equation}\nx = 1\n\\end{equation}"
        sections = {"Method": "content"}
        errors = math_depth_checks(metadata, body, sections)
        self.assertNotIn("heavy_math_requires_latex_formulas", errors)

    def test_unknown_math_depth_value_ignored(self):
        metadata = {"math_depth": "moderate"}
        errors = math_depth_checks(metadata, "No LaTeX", {})
        self.assertEqual(len(errors), 0)

    def test_none_math_depth_skips_checks(self):
        # B4: math_depth=none means no math requirement; LaTeX/symbol checks skipped.
        errors = math_depth_checks({"math_depth": "none"}, "No LaTeX here at all.", {})
        self.assertEqual(len(errors), 0)


# ── content_density_checks ────────────────────────────────────────


class TestContentDensityChecks(unittest.TestCase):
    def test_method_with_prose_passes(self):
        sections = {
            "Method": "This is a well-written method section that contains substantive prose "
            "describing the approach. It goes into detail about the algorithm and "
            "its implementation, providing more than fifty characters of prose.",
        }
        errors = content_density_checks(sections, "generic")
        self.assertNotIn("method_section_lacks_prose", errors)

    def test_method_only_bullets_fails(self):
        sections = {
            "Method": "- bullet one\n- bullet two\n- bullet three",
        }
        errors = content_density_checks(sections, "generic")
        self.assertIn("method_section_lacks_prose", errors)

    def test_findings_with_table_passes(self):
        sections = {
            "Results": "| Model | Accuracy |\n| GPT-4 | 95% |\n| GPT-3 | 90% |",
        }
        errors = content_density_checks(sections, "generic")
        self.assertNotIn("findings_section_lacks_substance", errors)

    def test_findings_with_prose_passes(self):
        sections = {
            "Results": "Our experimental results show significant improvements over baseline methods. "
            "The model achieves state-of-the-art performance across all metrics evaluated.",
        }
        errors = content_density_checks(sections, "generic")
        self.assertNotIn("findings_section_lacks_substance", errors)

    def test_findings_only_list_fails(self):
        sections = {
            "Results": "- result one\n- result two\n- result three",
        }
        errors = content_density_checks(sections, "generic")
        self.assertIn("findings_section_lacks_substance", errors)

    def test_empty_sections_no_error(self):
        errors = content_density_checks({}, "generic")
        self.assertEqual(len(errors), 0)

    def test_method_with_chinese_heading(self):
        sections = {
            "方法": "This is a method section with more than fifty characters of prose that describes the methodology in detail.",
        }
        errors = content_density_checks(sections, "generic")
        self.assertNotIn("method_section_lacks_prose", errors)

    def test_findings_with_chinese_heading(self):
        sections = {
            "实验结果": "The results demonstrate improvements with more than fifty characters of detailed analysis.",
        }
        errors = content_density_checks(sections, "generic")
        self.assertNotIn("findings_section_lacks_substance", errors)

    def test_method_with_short_prose_fails(self):
        """Prose paragraphs shorter than 50 chars don't count."""
        sections = {
            "Method": "Short text here.",
        }
        errors = content_density_checks(sections, "generic")
        self.assertIn("method_section_lacks_prose", errors)

    def test_findings_heading_variants(self):
        for heading_variant in ["Findings", "Core Findings", "Key Conclusion"]:
            with self.subTest(heading=heading_variant):
                sections = {
                    heading_variant: "Substantive findings text with more than fifty characters of detailed results analysis.",
                }
                errors = content_density_checks(sections, "generic")
                self.assertNotIn("findings_section_lacks_substance", errors)

    def test_baseline_method_table_not_flagged(self):
        # B3: only the MAIN method section is checked. A table-only "基线方法"
        # subsection must NOT trigger method_section_lacks_prose.
        sections = {
            "方法": "这是主方法 section，我们用自然语言 prose 详细描述了方法的核心思想、整体架构、关键模块设计以及具体实现步骤，内容超过五十个字符阈值。",
            "基线方法": "| Model | Acc |\n| --- | --- |\n| Base | 80% |",
        }
        errors = content_density_checks(sections, "generic")
        self.assertNotIn("method_section_lacks_prose", errors)


if __name__ == "__main__":
    unittest.main()
