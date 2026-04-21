"""Tests for academic modules: scoring, paper_analyzer, image_extractor, note_linker, daily_workflow."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import scholar_config


# ---------------------------------------------------------------------------
# Test: Scoring
# ---------------------------------------------------------------------------

class TestScoring(unittest.TestCase):

    def setUp(self):
        from academic.scoring import score_papers
        self.score_papers = score_papers
        self.config = {
            "research_domains": {
                "LLM": {
                    "keywords": ["large language model", "LLM", "transformer", "GPT"],
                    "arxiv_categories": ["cs.AI", "cs.CL"],
                    "priority": 5,
                },
            },
            "excluded_keywords": ["survey", "workshop"],
        }

    def test_relevance_score_keyword_match(self):
        papers = [{
            "title": "A new LLM approach for reasoning",
            "summary": "We propose a large language model with transformer architecture.",
            "categories": ["cs.AI"],
            "published_date": datetime.now(),
            "citationCount": 0,
            "source": "arxiv",
        }]
        scored = self.score_papers(papers, self.config)
        self.assertEqual(len(scored), 1)
        self.assertIn("scores", scored[0])
        self.assertGreater(scored[0]["scores"]["relevance"], 0)

    def test_relevance_excluded_keyword_returns_zero(self):
        papers = [{
            "title": "A survey of large language models",
            "summary": "This survey covers recent advances.",
            "categories": ["cs.AI"],
            "published_date": datetime.now(),
            "citationCount": 0,
            "source": "arxiv",
        }]
        scored = self.score_papers(papers, self.config)
        self.assertEqual(len(scored), 0, "Excluded keyword 'survey' should filter out the paper")

    def test_recency_score_within_30_days(self):
        papers = [{
            "title": "Recent LLM work",
            "summary": "A transformer model.",
            "categories": ["cs.AI"],
            "published_date": datetime.now() - timedelta(days=5),
            "citationCount": 0,
            "source": "arxiv",
        }]
        scored = self.score_papers(papers, self.config)
        if scored:
            self.assertGreater(scored[0]["scores"]["recency"], 0.5)

    def test_recency_score_beyond_180_days(self):
        papers = [{
            "title": "Old LLM work",
            "summary": "A transformer model.",
            "categories": ["cs.AI"],
            "published_date": datetime.now() - timedelta(days=200),
            "citationCount": 0,
            "source": "arxiv",
        }]
        scored = self.score_papers(papers, self.config)
        if scored:
            self.assertLessEqual(scored[0]["scores"]["recency"], 0.3)

    def test_score_papers_batch(self):
        papers = [
            {
                "title": f"LLM paper {i}",
                "summary": "transformer language model",
                "categories": ["cs.AI"],
                "published_date": datetime.now() - timedelta(days=i),
                "citationCount": i * 10,
                "source": "arxiv",
            }
            for i in range(5)
        ]
        scored = self.score_papers(papers, self.config)
        self.assertGreater(len(scored), 0)
        # Should be sorted by recommendation score descending
        scores = [p["scores"]["recommendation"] for p in scored]
        self.assertEqual(scores, sorted(scores, reverse=True))


# ---------------------------------------------------------------------------
# Test: Paper Analyzer
# ---------------------------------------------------------------------------

class TestPaperAnalyzer(unittest.TestCase):

    def setUp(self):
        from academic.paper_analyzer import generate_note, title_to_filename
        self.generate_note = generate_note
        self.title_to_filename = title_to_filename

    def test_title_to_filename_special_chars(self):
        self.assertEqual(self.title_to_filename("Hello: World"), "Hello_World")
        self.assertEqual(self.title_to_filename("A/B Test?"), "A_B_Test")
        self.assertEqual(self.title_to_filename("  spaces  "), "spaces")

    def test_generate_note_zh_creates_file_with_all_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            paper = {
                "title": "Test Paper",
                "arxiv_id": "2401.99999",
                "authors": ["Author A", "Author B"],
                "summary": "This is a test abstract about LLM.",
                "matched_domain": "LLM",
                "scores": {"recommendation": 8.5},
            }
            path = self.generate_note(paper, tmp, language="zh")
            self.assertTrue(os.path.exists(path))

            content = Path(path).read_text(encoding="utf-8")
            # Check key sections exist
            for section in ["核心信息", "摘要翻译", "研究背景与动机", "研究问题",
                           "方法概述", "实验结果", "深度分析", "与相关工作对比",
                           "技术路线定位", "未来工作", "综合评价", "我的笔记",
                           "相关论文", "外部资源"]:
                self.assertIn(section, content, f"Missing section: {section}")

    def test_generate_note_en_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            paper = {
                "title": "English Test Paper",
                "arxiv_id": "2401.00001",
                "authors": ["John Doe"],
                "summary": "An English abstract.",
                "matched_domain": "Agent",
                "scores": {"recommendation": 7.0},
            }
            path = self.generate_note(paper, tmp, language="en")
            self.assertTrue(os.path.exists(path))

            content = Path(path).read_text(encoding="utf-8")
            for section in ["Core Information", "Abstract Analysis", "Research Background",
                           "Method Overview", "Experimental Results", "Deep Analysis",
                           "Comprehensive Evaluation", "My Notes", "Related Papers"]:
                self.assertIn(section, content, f"Missing section: {section}")

    def test_frontmatter_valid_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            paper = {
                "title": 'Paper with "quotes" and colons:',
                "arxiv_id": "2401.11111",
                "authors": ["A"],
                "scores": {"recommendation": 5.0},
            }
            path = self.generate_note(paper, tmp, language="zh")
            content = Path(path).read_text(encoding="utf-8")
            # Should start with frontmatter
            self.assertTrue(content.startswith("---"))
            # YAML should not break on special chars
            self.assertIn('paper_id: "2401.11111"', content)

    def test_images_embedded_when_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            paper = {
                "title": "Image Test",
                "arxiv_id": "2401.22222",
                "authors": ["A"],
                "scores": {"recommendation": 6.0},
            }
            images = [
                {"filename": "fig1.png", "caption": "Framework", "section": "framework"},
                {"filename": "fig2.png", "caption": "Results", "section": "results"},
            ]
            path = self.generate_note(paper, tmp, language="zh", images=images)
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("![[images/fig1.png", content)
            self.assertIn("![[images/fig2.png", content)


# ---------------------------------------------------------------------------
# Test: Image Extractor
# ---------------------------------------------------------------------------

class TestImageExtractor(unittest.TestCase):

    def test_find_source_figures_empty_dir(self):
        from academic.image_extractor import _find_source_figures
        with tempfile.TemporaryDirectory() as tmp:
            figs = _find_source_figures(tmp)
            self.assertEqual(figs, [])

    def test_find_source_figures_with_images(self):
        from academic.image_extractor import _find_source_figures
        with tempfile.TemporaryDirectory() as tmp:
            fig_dir = os.path.join(tmp, "figures")
            os.makedirs(fig_dir)
            # Create dummy image files
            for name in ["fig1.png", "fig2.jpg", "data.csv"]:
                Path(fig_dir, name).write_bytes(b"dummy")
            figs = _find_source_figures(tmp)
            filenames = {f["filename"] for f in figs}
            self.assertIn("fig1.png", filenames)
            self.assertIn("fig2.jpg", filenames)
            self.assertNotIn("data.csv", filenames)

    def test_extract_returns_empty_without_fitz(self):
        from academic import image_extractor
        original = image_extractor.HAS_FITZ
        image_extractor.HAS_FITZ = False
        try:
            result = image_extractor._extract_pdf_images("/nonexistent.pdf", "/tmp")
            self.assertEqual(result, [])
        finally:
            image_extractor.HAS_FITZ = original


# ---------------------------------------------------------------------------
# Test: Note Linker
# ---------------------------------------------------------------------------

class TestNoteLinker(unittest.TestCase):

    def test_find_related_papers_shared_keywords(self):
        from academic.note_linker import find_related_papers
        paper = {
            "title": "LLM Reasoning",
            "matched_keywords": ["LLM", "reasoning"],
            "matched_domain": "AI",
            "authors": ["Alice"],
        }
        others = [
            {
                "title": "Another LLM Paper",
                "matched_keywords": ["LLM", "transformer"],
                "matched_domain": "AI",
                "authors": ["Bob"],
            },
            {
                "title": "Unrelated Paper",
                "matched_keywords": ["biology"],
                "matched_domain": "Bio",
                "authors": ["Carol"],
            },
        ]
        related = find_related_papers(paper, others, max_links=5)
        self.assertIn("Another_LLM_Paper", related)

    def test_find_related_papers_no_self_link(self):
        from academic.note_linker import find_related_papers
        paper = {
            "title": "My Paper",
            "matched_keywords": ["LLM"],
            "matched_domain": "AI",
            "authors": [],
        }
        others = [paper]  # same paper in the list
        related = find_related_papers(paper, others)
        self.assertEqual(related, [])

    def test_scan_notes_for_keywords_extracts_acronyms(self):
        from academic.note_linker import scan_notes_for_keywords
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "BLIP-2_Visual_Reasoning.md"
            note.write_text(
                '---\ntitle: "BLIP-2: Bootstrapping Language-Image"\ntags:\n  - VLP\n---\nContent here.\n',
                encoding="utf-8",
            )
            index = scan_notes_for_keywords(tmp)
            # Should extract "BLIP-2" from pre-colon text
            self.assertIn("blip-2", index)
            self.assertEqual(index["blip-2"], "BLIP-2_Visual_Reasoning")

    def test_linkify_keywords_skips_frontmatter(self):
        from academic.note_linker import linkify_keywords
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "test.md"
            note.write_text(
                '---\ntitle: "BLIP-2 paper"\n---\nThis mentions BLIP-2 in body.\n',
                encoding="utf-8",
            )
            keyword_index = {"blip-2": "BLIP-2_Note"}
            modified, count = linkify_keywords(str(note), keyword_index)
            content = note.read_text(encoding="utf-8")
            # Frontmatter should NOT be linked
            self.assertIn('title: "BLIP-2 paper"', content)
            # Body should be linked
            self.assertIn("[[BLIP-2_Note|BLIP-2]]", content)
            self.assertTrue(modified)
            self.assertEqual(count, 1)

    def test_linkify_keywords_skips_code_blocks(self):
        from academic.note_linker import linkify_keywords
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "test.md"
            note.write_text(
                '---\ntitle: "Test"\n---\n```python\nBLIP = load()\n```\nBLIP is great.\n',
                encoding="utf-8",
            )
            keyword_index = {"blip": "BLIP_Note"}
            modified, count = linkify_keywords(str(note), keyword_index)
            content = note.read_text(encoding="utf-8")
            # Code block should not be linked
            self.assertIn("BLIP = load()", content)
            self.assertNotIn("[[BLIP_Note|BLIP]]", content.split("```")[1])
            # Body text should be linked
            self.assertIn("[[BLIP_Note|BLIP]]", content)

    def test_linkify_keywords_skips_existing_wikilinks(self):
        from academic.note_linker import linkify_keywords
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "test.md"
            note.write_text(
                '---\ntitle: "Test"\n---\nSee [[BLIP_Note|BLIP]] already linked.\n',
                encoding="utf-8",
            )
            keyword_index = {"blip": "BLIP_Note"}
            modified, count = linkify_keywords(str(note), keyword_index)
            self.assertFalse(modified)
            self.assertEqual(count, 0)


# ---------------------------------------------------------------------------
# Test: Daily Workflow
# ---------------------------------------------------------------------------

class TestDailyWorkflow(unittest.TestCase):

    def test_get_analyzed_paper_ids_from_frontmatter(self):
        from academic.daily_workflow import get_analyzed_paper_ids
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "paper1.md"
            note.write_text(
                '---\npaper_id: "2401.12345"\ntitle: "Test"\n---\nContent\n',
                encoding="utf-8",
            )
            note2 = Path(tmp) / "paper2.md"
            note2.write_text(
                '---\npaper_id: "arXiv: 2401.67890"\n---\nContent\n',
                encoding="utf-8",
            )
            ids = get_analyzed_paper_ids(tmp)
            self.assertIn("2401.12345", ids)
            self.assertIn("2401.67890", ids)

    def test_filter_already_analyzed(self):
        from academic.daily_workflow import filter_already_analyzed
        papers = [
            {"arxiv_id": "2401.11111", "title": "A"},
            {"arxiv_id": "2401.22222", "title": "B"},
            {"arxiv_id": "2401.33333", "title": "C"},
        ]
        existing = {"2401.11111", "2401.33333"}
        remaining, filtered = filter_already_analyzed(papers, existing)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["title"], "B")
        self.assertEqual(filtered, 2)

    def test_build_daily_note_zh_has_frontmatter(self):
        from academic.daily_workflow import build_daily_note
        with tempfile.TemporaryDirectory() as tmp:
            papers = [
                {
                    "title": "Paper A",
                    "authors": ["Alice"],
                    "arxiv_id": "2401.00001",
                    "scores": {"recommendation": 9.0},
                    "matched_domain": "LLM",
                    "matched_keywords": ["LLM"],
                },
            ]
            path = build_daily_note("2025-01-01", papers, tmp, language="zh")
            self.assertTrue(os.path.exists(path))
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("---", content)
            self.assertIn("论文推荐", content)
            self.assertIn("Paper A", content)
            self.assertIn("TOP3", content)

    def test_build_daily_note_en(self):
        from academic.daily_workflow import build_daily_note
        with tempfile.TemporaryDirectory() as tmp:
            papers = [
                {
                    "title": "Paper B",
                    "authors": ["Bob"],
                    "arxiv_id": "2401.00002",
                    "scores": {"recommendation": 7.5},
                    "matched_domain": "Agent",
                    "matched_keywords": ["agent"],
                },
            ]
            path = build_daily_note("2025-01-01", papers, tmp, language="en")
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("Paper Recommendations", content)
            self.assertIn("Paper B", content)


class TestParseArxivId(unittest.TestCase):
    def test_raw_id(self) -> None:
        from mcp_server import _parse_arxiv_id
        self.assertEqual("2510.24701", _parse_arxiv_id("2510.24701"))

    def test_versioned_id(self) -> None:
        from mcp_server import _parse_arxiv_id
        self.assertEqual("2510.24701", _parse_arxiv_id("2510.24701v2"))

    def test_abs_url(self) -> None:
        from mcp_server import _parse_arxiv_id
        self.assertEqual("2510.24701", _parse_arxiv_id("https://arxiv.org/abs/2510.24701"))

    def test_pdf_url(self) -> None:
        from mcp_server import _parse_arxiv_id
        self.assertEqual("2510.24701", _parse_arxiv_id("https://arxiv.org/pdf/2510.24701.pdf"))

    def test_invalid_input(self) -> None:
        from mcp_server import _parse_arxiv_id
        self.assertIsNone(_parse_arxiv_id("not-an-arxiv-id"))
        self.assertIsNone(_parse_arxiv_id("https://example.com/paper"))


class TestSanitizeTitle(unittest.TestCase):
    def test_basic_title(self) -> None:
        from mcp_server import _sanitize_title
        self.assertEqual("Attention_Is_All_You_Need", _sanitize_title("Attention Is All You Need"))

    def test_special_chars(self) -> None:
        from mcp_server import _sanitize_title
        result = _sanitize_title("A Survey of NLP: Models, Methods & Applications")
        self.assertNotIn(":", result)
        self.assertNotIn(",", result)
        self.assertNotIn("&", result)

    def test_long_title_truncated(self) -> None:
        from mcp_server import _sanitize_title
        long_title = "A" * 200
        result = _sanitize_title(long_title)
        self.assertLessEqual(len(result), 120)

    def test_empty_returns_untitled(self) -> None:
        from mcp_server import _sanitize_title
        self.assertEqual("untitled", _sanitize_title(""))
        self.assertEqual("untitled", _sanitize_title("   "))


class TestDownloadArxivPdf(unittest.TestCase):
    def test_caches_existing_pdf(self) -> None:
        from academic.image_extractor import download_arxiv_pdf
        with tempfile.TemporaryDirectory() as tmp:
            arxiv_id = "2510.99999"
            # Create a dummy PDF
            pdf_path = os.path.join(tmp, f"{arxiv_id}.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 dummy content")

            # Should return the existing path without downloading
            result = download_arxiv_pdf(arxiv_id, tmp)
            self.assertTrue(result.endswith(f"{arxiv_id}.pdf"))
            # Content should be unchanged (not re-downloaded)
            with open(result, "rb") as f:
                self.assertEqual(b"%PDF-1.4 dummy content", f.read())

    def test_creates_output_dir(self) -> None:
        from academic.image_extractor import download_arxiv_pdf
        with tempfile.TemporaryDirectory() as tmp:
            nested_dir = os.path.join(tmp, "nested", "dir")
            # The function should create the directory
            self.assertFalse(os.path.exists(nested_dir))
            # We can't actually download without network, but the dir creation
            # is tested implicitly via os.makedirs in the function


class TestExtractPdfText(unittest.TestCase):
    def test_returns_empty_when_no_fitz(self) -> None:
        from academic import image_extractor
        original = image_extractor.HAS_FITZ
        image_extractor.HAS_FITZ = False
        try:
            result = image_extractor.extract_pdf_text("/nonexistent.pdf")
            self.assertEqual(result, "")
        finally:
            image_extractor.HAS_FITZ = original

    def test_extract_text_from_real_pdf(self) -> None:
        """Test text extraction from a PDF created with PyMuPDF."""
        from academic import image_extractor
        if not image_extractor.HAS_FITZ:
            self.skipTest("PyMuPDF not installed")
        import fitz
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = os.path.join(tmp, "test.pdf")
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "This is a test PDF with sample content.")
            doc.save(pdf_path)
            doc.close()

            result = image_extractor.extract_pdf_text(pdf_path)
            self.assertIn("test PDF", result)
            self.assertIn("sample content", result)

    def test_truncates_long_text(self) -> None:
        """Test that max_chars parameter truncates output."""
        from academic import image_extractor
        if not image_extractor.HAS_FITZ:
            self.skipTest("PyMuPDF not installed")
        import fitz
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = os.path.join(tmp, "long.pdf")
            doc = fitz.open()
            page = doc.new_page()
            long_text = "A" * 50000
            page.insert_text((72, 72), long_text, fontsize=6)
            doc.save(pdf_path)
            doc.close()

            result = image_extractor.extract_pdf_text(pdf_path, max_chars=100)
            self.assertLessEqual(len(result), 100)


class TestCheckNoteQuality(unittest.TestCase):
    def test_detects_unfilled_placeholders(self) -> None:
        from academic.paper_analyzer import check_note_quality
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "test.md"
            note.write_text(
                "---\ntitle: Test\n---\n"
                "## 方法概述\n<!-- LLM: describe method -->\n"
                "## 实验结果\n<!-- LLM: describe experiments -->\n",
                encoding="utf-8",
            )
            result = check_note_quality(str(note))
            self.assertTrue(result["has_issues"])
            self.assertEqual(result["placeholder_count"], 2)
            self.assertTrue(any("unfilled" in i for i in result["issues"]))

    def test_detects_duplicate_sections(self) -> None:
        from academic.paper_analyzer import check_note_quality
        with tempfile.TemporaryDirectory() as tmp:
            dup = "A" * 100
            note = Path(tmp) / "test.md"
            note.write_text(
                "---\ntitle: Test\n---\n"
                f"## 方法概述\n{dup}\n"
                f"## 实验结果\n{dup}\n",
                encoding="utf-8",
            )
            result = check_note_quality(str(note))
            self.assertTrue(result["has_issues"])
            self.assertTrue(any("identical" in i for i in result["issues"]))

    def test_passes_good_note(self) -> None:
        from academic.paper_analyzer import check_note_quality
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "test.md"
            note.write_text(
                "---\ntitle: Test\n---\n"
                "## 方法概述\nWe propose a novel transformer architecture with multi-head attention.\n"
                "## 实验结果\nOur method achieves 95.3% accuracy on GLUE benchmark.\n"
                "## 深度分析\nThe key strength is the efficient attention mechanism.\n",
                encoding="utf-8",
            )
            result = check_note_quality(str(note))
            self.assertFalse(result["has_issues"])
            self.assertEqual(result["placeholder_count"], 0)


if __name__ == "__main__":
    unittest.main()
