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


if __name__ == "__main__":
    unittest.main()
