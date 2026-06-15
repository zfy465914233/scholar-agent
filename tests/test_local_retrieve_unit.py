"""Unit tests for scholar_agent.engine.local_retrieve — direct imports, no subprocess."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scholar_agent.engine.bm25 import BM25
from scholar_agent.engine.local_retrieve import (
    _bm25_ranked_with_expansion,
    _is_ambiguous,
    _normalize_scores,
    retrieve,
    retrieve_bm25,
    retrieve_hybrid,
)


def _make_documents(n: int = 5) -> list[dict]:
    """Create n test documents with distinct search_text."""
    docs = []
    topics = ["physics", "math", "biology", "chemistry", "computer science"]
    for i in range(n):
        docs.append(
            {
                "doc_id": f"doc-{i}",
                "path": f"/path/to/doc_{i}.md",
                "title": f"Document {i} about {topics[i % len(topics)]}",
                "type": "knowledge",
                "topic": topics[i % len(topics)],
                "search_text": f"This is document number {i} about {topics[i % len(topics)]}. "
                + ("markov chain probability " * (i % 2))
                + ("neural network deep learning " * ((i + 1) % 2)),
            }
        )
    return docs


class TestNormalizeScores(unittest.TestCase):
    """Tests for _normalize_scores."""

    def test_empty_dict(self) -> None:
        result = _normalize_scores({})
        self.assertEqual(result, {})

    def test_single_value(self) -> None:
        result = _normalize_scores({"a": 5.0})
        # Range is 0, so all values map to 1.0
        self.assertEqual(result, {"a": 1.0})

    def test_already_normalized(self) -> None:
        result = _normalize_scores({"a": 0.0, "b": 0.5, "c": 1.0})
        self.assertAlmostEqual(result["a"], 0.0)
        self.assertAlmostEqual(result["b"], 0.5)
        self.assertAlmostEqual(result["c"], 1.0)

    def test_all_same_values(self) -> None:
        result = _normalize_scores({"a": 3.0, "b": 3.0, "c": 3.0})
        # All same -> range 0 -> all mapped to 1.0
        self.assertEqual(result, {"a": 1.0, "b": 1.0, "c": 1.0})

    def test_general_normalization(self) -> None:
        result = _normalize_scores({"a": 2.0, "b": 4.0, "c": 6.0})
        self.assertAlmostEqual(result["a"], 0.0)
        self.assertAlmostEqual(result["b"], 0.5)
        self.assertAlmostEqual(result["c"], 1.0)

    def test_negative_values(self) -> None:
        result = _normalize_scores({"a": -5.0, "b": 0.0, "c": 5.0})
        self.assertAlmostEqual(result["a"], 0.0)
        self.assertAlmostEqual(result["b"], 0.5)
        self.assertAlmostEqual(result["c"], 1.0)

    def test_two_values(self) -> None:
        result = _normalize_scores({"x": 10.0, "y": 20.0})
        self.assertAlmostEqual(result["x"], 0.0)
        self.assertAlmostEqual(result["y"], 1.0)


class TestRetrieveBM25(unittest.TestCase):
    """Tests for retrieve_bm25."""

    def test_basic_retrieval(self) -> None:
        docs = _make_documents(5)
        results = retrieve_bm25("markov chain", docs, limit=3)
        self.assertLessEqual(len(results), 3)
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("doc_id", r)
            self.assertIn("score", r)
            self.assertIn("matched_terms", r)
            self.assertEqual(r["source"], "bm25")
            self.assertIn("markov", r["matched_terms"])

    def test_limit_respected(self) -> None:
        docs = _make_documents(10)
        results = retrieve_bm25("document", docs, limit=2)
        self.assertLessEqual(len(results), 2)

    def test_no_results_for_unrelated_query(self) -> None:
        docs = _make_documents(3)
        results = retrieve_bm25("xyzzy_nonexistent_term_12345", docs, limit=5)
        # Might be 0 if no doc matches
        self.assertIsInstance(results, list)

    def test_results_have_required_fields(self) -> None:
        docs = _make_documents(5)
        results = retrieve_bm25("neural network", docs, limit=5)
        for r in results:
            self.assertIn("doc_id", r)
            self.assertIn("path", r)
            self.assertIn("title", r)
            self.assertIn("type", r)
            self.assertIn("topic", r)
            self.assertIn("score", r)
            self.assertIn("matched_terms", r)
            self.assertIn("source", r)
            self.assertIsInstance(r["matched_terms"], list)

    def test_scores_positive(self) -> None:
        docs = _make_documents(5)
        results = retrieve_bm25("markov", docs, limit=5)
        for r in results:
            self.assertGreater(r["score"], 0)

    def test_with_index_path(self) -> None:
        """Passing index_path triggers caching behavior but still returns results."""
        docs = _make_documents(5)
        with tempfile.TemporaryDirectory() as tmp:
            idx = Path(tmp) / "index.json"
            idx.write_text("{}", encoding="utf-8")
            results = retrieve_bm25("markov", docs, limit=3, index_path=idx)
            self.assertIsInstance(results, list)

    def test_missing_optional_fields_do_not_raise(self) -> None:
        docs = [{"doc_id": "legacy", "title": "Legacy Markov note", "search_text": "markov chain"}]
        results = retrieve_bm25("markov", docs, limit=1)
        self.assertEqual("legacy", results[0]["doc_id"])
        self.assertEqual("", results[0]["path"])
        self.assertEqual("", results[0]["type"])
        self.assertEqual("", results[0]["topic"])


class TestRetrieveHybrid(unittest.TestCase):
    """Tests for retrieve_hybrid."""

    def test_hybrid_without_embedding_falls_back_to_bm25(self) -> None:
        """When embedding_index is None, hybrid falls back to BM25 results."""
        docs = _make_documents(5)
        results = retrieve_hybrid(
            "markov chain",
            docs,
            embedding_index=None,
            bm25_weight=0.6,
            limit=3,
        )
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertEqual(r["source"], "bm25")

    def test_hybrid_with_empty_embedding_index(self) -> None:
        """Empty embedding_index dict falls back to BM25."""
        docs = _make_documents(5)
        results = retrieve_hybrid(
            "markov chain",
            docs,
            embedding_index={},
            bm25_weight=0.6,
            limit=3,
        )
        # Should still return results (bm25 fallback due to no embedding scores)
        self.assertIsInstance(results, list)

    def test_hybrid_with_mock_embedding(self) -> None:
        """Hybrid retrieval with mocked embedding returns results."""
        import types

        docs = _make_documents(5)
        mock_module = types.ModuleType("scholar_agent.engine.embedding_retrieve")
        mock_module.retrieve_by_embedding = lambda query, index, k: [("doc-0", 0.95), ("doc-2", 0.8)]
        with patch.dict("sys.modules", {"scholar_agent.engine.embedding_retrieve": mock_module}):
            results = retrieve_hybrid(
                "markov chain",
                docs,
                embedding_index={"some": "data"},
                bm25_weight=0.5,
                limit=3,
            )
            self.assertGreater(len(results), 0)
            sources = {r["source"] for r in results}
            self.assertTrue(sources.intersection({"hybrid", "bm25"}))

    def test_hybrid_limit_respected(self) -> None:
        docs = _make_documents(10)
        results = retrieve_hybrid(
            "document",
            docs,
            embedding_index=None,
            bm25_weight=0.6,
            limit=2,
        )
        self.assertLessEqual(len(results), 2)

    def test_hybrid_results_have_correct_fields(self) -> None:
        docs = _make_documents(5)
        results = retrieve_hybrid(
            "markov",
            docs,
            embedding_index=None,
            bm25_weight=0.6,
            limit=5,
        )
        for r in results:
            self.assertIn("doc_id", r)
            self.assertIn("score", r)
            self.assertIn("matched_terms", r)
            self.assertIn("source", r)


class TestRetrieve(unittest.TestCase):
    """Tests for retrieve — the main entry point."""

    def _make_index_file(self, tmpdir: str, docs: list[dict] | None = None) -> Path:
        """Create a temporary index JSON file and return its path."""
        if docs is None:
            docs = _make_documents(5)
        index_path = Path(tmpdir) / "index.json"
        index_path.write_text(
            json.dumps({"documents": docs}, ensure_ascii=False),
            encoding="utf-8",
        )
        return index_path

    def test_basic_retrieve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index_path = self._make_index_file(tmp)
            result = retrieve("markov chain", index_path, limit=3)

            self.assertIn("query", result)
            self.assertIn("results", result)
            self.assertEqual(result["query"], "markov chain")
            self.assertIsInstance(result["results"], list)

    def test_retrieve_with_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index_path = self._make_index_file(tmp)
            result = retrieve("document", index_path, limit=2)
            self.assertLessEqual(len(result["results"]), 2)

    def test_retrieve_missing_index(self) -> None:
        """Retrieving from a non-existent index returns error."""
        index_path = Path("/nonexistent/path/index.json")
        result = retrieve("test", index_path, limit=5)
        self.assertIn("error", result)
        self.assertEqual(result["results"], [])

    def test_retrieve_invalid_json(self) -> None:
        """Retrieving from an invalid JSON file returns error."""
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "bad.json"
            index_path.write_text("not valid json {{{", encoding="utf-8")
            result = retrieve("test", index_path, limit=5)
            self.assertIn("error", result)
            self.assertEqual(result["results"], [])

    def test_retrieve_empty_documents(self) -> None:
        """Empty documents list returns empty results."""
        with tempfile.TemporaryDirectory() as tmp:
            index_path = self._make_index_file(tmp, docs=[])
            result = retrieve("markov", index_path, limit=5)
            self.assertEqual(result["results"], [])

    def test_retrieve_with_embedding_index(self) -> None:
        """Passing embedding_index_path triggers hybrid retrieval."""
        import types

        with tempfile.TemporaryDirectory() as tmp:
            docs = _make_documents(5)
            index_path = self._make_index_file(tmp, docs)

            # Create an embedding index file
            emb_path = Path(tmp) / "embeddings.json"
            emb_path.write_text('{"some": "data"}', encoding="utf-8")

            mock_module = types.ModuleType("scholar_agent.engine.embedding_retrieve")
            mock_module.retrieve_by_embedding = lambda q, idx, k: [("doc-0", 0.9)]

            with patch.dict("sys.modules", {"scholar_agent.engine.embedding_retrieve": mock_module}):
                result = retrieve(
                    "markov chain",
                    index_path,
                    limit=3,
                    embedding_index_path=str(emb_path),
                    bm25_weight=0.5,
                )
                self.assertIn("results", result)

    def test_retrieve_nonexistent_embedding_index_uses_bm25(self) -> None:
        """Non-existent embedding_index_path falls back to BM25-only."""
        with tempfile.TemporaryDirectory() as tmp:
            index_path = self._make_index_file(tmp)
            result = retrieve(
                "markov",
                index_path,
                limit=3,
                embedding_index_path="/nonexistent/embeddings.json",
            )
            self.assertIn("results", result)
            if result["results"]:
                self.assertEqual(result["results"][0]["source"], "bm25")

    def test_retrieve_preserves_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index_path = self._make_index_file(tmp)
            result = retrieve("custom query text", index_path, limit=5)
            self.assertEqual(result["query"], "custom query text")


class TestParseArgs(unittest.TestCase):
    """Tests for parse_args CLI function."""

    def test_basic_query(self) -> None:
        from scholar_agent.engine.local_retrieve import parse_args

        with patch("sys.argv", ["local_retrieve", "test query"]):
            args = parse_args()
        self.assertEqual(args.query, "test query")
        self.assertEqual(args.limit, 5)

    def test_custom_limit(self) -> None:
        from scholar_agent.engine.local_retrieve import parse_args

        with patch("sys.argv", ["local_retrieve", "q", "--limit", "10"]):
            args = parse_args()
        self.assertEqual(args.limit, 10)

    def test_custom_bm25_weight(self) -> None:
        from scholar_agent.engine.local_retrieve import parse_args

        with patch("sys.argv", ["local_retrieve", "q", "--bm25-weight", "0.3"]):
            args = parse_args()
        self.assertAlmostEqual(args.bm25_weight, 0.3)

    def test_custom_index(self) -> None:
        from scholar_agent.engine.local_retrieve import parse_args

        with patch("sys.argv", ["local_retrieve", "q", "--index", "/tmp/myidx.json"]):
            args = parse_args()
        self.assertEqual(Path(args.index), Path("/tmp/myidx.json"))

    def test_embedding_index_option(self) -> None:
        from scholar_agent.engine.local_retrieve import parse_args

        with patch("sys.argv", ["local_retrieve", "q", "--embedding-index", "/tmp/emb.json"]):
            args = parse_args()
        self.assertEqual(Path(args.embedding_index), Path("/tmp/emb.json"))


class TestMain(unittest.TestCase):
    """Tests for the main() entry point."""

    def test_main_outputs_json(self) -> None:
        from scholar_agent.engine.local_retrieve import main

        with tempfile.TemporaryDirectory() as tmp:
            idx = Path(tmp) / "index.json"
            idx.write_text(json.dumps({"documents": _make_documents(3)}), encoding="utf-8")
            with patch("sys.argv", ["local_retrieve", "document", "--index", str(idx), "--limit", "2"]):
                with patch("builtins.print") as mock_print:
                    ret = main()
                self.assertEqual(ret, 0)
                mock_print.assert_called_once()
                output = mock_print.call_args[0][0]
                data = json.loads(output)
                self.assertEqual(data["query"], "document")
                self.assertIn("results", data)

    def test_main_with_embedding_index(self) -> None:
        import types

        from scholar_agent.engine.local_retrieve import main

        with tempfile.TemporaryDirectory() as tmp:
            idx = Path(tmp) / "index.json"
            idx.write_text(json.dumps({"documents": _make_documents(3)}), encoding="utf-8")
            emb = Path(tmp) / "emb.json"
            emb.write_text('{"data": true}', encoding="utf-8")
            mock_mod = types.ModuleType("scholar_agent.engine.embedding_retrieve")
            mock_mod.retrieve_by_embedding = lambda q, i, k: [("doc-0", 0.9)]
            with (
                patch.dict("sys.modules", {"scholar_agent.engine.embedding_retrieve": mock_mod}),
                patch("sys.argv", ["local_retrieve", "markov", "--index", str(idx), "--embedding-index", str(emb)]),
                patch("builtins.print"),
            ):
                ret = main()
            self.assertEqual(ret, 0)


class TestOSErrorCacheBranch(unittest.TestCase):
    """Cover the OSError branch in _get_bm25."""

    def test_oserror_on_stat(self) -> None:
        """When index_path.stat() raises OSError, the cache key uses 0.0 mtime."""
        from scholar_agent.engine.local_retrieve import retrieve_bm25

        docs = _make_documents(5)
        # Use a path that does not exist so .stat() raises OSError
        fake_path = Path("/nonexistent_dir_abc/index.json")
        results = retrieve_bm25("markov", docs, limit=3, index_path=fake_path)
        self.assertIsInstance(results, list)


class TestEmbeddingExceptionFallback(unittest.TestCase):
    """Cover the embedding retrieval exception handling."""

    def test_embedding_raises_falls_back(self) -> None:
        import types

        from scholar_agent.engine.local_retrieve import retrieve_hybrid

        docs = _make_documents(5)
        mock_mod = types.ModuleType("scholar_agent.engine.embedding_retrieve")

        def bad_embedding(query, index, k):
            raise RuntimeError("embedding service down")

        mock_mod.retrieve_by_embedding = bad_embedding
        with patch.dict("sys.modules", {"scholar_agent.engine.embedding_retrieve": mock_mod}):
            results = retrieve_hybrid("markov", docs, {"some": "data"}, 0.6, 5)
        # Falls back to BM25-only
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertEqual(r["source"], "bm25")


class TestExpansionBlend(unittest.TestCase):
    """Synonym expansion blends original + expansion BM25 scores.

    Contract: the original query's ranking is preserved (precision), while an
    expansion-only card can still enter top-k (recall).
    """

    def test_no_expansion_matches_plain_bm25(self) -> None:
        docs = _make_documents(5)
        bm25 = BM25(docs)
        with patch("scholar_agent.engine.local_retrieve.expand_query", return_value=["markov chain"]):
            ranked = _bm25_ranked_with_expansion(bm25, "markov chain", 3)
        plain = [idx for idx, _s, _m in bm25.score("markov chain")[:3]]
        self.assertEqual([r[0] for r in ranked], plain)

    def test_expansion_keeps_precise_hit_at_top(self) -> None:
        docs = _make_documents(5)
        bm25 = BM25(docs)
        plain_top1 = bm25.score("markov chain")[0][0]
        with patch(
            "scholar_agent.engine.local_retrieve.expand_query",
            return_value=["markov chain", "probability transition matrix"],
        ):
            ranked = _bm25_ranked_with_expansion(bm25, "markov chain", 3)
        self.assertEqual(ranked[0][0], plain_top1)

    def test_expansion_surfaces_missed_card(self) -> None:
        # doc-A is invisible to the original query but an expansion maps to it.
        docs = [
            {"doc_id": "A", "search_text": "denoising score matching SDE generative"},
            {"doc_id": "B", "search_text": "alpha beta gamma delta"},
            {"doc_id": "C", "search_text": "epsilon zeta eta theta"},
        ]
        bm25 = BM25(docs)
        with patch(
            "scholar_agent.engine.local_retrieve.expand_query",
            return_value=["image generation", "SDE"],
        ):
            ranked = _bm25_ranked_with_expansion(bm25, "image generation", 3)
        self.assertEqual(ranked[0][0], 0)  # doc index 0 = A, surfaced by expansion


class TestResultSnippet(unittest.TestCase):
    """retrieve results carry a body snippet so callers need no second Read."""

    def test_bm25_results_have_snippet(self) -> None:
        docs = _make_documents(5)
        results = retrieve_bm25("markov chain", docs, 3)
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("snippet", r)
            self.assertIsInstance(r["snippet"], str)
            self.assertLessEqual(len(r["snippet"]), 300)

    def test_hybrid_results_have_snippet(self) -> None:
        docs = _make_documents(5)
        # empty embedding index → BM25 fallback path, still must carry snippet
        results = retrieve_hybrid("markov chain", docs, {"doc_ids": [], "embeddings": []}, 0.8, 3)
        for r in results:
            self.assertIn("snippet", r)

    def test_retrieve_injects_confidence(self) -> None:
        # retrieve() (the entry point) annotates each result with the card's
        # confidence so callers can weight trust without a second file read.
        import json
        import tempfile

        docs = _make_documents(5)
        with tempfile.TemporaryDirectory() as tmp:
            idx = Path(tmp) / "index.json"
            idx.write_text(json.dumps({"documents": docs}))
            payload = retrieve("markov chain", idx, 3)
        for r in payload["results"]:
            self.assertIn("confidence", r)
            self.assertIsInstance(r["confidence"], str)


class TestAmbiguityDetection(unittest.TestCase):
    """_is_ambiguous flags nearly-tied top-2 for opt-in rerank."""

    def test_tied_scores_are_ambiguous(self) -> None:
        self.assertTrue(_is_ambiguous([{"score": 10.0}, {"score": 9.5}]))

    def test_clear_gap_not_ambiguous(self) -> None:
        self.assertFalse(_is_ambiguous([{"score": 10.0}, {"score": 5.0}]))

    def test_single_result_not_ambiguous(self) -> None:
        self.assertFalse(_is_ambiguous([{"score": 10.0}]))


if __name__ == "__main__":
    unittest.main()
