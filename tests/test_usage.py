"""Unit tests for usage-based popularity tracking."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from scholar_agent.engine import usage


class TestUsage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        os.environ["SCHOLAR_HOME"] = self._tmp
        usage.reset()

    def tearDown(self) -> None:
        os.environ.pop("SCHOLAR_HOME", None)
        shutil.rmtree(self._tmp, ignore_errors=True)
        usage.reset()

    def test_cold_start_no_boost(self) -> None:
        self.assertEqual(usage.usage_boost("brand-new"), 1.0)

    def test_record_then_boost_monotonic(self) -> None:
        usage.record_usage(["a", "a", "a", "b"])
        self.assertGreater(usage.usage_boost("a"), 1.0)
        self.assertGreater(usage.usage_boost("a"), usage.usage_boost("b"))

    def test_boost_is_capped(self) -> None:
        usage.record_usage(["a"] * 1000)
        self.assertLessEqual(usage.usage_boost("a"), 1.20 + 1e-9)

    def test_persist_survives_cache_clear(self) -> None:
        usage.record_usage(["a"] * 5)
        usage.reset()  # clear in-memory cache
        # load_usage re-reads from disk
        self.assertEqual(usage.load_usage().get("a"), 5)

    def test_record_empty_is_noop(self) -> None:
        usage.record_usage([])
        self.assertEqual(usage.get_usage_snapshot()["total_hits"], 0)

    def test_get_snapshot(self) -> None:
        usage.record_usage(["a", "b", "a"])
        snap = usage.get_usage_snapshot()
        self.assertEqual(snap["cards"], 2)
        self.assertEqual(snap["total_hits"], 3)
        self.assertEqual(snap["top"][0]["doc_id"], "a")


if __name__ == "__main__":
    unittest.main()
