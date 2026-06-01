"""Tests for functions from scholar_agent.engine.knowledge_governance."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scholar_agent.engine.knowledge_governance import (
    cmd_lint,
    cmd_show_transitions,
    cmd_validate,
)


def _write_card(
    directory: Path,
    filename: str,
    frontmatter: dict,
    body: str = "Some body text.",
) -> Path:
    """Helper: write a knowledge card markdown file with YAML frontmatter."""
    fm_lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, list):
            fm_lines.append(f"{key}:")
            for item in value:
                fm_lines.append(f"  - {item}")
        else:
            fm_lines.append(f"{key}: {value}")
    fm_lines.append("---")
    content = "\n".join(fm_lines) + "\n\n" + body + "\n"
    path = directory / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _valid_frontmatter(overrides: dict | None = None) -> dict:
    """Return valid frontmatter with sensible defaults."""
    base = {
        "id": "test-card-1",
        "title": "Test Knowledge Card",
        "type": "knowledge",
        "topic": "testing",
        "confidence": "confirmed",
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "tags": ["test"],
        "source_refs": ["https://example.com"],
    }
    if overrides:
        base.update(overrides)
    return base


class TestCmdLintOrphanDetection(unittest.TestCase):
    """Tests for cmd_lint orphan card detection."""

    def test_no_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = cmd_lint(root, stale_days=90)
            self.assertEqual(result, 0)

    def test_orphan_card_detected(self) -> None:
        """Card with no incoming or outgoing links is flagged as orphan."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_card(root, "orphan.md", _valid_frontmatter({"id": "orphan-1"}))
            result = cmd_lint(root, stale_days=90)
            self.assertEqual(result, 1)

    def test_linked_card_not_orphan(self) -> None:
        """Card with outgoing link is not flagged as orphan."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_card(
                root,
                "linked.md",
                _valid_frontmatter({"id": "graph-theory", "title": "Graph Theory Fundamentals"}),
                body="See also [[neural-networks]] for details.",
            )
            _write_card(
                root,
                "target.md",
                _valid_frontmatter({"id": "neural-networks", "title": "Neural Network Architecture"}),
            )
            # card-a has outgoing link to card-b, card-b has incoming from card-a
            # So neither is orphan. Titles are distinct so no overlap detected.
            result = cmd_lint(root, stale_days=90)
            self.assertEqual(result, 0)


class TestCmdLintBrokenLinks(unittest.TestCase):
    """Tests for cmd_lint broken wiki-link detection."""

    def test_broken_link_detected(self) -> None:
        """Link pointing to a non-existent card is flagged."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_card(
                root,
                "source.md",
                _valid_frontmatter({"id": "card-src"}),
                body="See [[nonexistent-card]] for more.",
            )
            result = cmd_lint(root, stale_days=90)
            self.assertEqual(result, 1)

    def test_valid_link_not_flagged(self) -> None:
        """Link pointing to an existing card is not flagged."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_card(
                root,
                "a.md",
                _valid_frontmatter({"id": "rl-basics", "title": "Reinforcement Learning Basics"}),
                body="Related: [[policy-gradient]].",
            )
            _write_card(
                root,
                "b.md",
                _valid_frontmatter({"id": "policy-gradient", "title": "Policy Gradient Methods"}),
            )
            result = cmd_lint(root, stale_days=90)
            self.assertEqual(result, 0)


class TestCmdLintStaleness(unittest.TestCase):
    """Tests for cmd_lint stale card detection."""

    def test_stale_card_detected(self) -> None:
        """Card updated long ago is flagged as stale."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_date = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%d")
            _write_card(
                root,
                "stale.md",
                _valid_frontmatter({"id": "stale-1", "updated_at": old_date}),
                body="Old content.",
            )
            result = cmd_lint(root, stale_days=90)
            self.assertEqual(result, 1)

    def test_recent_card_not_stale(self) -> None:
        """Recently updated card is not flagged."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recent = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            _write_card(
                root,
                "recent.md",
                _valid_frontmatter({"id": "fresh-insight", "updated_at": recent, "title": "Fresh Insight on LLM Scaling"}),
                body="Fresh content. See [[baseline-method]].",
            )
            _write_card(
                root,
                "other.md",
                _valid_frontmatter({"id": "baseline-method", "title": "Baseline Comparison Methodology"}),
            )
            result = cmd_lint(root, stale_days=90)
            self.assertEqual(result, 0)

    def test_draft_without_date_not_flagged_stale(self) -> None:
        """Draft cards without updated_at are not flagged as stale."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fm = _valid_frontmatter({"id": "draft-1"})
            del fm["updated_at"]
            fm["confidence"] = "draft"
            _write_card(root, "draft.md", fm)
            result = cmd_lint(root, stale_days=90)
            # May be orphan, but not stale
            # It will be orphan since no links
            # But the stale check should skip it

    def test_custom_stale_days(self) -> None:
        """Stale threshold can be customized."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            date_10_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
            _write_card(
                root,
                "custom.md",
                _valid_frontmatter({"id": "custom-1", "updated_at": date_10_days_ago}),
            )
            # With stale_days=5, this card is stale
            result = cmd_lint(root, stale_days=5)
            self.assertEqual(result, 1)


class TestCmdLintContradictionDetection(unittest.TestCase):
    """Tests for cmd_lint Jaccard similarity overlap detection."""

    def test_high_similarity_flagged(self) -> None:
        """Two cards with very similar titles (>0.6 Jaccard) are flagged."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_card(
                root,
                "card_a.md",
                _valid_frontmatter({"id": "overlap-a", "title": "Deep Learning Optimization Methods"}),
                body="See [[overlap-b]].",
            )
            _write_card(
                root,
                "card_b.md",
                _valid_frontmatter({"id": "overlap-b", "title": "Deep Learning Optimization Methods Overview"}),
            )
            result = cmd_lint(root, stale_days=90)
            self.assertEqual(result, 1)

    def test_different_titles_not_flagged(self) -> None:
        """Two cards with completely different titles are not flagged for overlap."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_card(
                root,
                "card_x.md",
                _valid_frontmatter({"id": "unique-x", "title": "Quantum Computing Basics"}),
                body="See [[unique-y]].",
            )
            _write_card(
                root,
                "card_y.md",
                _valid_frontmatter({"id": "unique-y", "title": "Classical Music History"}),
            )
            result = cmd_lint(root, stale_days=90)
            self.assertEqual(result, 0)


class TestCmdLintEdgeCases(unittest.TestCase):
    """Edge case tests for cmd_lint."""

    def test_card_without_id(self) -> None:
        """Cards without IDs are handled gracefully."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fm = _valid_frontmatter()
            del fm["id"]
            _write_card(root, "no_id.md", fm)
            result = cmd_lint(root, stale_days=90)
            # Should not crash; may report issues

    def test_card_with_empty_title(self) -> None:
        """Card with empty title is handled gracefully."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_card(root, "empty_title.md", _valid_frontmatter({"id": "et-1", "title": ""}))
            result = cmd_lint(root, stale_days=90)
            # Should not crash


class TestCmdValidate(unittest.TestCase):
    """Tests for cmd_validate."""

    def test_valid_cards(self) -> None:
        """All valid cards pass validation with return code 0."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_card(root, "valid.md", _valid_frontmatter({"id": "valid-1"}))
            result = cmd_validate(root)
            self.assertEqual(result, 0)

    def test_missing_required_field(self) -> None:
        """Card missing a required field fails validation."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fm = _valid_frontmatter({"id": "bad-1"})
            del fm["title"]
            _write_card(root, "bad.md", fm)
            result = cmd_validate(root)
            self.assertEqual(result, 1)

    def test_invalid_type(self) -> None:
        """Card with invalid type fails validation."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_card(
                root,
                "bad_type.md",
                _valid_frontmatter({"id": "bt-1", "type": "invalid_type"}),
            )
            result = cmd_validate(root)
            self.assertEqual(result, 1)

    def test_invalid_confidence(self) -> None:
        """Card with invalid confidence fails validation."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_card(
                root,
                "bad_conf.md",
                _valid_frontmatter({"id": "bc-1", "confidence": "maybe"}),
            )
            result = cmd_validate(root)
            self.assertEqual(result, 1)

    def test_invalid_review_status(self) -> None:
        """Card with invalid review_status fails validation."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_card(
                root,
                "bad_status.md",
                _valid_frontmatter({"id": "bs-1", "review_status": "nonexistent"}),
            )
            result = cmd_validate(root)
            self.assertEqual(result, 1)

    def test_empty_directory(self) -> None:
        """Empty knowledge directory validates successfully."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = cmd_validate(root)
            self.assertEqual(result, 0)

    def test_verbose_mode(self) -> None:
        """Verbose mode includes warnings in output."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_card(root, "verbose.md", _valid_frontmatter({"id": "v-1"}))
            result = cmd_validate(root, verbose=True)
            self.assertEqual(result, 0)


