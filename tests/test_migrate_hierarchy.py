"""Unit tests for migrate_hierarchy pure logic."""

import tempfile
import unittest
from pathlib import Path

from scholar_agent.engine.migrate_hierarchy import (
    OR_CHILDREN,
    TOP_LEVEL,
    migrate,
    update_topic_frontmatter,
)


class TestUpdateTopicFrontmatter(unittest.TestCase):
    def test_updates_topic(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("---\nid: test\ntopic: old-topic\n---\nContent\n")
            f.flush()
            p = Path(f.name)
        update_topic_frontmatter(p, "new-topic", dry_run=False)
        text = p.read_text(encoding="utf-8")
        self.assertIn("topic: new-topic", text)
        self.assertNotIn("topic: old-topic", text)
        p.unlink()

    def test_dry_run_does_not_modify(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("---\nid: test\ntopic: old\n---\nContent\n")
            f.flush()
            p = Path(f.name)
        original = p.read_text(encoding="utf-8")
        update_topic_frontmatter(p, "new", dry_run=True)
        self.assertEqual(p.read_text(encoding="utf-8"), original)
        p.unlink()

    def test_no_frontmatter_skipped(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("Just content, no frontmatter.\n")
            f.flush()
            p = Path(f.name)
        original = p.read_text(encoding="utf-8")
        update_topic_frontmatter(p, "new", dry_run=False)
        self.assertEqual(p.read_text(encoding="utf-8"), original)
        p.unlink()

    def test_topic_already_correct(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("---\ntopic: same\n---\nContent\n")
            f.flush()
            p = Path(f.name)
        original = p.read_text(encoding="utf-8")
        update_topic_frontmatter(p, "same", dry_run=False)
        self.assertEqual(p.read_text(encoding="utf-8"), original)
        p.unlink()


class TestMigrate(unittest.TestCase):
    def test_migrate_creates_or_dir_and_moves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "linear-programming"
            child.mkdir()
            card = child / "test.md"
            card.write_text("---\ntopic: linear-programming\n---\nContent\n", encoding="utf-8")

            migrate(root, dry_run=False)

            or_dir = root / "operations-research"
            self.assertTrue(or_dir.exists())
            self.assertFalse(child.exists())
            moved = or_dir / "linear-programming" / "test.md"
            self.assertTrue(moved.exists())
            text = moved.read_text(encoding="utf-8")
            self.assertIn("operations-research/linear-programming", text)

    def test_migrate_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "scheduling"
            child.mkdir()
            card = child / "test.md"
            card.write_text("---\ntopic: scheduling\n---\nContent\n", encoding="utf-8")

            migrate(root, dry_run=True)

            self.assertTrue(child.exists())
            self.assertFalse((root / "operations-research").exists())
            text = card.read_text(encoding="utf-8")
            self.assertIn("topic: scheduling", text)

    def test_migrate_skips_missing_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            migrate(root, dry_run=False)
            # operations-research dir is always created (mkdir exist_ok)
            self.assertTrue((root / "operations-research").exists())
            # but it should be empty since no children existed
            self.assertEqual(list((root / "operations-research").iterdir()), [])

    def test_migrate_top_level_updates_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "general"
            folder.mkdir()
            card = folder / "test.md"
            card.write_text("---\ntopic: general\n---\nContent\n", encoding="utf-8")

            migrate(root, dry_run=False)
            text = card.read_text(encoding="utf-8")
            self.assertIn("topic: general", text)

    def test_constants_not_empty(self) -> None:
        self.assertGreater(len(OR_CHILDREN), 0)
        self.assertGreater(len(TOP_LEVEL), 0)


if __name__ == "__main__":
    unittest.main()
