"""Tests for ``_normalize_answer_markdown`` header handling (F1).

The answer body is embedded under the card's own ``##`` sections, so any
header in the answer must be demoted below H2 — otherwise it rivals the
card structure (## 回答 / ## 支撑论据) or clobbers the card H1.
"""

import unittest

from scholar_agent.engine.close_knowledge_loop import _normalize_answer_markdown


class TestNormalizeAnswerMarkdown(unittest.TestCase):
    def test_demotes_h2_to_h3(self) -> None:
        self.assertEqual(_normalize_answer_markdown("## 主线"), "### 主线")

    def test_demotes_h1_to_h3(self) -> None:
        # A bare # in the answer must not rival the card H1.
        self.assertEqual(_normalize_answer_markdown("# 五个维度"), "### 五个维度")

    def test_demotes_h4(self) -> None:
        self.assertEqual(_normalize_answer_markdown("#### deep"), "##### deep")

    def test_no_header_unchanged(self) -> None:
        self.assertEqual(_normalize_answer_markdown("plain text"), "plain text")

    def test_inline_header_gets_newline_and_demoted(self) -> None:
        out = _normalize_answer_markdown("text。## 行中标题")
        self.assertEqual(out, "text。\n\n### 行中标题")

    def test_code_block_hash_preserved(self) -> None:
        out = _normalize_answer_markdown("intro\n```python\n# comment\n```\n## after")
        self.assertIn("# comment", out)  # code comment untouched
        self.assertNotIn("\n## after", out)  # header demoted
        self.assertIn("### after", out)

    def test_multiple_headers_all_demoted(self) -> None:
        out = _normalize_answer_markdown("a\n## b\n## c")
        self.assertEqual(out, "a\n\n### b\n\n### c")


if __name__ == "__main__":
    unittest.main()
