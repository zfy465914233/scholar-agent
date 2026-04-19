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

import lore_config


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
            self.assertIn("![[images/fig1.png]]", content)
            self.assertIn("![[images/fig2.png]]", content)


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


if __name__ == "__main__":
    unittest.main()
