"""Unit tests for the Porter stemmer and its integration into BM25 tokenization."""

from __future__ import annotations

import unittest

from scholar_agent.engine.bm25 import BM25, tokenize
from scholar_agent.engine.stemmer import stem, stem_tokens


class TestPorterStemmer(unittest.TestCase):
    """Core Porter stemmer behavior."""

    def test_morphological_variants_collapse_diffusion(self) -> None:
        stems = {stem(w) for w in ("diffusion", "diffusing", "diffused")}
        self.assertEqual(len(stems), 1, f"expected collapse, got {stems}")

    def test_morphological_variants_collapse_optimize(self) -> None:
        stems = {stem(w) for w in ("optimize", "optimizing", "optimized", "optimization")}
        self.assertEqual(len(stems), 1, f"expected collapse, got {stems}")

    def test_morphological_variants_collapse_embedding(self) -> None:
        # Note: Porter is non-idempotent by design (Porter 1980). "embed" itself
        # contains "ed" and gets re-stemmed, so we test only the inflected forms.
        stems = {stem(w) for w in ("embedding", "embeddings", "embedded")}
        self.assertEqual(len(stems), 1, f"expected collapse, got {stems}")

    def test_classic_porter_test_cases(self) -> None:
        """Porter's canonical examples from the 1980 paper."""
        cases = [
            ("caresses", "caress"),
            ("ponies", "poni"),
            ("cats", "cat"),
            ("agreed", "agre"),
            ("running", "run"),
            ("happy", "happi"),
            ("relational", "relat"),
            ("conditional", "condit"),
            ("rational", "ration"),
            ("hopeful", "hope"),
            ("goodness", "good"),
        ]
        for word, expected in cases:
            with self.subTest(word=word):
                self.assertEqual(stem(word), expected)

    def test_short_words_untouched(self) -> None:
        for w in ("a", "be", "is"):
            self.assertEqual(stem(w), w)

    def test_empty_input(self) -> None:
        self.assertEqual(stem(""), "")

    def test_stem_tokens_batch(self) -> None:
        out = stem_tokens(["diffusion", "embeddings", "cats"])
        self.assertEqual(out, ["diffus", "embed", "cat"])

    def test_non_idempotency_is_known_porter_behavior(self) -> None:
        """Porter is non-idempotent by design (Porter 1980).

        ``stem("diffusion") = "diffus"`` but ``stem("diffus") = "diffu"`` because
        step 1a strips trailing single 's'. This is documented behavior; BM25 is
        unaffected because doc and query share the same stem() function.
        """
        self.assertEqual(stem("diffusion"), "diffus")
        self.assertEqual(stem("diffus"), "diffu")


class TestBM25StemmerIntegration(unittest.TestCase):
    """BM25.tokenize applies stemming to English tokens."""

    def test_tokenize_stems_english(self) -> None:
        toks = tokenize("diffusion models are diffusing data")
        # "diffusion" and "diffusing" should both stem to "diffus"
        self.assertIn("diffus", toks)
        self.assertEqual(toks.count("diffus"), 2)

    def test_tokenize_preserves_chinese(self) -> None:
        # CJK should pass through unchanged
        toks = tokenize("扩散模型 diffusion model")
        self.assertIn("扩散", toks)
        self.assertIn("模型", toks)
        self.assertIn("diffus", toks)
        self.assertIn("model", toks)

    def test_bm25_recall_via_stemming(self) -> None:
        """Doc with 'diffusion' must be retrievable by 'diffusing' query."""
        docs = [
            {"doc_id": "d1", "search_text": "diffusion model for image generation"},
            {"doc_id": "d2", "search_text": "linear programming optimization"},
        ]
        bm25 = BM25(docs)
        results = bm25.top_k("diffusing models", k=1)
        self.assertEqual(results[0][0], 0, "stemmed query must match d1")

    def test_bm25_stemming_does_not_break_exact_match(self) -> None:
        docs = [{"doc_id": "a", "search_text": "markov chain"}, {"doc_id": "b", "search_text": "linear algebra"}]
        bm25 = BM25(docs)
        results = bm25.top_k("markov", k=2)
        self.assertEqual(results[0][0], 0)


if __name__ == "__main__":
    unittest.main()
