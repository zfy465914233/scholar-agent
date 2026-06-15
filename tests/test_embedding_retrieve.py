"""Tests for pure functions from scholar_agent.engine.embedding_retrieve."""

import math
import unittest
from unittest.mock import patch

from scholar_agent.engine.embedding_retrieve import (
    _get_backend,
    _get_model,
    cosine_similarity,
)


class TestCosineSimilarity(unittest.TestCase):
    """Tests for cosine_similarity pure math function."""

    def test_identical_vectors(self) -> None:
        a = [1.0, 2.0, 3.0]
        sim = cosine_similarity(a, a)
        self.assertAlmostEqual(sim, 1.0, places=10)

    def test_identical_unit_vectors(self) -> None:
        a = [0.577350269, 0.577350269, 0.577350269]
        sim = cosine_similarity(a, a)
        self.assertAlmostEqual(sim, 1.0, places=5)

    def test_orthogonal_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        sim = cosine_similarity(a, b)
        self.assertAlmostEqual(sim, 0.0, places=10)

    def test_zero_vector_a(self) -> None:
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        sim = cosine_similarity(a, b)
        self.assertEqual(sim, 0.0)

    def test_zero_vector_b(self) -> None:
        a = [1.0, 2.0, 3.0]
        b = [0.0, 0.0, 0.0]
        sim = cosine_similarity(a, b)
        self.assertEqual(sim, 0.0)

    def test_both_zero_vectors(self) -> None:
        a = [0.0, 0.0]
        b = [0.0, 0.0]
        sim = cosine_similarity(a, b)
        self.assertEqual(sim, 0.0)

    def test_opposite_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        sim = cosine_similarity(a, b)
        self.assertAlmostEqual(sim, -1.0, places=10)

    def test_parallel_same_direction(self) -> None:
        a = [1.0, 2.0, 3.0]
        b = [2.0, 4.0, 6.0]
        sim = cosine_similarity(a, b)
        self.assertAlmostEqual(sim, 1.0, places=10)

    def test_parallel_opposite_direction(self) -> None:
        a = [1.0, 2.0]
        b = [-2.0, -4.0]
        sim = cosine_similarity(a, b)
        self.assertAlmostEqual(sim, -1.0, places=10)

    def test_known_angle(self) -> None:
        """cos(45 deg) = sqrt(2)/2."""
        a = [1.0, 0.0]
        b = [1.0, 1.0]
        expected = math.sqrt(2) / 2
        sim = cosine_similarity(a, b)
        self.assertAlmostEqual(sim, expected, places=10)

    def test_single_dimension(self) -> None:
        a = [3.0]
        b = [4.0]
        sim = cosine_similarity(a, b)
        self.assertAlmostEqual(sim, 1.0, places=10)

    def test_single_dimension_opposite(self) -> None:
        a = [3.0]
        b = [-4.0]
        sim = cosine_similarity(a, b)
        self.assertAlmostEqual(sim, -1.0, places=10)

    def test_high_dimensional(self) -> None:
        a = [float(i) for i in range(100)]
        b = [float(i) for i in range(100)]
        sim = cosine_similarity(a, b)
        self.assertAlmostEqual(sim, 1.0, places=10)

    def test_result_bounded(self) -> None:
        a = [1.0, 2.0, 3.0]
        b = [4.0, 5.0, 6.0]
        sim = cosine_similarity(a, b)
        self.assertGreaterEqual(sim, -1.0)
        self.assertLessEqual(sim, 1.0)


class TestGetBackend(unittest.TestCase):
    """Tests for _get_backend env-var-based backend detection."""

    @patch.dict("os.environ", {"EMBEDDING_BACKEND": "api"}, clear=False)
    def test_explicit_api(self) -> None:
        self.assertEqual(_get_backend(), "api")

    @patch.dict("os.environ", {"EMBEDDING_BACKEND": "local"}, clear=False)
    def test_explicit_local(self) -> None:
        self.assertEqual(_get_backend(), "local")

    @patch.dict("os.environ", {"EMBEDDING_BACKEND": "API"}, clear=False)
    def test_explicit_api_case_insensitive(self) -> None:
        self.assertEqual(_get_backend(), "api")

    @patch.dict("os.environ", {"EMBEDDING_BACKEND": "Local"}, clear=False)
    def test_explicit_local_mixed_case(self) -> None:
        self.assertEqual(_get_backend(), "local")

    @patch.dict("os.environ", {}, clear=True)
    def test_auto_detect_without_env(self) -> None:
        """Auto-detect returns 'local' or 'api' depending on library availability."""
        result = _get_backend()
        self.assertIn(result, ("local", "api"))

    @patch.dict("os.environ", {"EMBEDDING_BACKEND": ""}, clear=True)
    def test_empty_env_auto_detects(self) -> None:
        result = _get_backend()
        self.assertIn(result, ("local", "api"))


