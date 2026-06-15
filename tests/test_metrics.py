"""Unit tests for the in-process metrics counters."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import unittest

from scholar_agent.engine import metrics


class TestMetricsCounters(unittest.TestCase):
    def setUp(self) -> None:
        metrics.reset()

    def tearDown(self) -> None:
        metrics.reset()

    def test_initial_state(self) -> None:
        snapshot = metrics.get_metrics()
        self.assertEqual(snapshot["llm"]["calls"], 0)
        self.assertEqual(snapshot["retrieve"]["calls"], 0)

    def test_record_llm_call_accumulates_tokens(self) -> None:
        metrics.record_llm_call({"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        metrics.record_llm_call({"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230})
        snapshot = metrics.get_metrics()
        self.assertEqual(snapshot["llm"]["calls"], 2)
        self.assertEqual(snapshot["llm"]["prompt_tokens"], 300)
        self.assertEqual(snapshot["llm"]["completion_tokens"], 80)
        self.assertEqual(snapshot["llm"]["total_tokens"], 380)

    def test_record_llm_call_failure(self) -> None:
        metrics.record_llm_call(failed=True)
        metrics.record_llm_call({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        snapshot = metrics.get_metrics()
        self.assertEqual(snapshot["llm"]["calls"], 2)
        self.assertEqual(snapshot["llm"]["failures"], 1)

    def test_record_llm_call_none_usage(self) -> None:
        metrics.record_llm_call(None)
        snapshot = metrics.get_metrics()
        self.assertEqual(snapshot["llm"]["calls"], 1)
        self.assertEqual(snapshot["llm"]["total_tokens"], 0)

    def test_record_llm_call_handles_missing_keys(self) -> None:
        metrics.record_llm_call({})  # empty usage dict
        snapshot = metrics.get_metrics()
        self.assertEqual(snapshot["llm"]["calls"], 1)
        self.assertEqual(snapshot["llm"]["prompt_tokens"], 0)

    def test_record_retrieve_call(self) -> None:
        metrics.record_retrieve_call(expansions_used=False)
        metrics.record_retrieve_call(expansions_used=True)
        metrics.record_retrieve_call(expansions_used=True)
        snapshot = metrics.get_metrics()
        self.assertEqual(snapshot["retrieve"]["calls"], 3)
        self.assertEqual(snapshot["retrieve"]["expansions_used"], 2)

    def test_record_rerank_call(self) -> None:
        metrics.record_rerank_call(fallback=False)
        metrics.record_rerank_call(fallback=True)
        snapshot = metrics.get_metrics()
        self.assertEqual(snapshot["retrieve"]["rerank_calls"], 2)
        self.assertEqual(snapshot["retrieve"]["rerank_fallbacks"], 1)

    def test_reset_clears_all(self) -> None:
        metrics.record_llm_call({"total_tokens": 100})
        metrics.record_retrieve_call()
        metrics.reset()
        snapshot = metrics.get_metrics()
        self.assertEqual(snapshot["llm"]["calls"], 0)
        self.assertEqual(snapshot["retrieve"]["calls"], 0)


class TestMetricsConcurrency(unittest.TestCase):
    """Counters are written from multiple threads in the MCP server."""

    def setUp(self) -> None:
        metrics.reset()

    def tearDown(self) -> None:
        metrics.reset()

    def test_concurrent_increments(self) -> None:
        n_threads = 8
        n_per_thread = 100

        def worker() -> None:
            for _ in range(n_per_thread):
                metrics.record_llm_call({"total_tokens": 1})
                metrics.record_retrieve_call()

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snapshot = metrics.get_metrics()
        self.assertEqual(snapshot["llm"]["calls"], n_threads * n_per_thread)
        self.assertEqual(snapshot["retrieve"]["calls"], n_threads * n_per_thread)
        self.assertEqual(snapshot["llm"]["total_tokens"], n_threads * n_per_thread)


class TestMetricsPersistence(unittest.TestCase):
    """persist/load_persisted let a separate process read server metrics."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        os.environ["SCHOLAR_HOME"] = self._tmp
        metrics.reset()

    def tearDown(self) -> None:
        os.environ.pop("SCHOLAR_HOME", None)
        shutil.rmtree(self._tmp, ignore_errors=True)
        metrics.reset()

    def test_persist_then_load_roundtrip(self) -> None:
        metrics.record_retrieve_call(expansions_used=True)
        metrics.record_llm_call({"total_tokens": 100})
        self.assertTrue(metrics.persist())
        loaded = metrics.load_persisted()
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["retrieve"]["calls"], 1)
        self.assertEqual(loaded["llm"]["total_tokens"], 100)

    def test_load_returns_none_when_no_file(self) -> None:
        self.assertIsNone(metrics.load_persisted())


if __name__ == "__main__":
    unittest.main()