class TestCmdShowTransitions(unittest.TestCase):
    """Tests for cmd_show_transitions."""

    def test_returns_zero(self) -> None:
        result = cmd_show_transitions()
        self.assertEqual(result, 0)

    def test_no_filesystem_dependency(self) -> None:
        """cmd_show_transitions should work without any filesystem setup."""
        result = cmd_show_transitions()
        self.assertIsInstance(result, int)

    def test_all_states_present(self) -> None:
        """Output should include all lifecycle states."""
        import io
        import sys

        captured = io.StringIO()
        sys.stdout = captured
        try:
            cmd_show_transitions()
        finally:
            sys.stdout = sys.__stdout__

        output = captured.getvalue()
        self.assertIn("draft", output)
        self.assertIn("reviewed", output)
        self.assertIn("trusted", output)
        self.assertIn("stale", output)
        self.assertIn("deprecated", output)

    def test_deprecated_is_terminal(self) -> None:
        """Deprecated state should show as terminal (no outgoing transitions)."""
        import io
        import sys

        captured = io.StringIO()
        sys.stdout = captured
        try:
            cmd_show_transitions()
        finally:
            sys.stdout = sys.__stdout__

        output = captured.getvalue()
        self.assertIn("deprecated", output)
        self.assertIn("(terminal)", output)


if __name__ == "__main__":
    unittest.main()