class TestGetModel(unittest.TestCase):
    """Tests for _get_model env-var-based model selection."""

    @patch.dict("os.environ", {"EMBEDDING_MODEL": "custom-model"}, clear=False)
    def test_explicit_model(self) -> None:
        result = _get_model()
        self.assertEqual(result, "custom-model")

    @patch.dict("os.environ", {}, clear=True)
    def test_default_model_local_backend(self) -> None:
        """When no EMBEDDING_MODEL is set, defaults depend on backend."""
        result = _get_model()
        self.assertTrue(len(result) > 0)

    @patch.dict("os.environ", {"EMBEDDING_MODEL": "text-embedding-3-large"}, clear=True)
    def test_explicit_api_model(self) -> None:
        result = _get_model()
        self.assertEqual(result, "text-embedding-3-large")


class TestEmbedQueryCache(unittest.TestCase):
    """Query embedding cache behavior."""

    def setUp(self) -> None:
        # Ensure cache is empty before each test
        from scholar_agent.engine.embedding_retrieve import clear_embed_cache

        clear_embed_cache()

    def tearDown(self) -> None:
        from scholar_agent.engine.embedding_retrieve import clear_embed_cache

        clear_embed_cache()

    def test_cache_hits_avoid_recomputation(self) -> None:
        from scholar_agent.engine import embedding_retrieve as er

        call_count = 0
        fake_vec = [0.1, 0.2, 0.3]

        def fake_embed_texts(texts):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            return [list(fake_vec) for _ in texts]

        with patch.object(er, "embed_texts", side_effect=fake_embed_texts):
            r1 = er.embed_query("hello")
            r2 = er.embed_query("hello")

        self.assertEqual(call_count, 1, "second call must hit cache")
        self.assertEqual(r1, fake_vec)
        self.assertEqual(r2, fake_vec)

    def test_different_queries_miss_cache(self) -> None:
        from scholar_agent.engine import embedding_retrieve as er

        call_count = 0

        def fake_embed_texts(texts):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            return [[0.1, 0.2] for _ in texts]

        with patch.object(er, "embed_texts", side_effect=fake_embed_texts):
            er.embed_query("hello")
            er.embed_query("world")

        self.assertEqual(call_count, 2)

    def test_empty_result_not_cached(self) -> None:
        from scholar_agent.engine import embedding_retrieve as er

        call_count = 0

        def fake_embed_texts(texts):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            return []  # backend failure

        with patch.object(er, "embed_texts", side_effect=fake_embed_texts):
            r1 = er.embed_query("hello")
            r2 = er.embed_query("hello")

        # Both calls must hit the underlying backend so failures can retry.
        self.assertEqual(call_count, 2)
        self.assertEqual(r1, [])
        self.assertEqual(r2, [])


