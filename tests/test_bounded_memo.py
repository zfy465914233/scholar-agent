"""Tests for engine.common.BoundedMemo — the unified bounded cache.

Guards the two invariants that were implicit in the four duplicated caches:
 - identity mode holds a strong reference and rejects id() reuse (GC defense);
 - TTL/value semantics behave as documented.
"""

from __future__ import annotations

import threading
import unittest
from unittest import mock

from scholar_agent.engine.common import MISS, BoundedMemo


class TestValueMode(unittest.TestCase):
    def test_miss_then_hit(self) -> None:
        cache = BoundedMemo(bound=4)
        self.assertIs(cache.get("k"), MISS)
        cache.set("k", 42)
        self.assertEqual(cache.get("k"), 42)

    def test_fifo_eviction_at_bound(self) -> None:
        cache = BoundedMemo(bound=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # evicts oldest ("a")
        self.assertIs(cache.get("a"), MISS)
        self.assertEqual(cache.get("b"), 2)
        self.assertEqual(cache.get("c"), 3)

    def test_cached_none_is_distinct_from_miss(self) -> None:
        cache = BoundedMemo(bound=4)
        cache.set("k", None)
        self.assertIsNone(cache.get("k"))
        self.assertIsNot(cache.get("k"), MISS)

    def test_path_mtime_key_invalidates_on_mtime_change(self) -> None:
        cache = BoundedMemo(bound=4)
        cache.set(("idx.json", 1.0), "v1")
        self.assertEqual(cache.get(("idx.json", 1.0)), "v1")
        self.assertIs(cache.get(("idx.json", 2.0)), MISS)


class TestIdentityMode(unittest.TestCase):
    def test_hit(self) -> None:
        cache = BoundedMemo(bound=4, identity=True)
        obj = {"x": 1}
        cache.set(obj, "wrapped")
        self.assertEqual(cache.get(obj), "wrapped")

    def test_different_object_is_a_miss(self) -> None:
        # The entry holds a strong reference to the original object, so its
        # id() cannot be recycled; a distinct object (even equal-by-value) is
        # not a hit.
        cache = BoundedMemo(bound=4, identity=True)
        obj = [1, 2, 3]
        cache.set(obj, "v")
        self.assertIs(cache.get([1, 2, 3]), MISS)

    def test_fifo_eviction(self) -> None:
        cache = BoundedMemo(bound=2, identity=True)
        cache.set({"a": 1}, 1)
        cache.set({"b": 2}, 2)
        cache.set({"c": 3}, 3)
        self.assertEqual(len(cache), 2)


class TestTTL(unittest.TestCase):
    def test_entry_expires_past_ttl(self) -> None:
        cache = BoundedMemo(bound=4, ttl_seconds=10.0)
        with mock.patch("scholar_agent.engine.common.time.monotonic") as mono:
            mono.return_value = 0.0
            cache.set("k", 1)
            mono.return_value = 5.0
            self.assertEqual(cache.get("k"), 1)  # within TTL
            mono.return_value = 11.0
            self.assertIs(cache.get("k"), MISS)  # expired

    def test_set_refreshes_the_ttl(self) -> None:
        cache = BoundedMemo(bound=4, ttl_seconds=10.0)
        with mock.patch("scholar_agent.engine.common.time.monotonic") as mono:
            mono.return_value = 0.0
            cache.set("k", 1)
            mono.return_value = 9.0
            cache.set("k", 2)  # refresh at t=9
            mono.return_value = 15.0  # 6s after refresh — still within TTL
            self.assertEqual(cache.get("k"), 2)


class TestClear(unittest.TestCase):
    def test_clear_empties_all_entries(self) -> None:
        cache = BoundedMemo(bound=4)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        self.assertIs(cache.get("a"), MISS)
        self.assertEqual(len(cache), 0)


class TestThreadSafety(unittest.TestCase):
    def test_concurrent_access_does_not_corrupt(self) -> None:
        cache = BoundedMemo(bound=8)
        errors: list[BaseException] = []

        def worker(n: int) -> None:
            try:
                for i in range(200):
                    cache.set(f"k{(n + i) % 8}", i)
                    cache.get(f"k{i % 8}")
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
