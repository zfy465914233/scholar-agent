"""Tests for incremental indexing and cache improvements."""

import json
import time
import unittest
from pathlib import Path

import tempfile
import shutil

_ROOT = Path(__file__).resolve().parents[1]

ENGINE = _ROOT / "scholar_agent" / "engine"


from scholar_agent.engine.local_index import (
    build_index,
    build_index_incremental,
    _load_manifest,
    _save_manifest,
    _build_manifest,
)
from scholar_agent.engine.cache_helper import get, put, invalidate, clear_all, cache_stats, MAX_ENTRIES


class IncrementalIndexTest(unittest.TestCase):
    """Test incremental index building."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.index_path = self.tmpdir / "index.json"
        # Create a knowledge card
        card = self.tmpdir / "test-card.md"
        card.write_text(
            "---\n"
            "id: test-1\n"
            "title: Test Card\n"
            "type: definition\n"
            "topic: test\n"
            "tags: [test]\n"
            "---\n\n"
            "Test body content.\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_build_creates_index(self) -> None:
        payload = build_index(self.tmpdir)
        self.assertEqual(1, len(payload["documents"]))
        self.assertEqual("test-1", payload["documents"][0]["doc_id"])

    def test_incremental_reuses_unchanged(self) -> None:
        # First build
        payload = build_index(self.tmpdir)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = _build_manifest(payload, self.tmpdir)
        _save_manifest(manifest, self.index_path)

        # Incremental rebuild — should reuse existing
        payload2 = build_index_incremental(self.tmpdir, self.index_path)
        self.assertEqual(1, len(payload2["documents"]))
        self.assertEqual("test-1", payload2["documents"][0]["doc_id"])

    def test_incremental_detects_new_card(self) -> None:
        # First build
        payload = build_index(self.tmpdir)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = _build_manifest(payload, self.tmpdir)
        _save_manifest(manifest, self.index_path)

        # Add a new card
        card2 = self.tmpdir / "test-card-2.md"
        card2.write_text(
            "---\n"
            "id: test-2\n"
            "title: Test Card 2\n"
            "type: definition\n"
            "topic: test\n"
            "---\n\nAnother card.\n",
            encoding="utf-8",
        )
        # Touch with different mtime
        time.sleep(0.05)

        payload2 = build_index_incremental(self.tmpdir, self.index_path)
        self.assertEqual(2, len(payload2["documents"]))
        doc_ids = {d["doc_id"] for d in payload2["documents"]}
        self.assertIn("test-1", doc_ids)
        self.assertIn("test-2", doc_ids)

    def test_incremental_falls_back_on_missing_manifest(self) -> None:
        # No manifest → full rebuild
        payload = build_index_incremental(self.tmpdir, self.index_path)
        self.assertEqual(1, len(payload["documents"]))

    def test_incremental_falls_back_on_corrupt_index(self) -> None:
        # Write corrupt index
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text("NOT JSON", encoding="utf-8")
        _save_manifest({"x": 1.0}, self.index_path)

        payload = build_index_incremental(self.tmpdir, self.index_path)
        self.assertEqual(1, len(payload["documents"]))

    def test_incremental_detects_modified_card(self) -> None:
        # First build
        payload = build_index(self.tmpdir)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = _build_manifest(payload, self.tmpdir)
        _save_manifest(manifest, self.index_path)

        # Modify the card
        card = self.tmpdir / "test-card.md"
        time.sleep(0.05)
        card.write_text(
            "---\n"
            "id: test-1\n"
            "title: Modified Title\n"
            "type: definition\n"
            "topic: test\n"
            "tags: [test, modified]\n"
            "---\n\nUpdated body.\n",
            encoding="utf-8",
        )

        payload2 = build_index_incremental(self.tmpdir, self.index_path)
        self.assertEqual(1, len(payload2["documents"]))
        self.assertEqual("Modified Title", payload2["documents"][0]["title"])
        self.assertIn("Updated body.", payload2["documents"][0]["search_text"])

    def test_incremental_removes_deleted_card(self) -> None:
        # Create two cards
        card2 = self.tmpdir / "test-card-2.md"
        card2.write_text(
            "---\n"
            "id: test-2\n"
            "title: Card Two\n"
            "type: definition\n"
            "topic: test\n"
            "---\n\nSecond card.\n",
            encoding="utf-8",
        )

        # First build
        payload = build_index(self.tmpdir)
        self.assertEqual(2, len(payload["documents"]))
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(payload), encoding="utf-8")
        manifest = _build_manifest(payload, self.tmpdir)
        _save_manifest(manifest, self.index_path)

        # Delete one card
        card2.unlink()

        payload2 = build_index_incremental(self.tmpdir, self.index_path)
        doc_ids = [d["doc_id"] for d in payload2["documents"]]
        self.assertEqual(1, len(doc_ids))
        self.assertIn("test-1", doc_ids)
        self.assertNotIn("test-2", doc_ids)


class CacheHelperTest(unittest.TestCase):
    """Test cache improvements."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        # Monkey-patch CACHE_DIR for isolation
        import cache_helper
        self._original_cache_dir = cache_helper.CACHE_DIR
        cache_helper.CACHE_DIR = self.tmpdir

    def tearDown(self) -> None:
        import cache_helper
        cache_helper.CACHE_DIR = self._original_cache_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_put_and_get(self) -> None:
        put("https://example.com/page1", "# Page 1\nContent.")
        result = get("https://example.com/page1")
        self.assertEqual("# Page 1\nContent.", result)

    def test_get_returns_none_for_missing(self) -> None:
        self.assertIsNone(get("https://example.com/missing"))

    def test_invalidate(self) -> None:
        put("https://example.com/page2", "Content")
        invalidate("https://example.com/page2")
        self.assertIsNone(get("https://example.com/page2"))

    def test_cache_stats(self) -> None:
        put("https://example.com/a", "A")
        put("https://example.com/b", "BB")
        stats = cache_stats()
        self.assertEqual(2, stats["entries"])
        self.assertGreater(stats["bytes"], 0)

    def test_eviction_on_excess(self) -> None:
        import cache_helper
        old_max = cache_helper.MAX_ENTRIES
        cache_helper.MAX_ENTRIES = 3
        try:
            for i in range(10):
                put(f"https://example.com/evict-{i}", f"content {i}")
            # After eviction, should have <= MAX_ENTRIES
            meta_files = list(self.tmpdir.glob("*.meta.json"))
            self.assertLessEqual(len(meta_files), cache_helper.MAX_ENTRIES + 2)
        finally:
            cache_helper.MAX_ENTRIES = old_max


if __name__ == "__main__":
    unittest.main()