class TestRetrieveByEmbedding(unittest.TestCase):
    """retrieve_by_embedding top-k selection and numpy/Python parity."""

    def setUp(self) -> None:
        from scholar_agent.engine import embedding_retrieve as er

        self.er = er

    def test_topk_order_and_positive_only(self) -> None:
        # query [1,0] is identical to d1 (sim 1.0), aligned with d2 (>0),
        # orthogonal to d3 (sim 0 → excluded).
        index = {
            "doc_ids": ["d1", "d2", "d3"],
            "embeddings": [[1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        }
        with patch.object(self.er, "embed_query", return_value=[1.0, 0.0]):
            res = self.er.retrieve_by_embedding("q", index, k=5)
        ids = [r[0] for r in res]
        self.assertEqual(ids[0], "d1")
        self.assertNotIn("d3", ids)
        scores = [r[1] for r in res]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_drops_empty_embeddings(self) -> None:
        index = {
            "doc_ids": ["d1", "d2", "d3"],
            "embeddings": [[1.0, 0.0], [], [0.0, 1.0]],
        }
        with patch.object(self.er, "embed_query", return_value=[1.0, 0.0]):
            res = self.er.retrieve_by_embedding("q", index, k=5)
        ids = [r[0] for r in res]
        self.assertIn("d1", ids)
        self.assertNotIn("d2", ids)  # empty embedding dropped

    def test_empty_query_returns_empty(self) -> None:
        index = {"doc_ids": ["d1"], "embeddings": [[1.0, 0.0]]}
        with patch.object(self.er, "embed_query", return_value=[]):
            res = self.er.retrieve_by_embedding("q", index, k=5)
        self.assertEqual(res, [])

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("numpy") is not None,
        "numpy not available",
    )
    def test_numpy_python_parity(self) -> None:
        import random

        rng = random.Random(0)
        dim, n = 16, 40
        doc_ids = [f"d{i}" for i in range(n)]
        embeddings = [[rng.uniform(-1, 1) for _ in range(dim)] for _ in range(n)]
        query = [rng.uniform(-1, 1) for _ in range(dim)]

        np_res = self.er._cosine_topk(query, embeddings, doc_ids, 5)
        with patch.object(self.er, "_HAS_NUMPY", False):
            py_res = self.er._cosine_topk(query, embeddings, doc_ids, 5)

        self.assertEqual([r[0] for r in np_res], [r[0] for r in py_res])
        for (_id_np, s_np), (_id_py, s_py) in zip(np_res, py_res, strict=True):
            self.assertEqual(_id_np, _id_py)
            self.assertAlmostEqual(s_np, s_py, places=9)


class TestIncrementalEmbeddingIndex(unittest.TestCase):
    """build_embedding_index reuses unchanged embeddings, re-embeds changed."""

    def test_reuses_unchanged_embeddings(self) -> None:
        from scholar_agent.engine.embedding_retrieve import _text_hash, build_embedding_index

        docs = [
            {"doc_id": "a", "search_text": "alpha beta"},
            {"doc_id": "b", "search_text": "gamma delta"},
            {"doc_id": "c", "search_text": "epsilon"},  # new
        ]
        existing = {
            "doc_ids": ["a", "b"],
            "embeddings": [[1.0, 0.0], [0.0, 1.0]],
            "text_hashes": {
                "a": _text_hash("alpha beta"),
                "b": _text_hash("gamma delta"),
            },
        }

        embedded_texts: list[list[str]] = []

        def fake_embed(texts: list[str]) -> list[list[float]]:
            embedded_texts.append(list(texts))
            return [[0.5, 0.5] for _ in texts]

        with patch("scholar_agent.engine.embedding_retrieve.embed_texts", side_effect=fake_embed):
            idx = build_embedding_index(docs, existing_index=existing)

        # Only the new doc "c" is embedded; "a" and "b" are reused verbatim.
        self.assertEqual(embedded_texts, [["epsilon"]])
        emb_map = dict(zip(idx["doc_ids"], idx["embeddings"], strict=True))
        self.assertEqual(emb_map["a"], [1.0, 0.0])
        self.assertEqual(emb_map["b"], [0.0, 1.0])
        self.assertEqual(emb_map["c"], [0.5, 0.5])
        self.assertIn("c", idx["text_hashes"])

    def test_reembeds_modified_doc(self) -> None:
        from scholar_agent.engine.embedding_retrieve import _text_hash, build_embedding_index

        docs = [{"doc_id": "a", "search_text": "changed text"}]
        existing = {
            "doc_ids": ["a"],
            "embeddings": [[1.0, 0.0]],
            "text_hashes": {"a": _text_hash("original text")},  # mismatch → re-embed
        }
        with patch("scholar_agent.engine.embedding_retrieve.embed_texts", return_value=[[0.9, 0.1]]):
            idx = build_embedding_index(docs, existing_index=existing)
        self.assertEqual(dict(zip(idx["doc_ids"], idx["embeddings"], strict=True))["a"], [0.9, 0.1])

    def test_no_existing_index_embeds_all(self) -> None:
        from scholar_agent.engine.embedding_retrieve import build_embedding_index

        docs = [{"doc_id": "a", "search_text": "x"}, {"doc_id": "b", "search_text": "y"}]
        with patch("scholar_agent.engine.embedding_retrieve.embed_texts", return_value=[[1.0], [2.0]]):
            idx = build_embedding_index(docs)
        emb_map = dict(zip(idx["doc_ids"], idx["embeddings"], strict=True))
        self.assertEqual(emb_map["a"], [1.0])
        self.assertEqual(emb_map["b"], [2.0])
        self.assertIn("a", idx["text_hashes"])


if __name__ == "__main__":
    unittest.main()
