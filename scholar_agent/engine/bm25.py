"""BM25 scoring for local knowledge retrieval.

Implements Okapi BM25 without external dependencies. Used by local_retrieve.py
to replace the previous simple TF scoring with proper term-frequency weighting
and document-length normalization.
"""

from __future__ import annotations

import math
import re
from typing import Sequence


TOKEN_RE = re.compile(r"[a-z0-9_-]+")
CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "is", "of", "on", "or", "that", "the", "to", "what", "when",
    "where", "which", "who",
}


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    tokens = [t for t in TOKEN_RE.findall(lowered) if t not in STOPWORDS]

    for chunk in CJK_RE.findall(lowered):
        if len(chunk) == 1:
            tokens.append(chunk)
            continue

        # Use overlapping bigrams as a lightweight Chinese tokenizer.
        tokens.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))

    return tokens


class BM25:
    """Okapi BM25 scorer for a collection of documents.

    Parameters
    ----------
    documents : list of dict
        Each document must have a ``search_text`` field used for term counting.
        Any additional fields are preserved through scoring.
    k1 : float
        Term frequency saturation parameter (default 1.5).
    b : float
        Document length normalization parameter (default 0.75).
    """

    def __init__(self, documents: list[dict], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs: list[dict] = documents
        self.corpus_size = len(documents)

        # Build per-document term frequencies and lengths
        self.doc_term_freqs: list[dict[str, int]] = []
        self.doc_lengths: list[int] = []
        self.avg_dl: float = 0.0

        total_length = 0
        for doc in documents:
            terms = tokenize(str(doc.get("search_text", "")))
            tf: dict[str, int] = {}
            for t in terms:
                tf[t] = tf.get(t, 0) + 1
            self.doc_term_freqs.append(tf)
            self.doc_lengths.append(len(terms))
            total_length += len(terms)

        self.avg_dl = total_length / self.corpus_size if self.corpus_size else 1.0

        # Build document frequency (how many docs contain each term)
        self.doc_freq: dict[str, int] = {}
        for tf in self.doc_term_freqs:
            for term in tf:
                self.doc_freq[term] = self.doc_freq.get(term, 0) + 1

        # Precompute IDF for each term
        self.idf_cache: dict[str, float] = {}
        for term, df in self.doc_freq.items():
            self.idf_cache[term] = math.log((self.corpus_size - df + 0.5) / (df + 0.5) + 1.0)

    def _score_single(self, query_terms: list[str], doc_idx: int) -> float:
        tf_map = self.doc_term_freqs[doc_idx]
        dl = self.doc_lengths[doc_idx]
        score = 0.0
        for term in query_terms:
            tf = tf_map.get(term, 0)
            if tf == 0:
                continue
            idf = self.idf_cache.get(term, 0.0)
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * dl / self.avg_dl)
            score += idf * numerator / denominator
        return score

    def score(self, query: str) -> list[tuple[int, float, list[str]]]:
        """Score all documents against a query.

        Returns a list of (doc_index, score, matched_terms) sorted by score descending.
        """
        query_terms = tokenize(query)
        results: list[tuple[int, float, list[str]]] = []

        for idx in range(self.corpus_size):
            tf_map = self.doc_term_freqs[idx]
            matched = [t for t in query_terms if t in tf_map]
            if not matched:
                continue
            s = self._score_single(query_terms, idx)
            if s > 0:
                results.append((idx, s, matched))

        results.sort(key=lambda x: -x[1])
        return results

    def top_k(self, query: str, k: int = 5) -> list[tuple[int, float, list[str]]]:
        return self.score(query)[:k]
