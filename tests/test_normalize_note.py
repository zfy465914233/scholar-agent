"""Unit tests for normalize_note pure logic."""

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from scholar_agent.validation.normalize_note import (
    build_target_filename,
    main,
    prune_empty_parents,
)


def _make_args(**overrides: object) -> argparse.Namespace:
    defaults = {
        "source": "/tmp/test.md",
        "paper_notes_root": "/tmp/notes",
        "domain": "ml",
        "paper_folder": "test-paper",
        "filename_mode": "folder",
        "filename": None,
        "promote": False,
        "overwrite": False,
        "allow_non_staging": True,
        "json_indent": 2,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestBuildTargetFilename(unittest.TestCase):
    def test_folder_mode(self) -> None:
        args = _make_args(filename_mode="folder", paper_folder="my-paper")
        self.assertEqual(build_target_filename(args), "my-paper.md")

    def test_note_mode(self) -> None:
        args = _make_args(filename_mode="note")
        self.assertEqual(build_target_filename(args), "note.md")

    def test_explicit_mode(self) -> None:
        args = _make_args(filename_mode="explicit", filename="custom.md")
        self.assertEqual(build_target_filename(args), "custom.md")

    def test_explicit_mode_missing_filename_raises(self) -> None:
        args = _make_args(filename_mode="explicit", filename=None)
        with self.assertRaises(ValueError):
            build_target_filename(args)


class TestPruneEmptyParents(unittest.TestCase):
    def test_removes_empty_parents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deep = root / "a" / "b" / "c"
            deep.mkdir(parents=True)
            marker = deep / "file.md"
            marker.write_text("x", encoding="utf-8")

            # Remove the file, then prune
            marker.unlink()
            prune_empty_parents(marker, stop_at=root)
            # a/b/c removed, a/b removed, a removed
            self.assertFalse((root / "a").exists())

    def test_stops_at_non_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deep = root / "a" / "b"
            deep.mkdir(parents=True)
            keeper = root / "a" / "keep.txt"
            keeper.write_text("x", encoding="utf-8")

            file_in_b = deep / "file.md"
            file_in_b.write_text("x", encoding="utf-8")
            file_in_b.unlink()
            prune_empty_parents(file_in_b, stop_at=root)
            # b removed, but a stays because it has keep.txt
            self.assertFalse(deep.exists())
            self.assertTrue((root / "a").exists())

    def test_noop_when_stop_at_is_direct_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "file.md"
            f.write_text("x", encoding="utf-8")
            f.unlink()
            prune_empty_parents(f, stop_at=root)
            self.assertTrue(root.exists())


class TestMainDryRun(unittest.TestCase):
    def test_dry_run_reports_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / ".staging"
            staging.mkdir()
            src = staging / "test.md"
            src.write_text("---\nid: t\n---\nContent", encoding="utf-8")

            import sys

            old_argv = sys.argv
            sys.argv = [
                "normalize_note",
                "--source",
                str(src),
                "--paper-notes-root",
                str(root),
                "--domain",
                "ml",
                "--paper-folder",
                "test-paper",
                "--filename-mode",
                "folder",
                "--allow-non-staging",
            ]
            try:
                # Capture stdout
                from io import StringIO

                captured = StringIO()
                old_stdout = sys.stdout
                sys.stdout = captured
                rc = main()
                sys.stdout = old_stdout
            finally:
                sys.argv = old_argv

            self.assertEqual(rc, 0)
            data = json.loads(captured.getvalue())
            self.assertTrue(data["ok"])
            self.assertIn("dry_run_only", data["warnings"])

    def test_source_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import sys

            old_argv = sys.argv
            sys.argv = [
                "normalize_note",
                "--source",
                str(Path(tmp) / "nonexistent.md"),
                "--paper-notes-root",
                tmp,
                "--domain",
                "ml",
                "--paper-folder",
                "test",
                "--allow-non-staging",
            ]
            try:
                from io import StringIO

                captured = StringIO()
                old_stdout = sys.stdout
                sys.stdout = captured
                rc = main()
                sys.stdout = old_stdout
            finally:
                sys.argv = old_argv

            self.assertEqual(rc, 1)
            data = json.loads(captured.getvalue())
            self.assertFalse(data["ok"])
            self.assertIn("source_not_found", data["errors"])


if __name__ == "__main__":
    unittest.main()
