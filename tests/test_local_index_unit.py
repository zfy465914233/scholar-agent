"""Unit tests for scholar_agent.engine.local_index helper functions."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from scholar_agent.engine.local_index import build_search_text, is_card, parse_card, split_frontmatter

if TYPE_CHECKING:
    from pathlib import Path


class TestIsCard:
    """Tests for is_card() — detects valid knowledge card files."""

    def test_valid_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "card.md"
        f.write_text("---\nid: test\n---\nBody\n", encoding="utf-8")
        assert is_card(f) is True

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.md"
        f.write_text("", encoding="utf-8")
        assert is_card(f) is False

    def test_no_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "plain.md"
        f.write_text("Just some text\n", encoding="utf-8")
        assert is_card(f) is False

    def test_crlf_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "crlf.md"
        f.write_bytes(b"---\r\nid: test\r\n---\r\nBody\r\n")
        assert is_card(f) is True

    def test_readme_excluded(self, tmp_path: Path) -> None:
        f = tmp_path / "README.md"
        f.write_text("---\nid: readme\n---\nBody\n", encoding="utf-8")
        assert is_card(f) is False

    def test_templates_dir_excluded(self, tmp_path: Path) -> None:
        tpl = tmp_path / "templates" / "card.md"
        tpl.parent.mkdir(parents=True)
        tpl.write_text("---\nid: tpl\n---\nBody\n", encoding="utf-8")
        assert is_card(tpl) is False

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        f = tmp_path / "nonexistent.md"
        assert is_card(f) is False

    def test_four_byte_header_only(self, tmp_path: Path) -> None:
        """is_card reads only 4 bytes — a file with just '---\\n' should match."""
        f = tmp_path / "minimal.md"
        f.write_bytes(b"---\n")
        assert is_card(f) is True

    def test_binary_file(self, tmp_path: Path) -> None:
        f = tmp_path / "binary.md"
        f.write_bytes(b"\x00\x01\x02\x03")
        assert is_card(f) is False


class TestSplitFrontmatter:
    def test_with_frontmatter(self) -> None:
        raw = "---\nid: test\ntitle: Test\n---\nBody content\n"
        meta, body = split_frontmatter(raw)
        assert meta["id"] == "test"
        assert meta["title"] == "Test"
        assert "Body content" in body

    def test_without_frontmatter(self) -> None:
        raw = "Just body text\n"
        meta, body = split_frontmatter(raw)
        assert meta == {}
        assert "Just body text" in body

    def test_empty_frontmatter(self) -> None:
        raw = "---\n---\nBody\n"
        meta, body = split_frontmatter(raw)
        assert meta == {}
        assert "Body" in body


class TestBuildSearchText:
    def test_combines_metadata_and_body(self) -> None:
        meta = {"title": "Markov Chain", "domain": "probability", "topic": "stochastic", "tags": ["mcmc", "sampling"]}
        body = "A Markov chain is a stochastic process."
        result = build_search_text(meta, body)
        assert "Markov Chain" in result
        assert "probability" in result
        assert "mcmc" in result
        assert "stochastic process" in result

    def test_empty_metadata(self) -> None:
        meta: dict = {}
        body = "Some body text"
        result = build_search_text(meta, body)
        assert "Some body text" in result

    def test_non_string_tags_skipped(self) -> None:
        meta = {"tags": [1, 2, "valid_tag"]}
        body = ""
        result = build_search_text(meta, body)
        assert "valid_tag" in result


class TestParseCard:
    def test_full_card(self, tmp_path: Path) -> None:
        card = tmp_path / "test-card.md"
        card.write_text(
            textwrap.dedent("""\
            ---
            id: test-001
            title: Test Card
            type: knowledge
            domain: math
            topic: probability
            tags:
              - test
            ---

            This is the body of the card.
            """),
            encoding="utf-8",
        )
        result = parse_card(card, knowledge_root=tmp_path)
        assert result["doc_id"] == "test-001"
        assert result["title"] == "Test Card"
        assert result["type"] == "knowledge"
        assert result["domain"] == "math"
        assert result["topic"] == "probability"
        assert "test" in result["tags"]
        assert "body of the card" in result["search_text"]

    def test_infer_domain_from_path(self, tmp_path: Path) -> None:
        domain_dir = tmp_path / "physics"
        domain_dir.mkdir()
        card = domain_dir / "quantum" / "card.md"
        card.parent.mkdir(parents=True)
        card.write_text("---\nid: phys-001\n---\nBody\n", encoding="utf-8")
        result = parse_card(card, knowledge_root=tmp_path)
        assert result["domain"] == "physics"

    def test_empty_body(self, tmp_path: Path) -> None:
        card = tmp_path / "empty-body.md"
        card.write_text("---\nid: empty\n---\n", encoding="utf-8")
        result = parse_card(card)
        assert result["doc_id"] == "empty"
        assert result["search_text"].strip() == ""
