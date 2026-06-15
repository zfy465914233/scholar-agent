"""Hybrid retrieval over the local knowledge index.

Combines BM25 lexical scoring with optional embedding-based semantic retrieval,
then reranks results using a weighted blend. Falls back to BM25-only when
no embedding index is available.

Usage:
  python local_retrieve.py "what is a markov chain"
  python local_retrieve.py "radar rainfall estimation" --embedding-index indexes/local/embeddings.json
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
from pathlib import Path
from typing import TypeVar

from scholar_agent.engine.bm25 import BM25
from scholar_agent.engine.synonyms import expand_query

logger = logging.getLogger(__name__)

DEFAULT_INDEX = Path("indexes/local/index.json")

# Blend weights for synonym query expansion. The original query keeps its full
# BM25 score (1.0) so its ranking is preserved exactly (nDCG-stable); the
# expansion term (0.1) is small enough that an expansion-only card can only
# oust the *weakest* original hit — filling recall when the original returned
# fewer than k relevant docs, never re-ranking the top. Tuned on the retrieval
# benchmark: orig=1.0 / exp∈[0.05, 0.15] holds nDCG@3=0.950 while lifting
# Recall@5 from 0.967 to 1.000.
_EXPANSION_ORIG_WEIGHT = 1.0
_EXPANSION_EXP_WEIGHT = 0.1

_bm25_cache: dict[tuple[str, float], tuple[BM25, list[dict]]] = {}
_bm25_lock = threading.Lock()


def _get_bm25(documents: list[dict], index_path: Path) -> BM25:
    """Get or create a cached BM25 instance for the given index."""
    try:
        cache_key = (str(index_path), index_path.stat().st_mtime)
    except OSError:
        cache_key = (str(index_path), 0.0)

    with _bm25_lock:
        cached = _bm25_cache.get(cache_key)
        if cached is not None:
            return cached[0]

    bm25 = BM25(documents)

    with _bm25_lock:
        _bm25_cache[cache_key] = (bm25, documents)
        if len(_bm25_cache) > 4:
            oldest = next(iter(_bm25_cache))
            del _bm25_cache[oldest]

    return bm25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retrieve local knowledge documents from the JSON index.")
    parser.add_argument("query", help="Query text for retrieval")
    parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX,
        help="Path to the local JSON index file.",
    )
    parser.add_argument(
        "--embedding-index",
        type=Path,
        default=None,
        help="Path to embedding index JSON for semantic retrieval.",
    )
    parser.add_argument(
        "--bm25-weight",
        type=float,
        default=0.8,
        help="Weight for BM25 scores in hybrid ranking (0-1). Default: 0.8",
    )
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of results to return.")
    return parser.parse_args()


_K = TypeVar("_K")


def _normalize_scores(scores: dict[_K, float]) -> dict[_K, float]:
    """Normalize scores to [0, 1] range."""
    if not scores:
        return {}
    min_s = min(scores.values())
    max_s = max(scores.values())
    rng = max_s - min_s
    if rng == 0:
        return {k: 1.0 for k in scores}
    return {k: (v - min_s) / rng for k, v in scores.items()}


def _bm25_ranked_with_expansion(bm25: BM25, query: str, k: int) -> list[tuple[int, float, set[str]]]:
    """Run BM25 over the original query, boosted by synonym-expansion scores.

    The original query's BM25 score is the authoritative signal — a precise
    lexical hit outranks everything. Synonym expansions add a secondary,
    per-query-normalized boost so a card the original query missed, but an
    expansion maps to, can still enter top-k. Blended as:

    $\\text{score}(d) = w_o \\cdot \\widehat{s}_{\\text{orig}}(d) + w_e \\cdot \\max_{q \\in \\text{exp}} \\widehat{s}_q(d)$

    where hats are min-max normalization within each query, $w_o$ =
    :data:`_EXPANSION_ORIG_WEIGHT`, $w_e$ = :data:`_EXPANSION_EXP_WEIGHT`.

    This deliberately keeps the original query dominant (precision: a precise
    hit stays on top) while letting expansion consensus surface (recall: a
    missed-but-synonym-relevant card outranks a weak original-only hit). Pure
    RRF was tried and rejected — it discards match strength and lets a
    broad-theme card outrank a precise hit (benchmark nDCG 0.950 → 0.844).

    Returns ``(doc_idx, blended_score, matched_terms)`` sorted by score desc.
    The original query's results are returned unchanged when there are no
    expansions.
    """
    expansions = expand_query(query)
    orig_results = bm25.score(query)
    if len(expansions) <= 1:
        return [(idx, score, set(matched)) for idx, score, matched in orig_results[:k]]

    orig_raw = {idx: s for idx, s, _ in orig_results}
    orig_matched = {idx: set(m) for idx, _, m in orig_results}
    norm_orig = _normalize_scores(orig_raw)

    # Per-expansion normalized score, take the max so each expansion
    # contributes fairly regardless of its raw-score scale (IDF / length).
    exp_best: dict[int, float] = {}
    exp_matched: dict[int, set[str]] = {}
    for sub_query in expansions[1:]:
        sub_results = bm25.score(sub_query)
        if not sub_results:
            continue
        norm_sub = _normalize_scores({idx: s for idx, s, _ in sub_results})
        for idx, _s, matched in sub_results:
            ns = norm_sub.get(idx, 0.0)
            if ns > exp_best.get(idx, 0.0):
                exp_best[idx] = ns
            exp_matched.setdefault(idx, set()).update(matched)

    all_docs = set(norm_orig) | set(exp_best)
    blended: dict[int, float] = {}
    for idx in all_docs:
        blended[idx] = _EXPANSION_ORIG_WEIGHT * norm_orig.get(idx, 0.0) + _EXPANSION_EXP_WEIGHT * exp_best.get(idx, 0.0)

    ranked = sorted(blended.items(), key=lambda x: -x[1])[:k]
    return [(idx, score, orig_matched.get(idx, set()) | exp_matched.get(idx, set())) for idx, score in ranked]


SNIPPET_MAX_CHARS = 300


def _snippet(doc: dict) -> str:
    """Truncated search_text for a result preview.

    Lets the caller judge relevance — and often answer directly — from the
    retrieval payload, without a second file Read per hit.
    """
    return str(doc.get("search_text", ""))[:SNIPPET_MAX_CHARS]


def retrieve_bm25(query: str, documents: list[dict], limit: int, index_path: Path | None = None) -> list[dict]:
    """BM25-only retrieval with synonym query expansion (score blend)."""
    bm25 = _get_bm25(documents, index_path) if index_path is not None else BM25(documents)
    ranked = _bm25_ranked_with_expansion(bm25, query, limit)
    results = []
    for doc_idx, score, matched_terms in ranked:
        doc = documents[doc_idx]
        results.append(
            {
                "doc_id": doc.get("doc_id", ""),
                "path": doc.get("path", ""),
                "title": doc.get("title", ""),
                "type": doc.get("type", ""),
                "topic": doc.get("topic", ""),
                "snippet": _snippet(doc),
                "score": round(score, 4),
                "matched_terms": sorted(set(matched_terms)),
                "source": "bm25",
            }
        )
    return results


def retrieve_hybrid(
    query: str,
    documents: list[dict],
    embedding_index: dict | None,
    bm25_weight: float,
    limit: int,
    index_path: Path | None = None,
) -> list[dict]:
    """Hybrid retrieval: BM25 (with synonym expansion) + embedding reranking."""
    bm25 = _get_bm25(documents, index_path) if index_path is not None else BM25(documents)
    bm25_results = _bm25_ranked_with_expansion(bm25, query, limit * 3)  # fetch more candidates for reranking

    # BM25 scores
    bm25_scores: dict[str, float] = {}
    for doc_idx, score, _ in bm25_results:
        bm25_scores[documents[doc_idx]["doc_id"]] = score

    # Embedding scores
    emb_scores: dict[str, float] = {}
    if embedding_index is not None:
        try:
            from scholar_agent.engine.embedding_retrieve import retrieve_by_embedding

            emb_results = retrieve_by_embedding(query, embedding_index, k=limit * 3)
            emb_scores = {doc_id: score for doc_id, score in emb_results}
        except Exception as exc:
            logger.warning("Embedding retrieval failed, falling back to BM25-only: %s", exc)

    if not emb_scores:
        # No embedding data available, use BM25 only
        results = []
        for doc_idx, score, matched_terms in bm25_results[:limit]:
            doc = documents[doc_idx]
            results.append(
                {
                    "doc_id": doc["doc_id"],
                    "path": doc["path"],
                    "title": doc["title"],
                    "type": doc["type"],
                    "topic": doc["topic"],
                    "snippet": _snippet(doc),
                    "score": round(score, 4),
                    "matched_terms": sorted(set(matched_terms)),
                    "source": "bm25",
                }
            )
        return results

    # Normalize and blend scores
    norm_bm25 = _normalize_scores(bm25_scores)
    norm_emb = _normalize_scores(emb_scores)

    # Collect all candidate doc_ids
    all_ids = set(bm25_scores) | set(emb_scores)
    emb_weight = 1.0 - bm25_weight

    doc_by_id: dict[str, dict] = {}
    for doc in documents:
        doc_by_id[doc["doc_id"]] = doc

    # Find matched terms from BM25
    matched_terms_map: dict[str, set[str]] = {}
    for doc_idx, _, matched in bm25_results:
        doc_id = documents[doc_idx]["doc_id"]
        matched_terms_map[doc_id] = matched

    blended: list[tuple[str, float]] = []
    for doc_id in all_ids:
        score = bm25_weight * norm_bm25.get(doc_id, 0.0) + emb_weight * norm_emb.get(doc_id, 0.0)
        blended.append((doc_id, score))

    blended.sort(key=lambda x: -x[1])

    results = []
    for doc_id, score in blended[:limit]:
        doc = doc_by_id.get(doc_id, {})
        results.append(
            {
                "doc_id": doc_id,
                "path": doc.get("path", ""),
                "title": doc.get("title", ""),
                "type": doc.get("type", ""),
                "topic": doc.get("topic", ""),
                "snippet": _snippet(doc),
                "score": round(score, 4),
                "matched_terms": sorted(set(matched_terms_map.get(doc_id, []))),
                "source": "hybrid",
            }
        )
    return results


from typing import Any

# Top-1/Top-2 score gap below this fraction of Top-1 signals an ambiguous
# query (several candidates nearly tied) — surfaced as `ambiguous` so a caller
# can opt into LLM rerank only when it helps, not on every clear-cut query.
AMBIGUOUS_RELATIVE_DIFF = 0.10


def _is_ambiguous(results: list[dict]) -> bool:
    if len(results) < 2:
        return False
    s1 = float(results[0].get("score", 0.0))
    s2 = float(results[1].get("score", 0.0))
    if s1 <= 0:
        return False
    return (s1 - s2) / s1 < AMBIGUOUS_RELATIVE_DIFF


def retrieve(query: str, index_path: Path, limit: int, *, rerank: bool = False, **kwargs) -> dict[str, Any]:
    """Main retrieval entry point — backward compatible with existing callers.

    When ``rerank=True``, fetches ``limit * 3`` candidates from BM25/hybrid and
    passes them through :func:`scholar_agent.engine.rerank.rerank` for LLM-based
    cross-encoder scoring. This adds one LLM call per candidate (~2s each) and
    is opt-in for callers that need high-quality top-1 ranking.
    """
    from scholar_agent.engine import metrics
    from scholar_agent.engine.synonyms import expand_query

    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("failed to read index %s: %s", index_path, exc)
        return {"query": query, "results": [], "error": f"Failed to read index: {exc}"}
    documents = payload.get("documents", [])

    embedding_index_path = kwargs.get("embedding_index_path")
    embedding_index = None
    if embedding_index_path and Path(embedding_index_path).exists():
        embedding_index = json.loads(Path(embedding_index_path).read_text(encoding="utf-8"))

    bm25_weight = kwargs.get("bm25_weight", 0.8)

    # When reranking, pull extra candidates so the reranker has material to prune.
    candidate_limit = limit * 3 if rerank else limit

    if embedding_index is not None:
        results = retrieve_hybrid(
            query, documents, embedding_index, bm25_weight, candidate_limit, index_path=index_path
        )
    else:
        results = retrieve_bm25(query, documents, candidate_limit, index_path=index_path)

    # Record retrieve call + whether synonym expansion fired.
    expansions = expand_query(query)
    metrics.record_retrieve_call(expansions_used=len(expansions) > 1)

    # Detect ambiguity from the pre-rerank ranking; rerank (if requested)
    # resolves it, so the flag only fires for callers that did NOT rerank.
    ambiguous = _is_ambiguous(results) and not rerank

    if rerank and len(results) > limit:
        try:
            from scholar_agent.engine.rerank import rerank as llm_rerank

            results = llm_rerank(query, results, top_k=limit)
        except Exception as exc:
            logger.warning("rerank failed, returning unranked candidates: %s", exc)

    # Annotate each result with the card's confidence so callers can weight
    # trust (reviewed/trusted outrank draft) without an extra file read.
    doc_confidence = {d.get("doc_id"): d.get("confidence", "draft") for d in documents}
    for r in results:
        r["confidence"] = doc_confidence.get(r.get("doc_id"), "draft")

    # Apply a capped popularity boost. With no usage recorded every boost is
    # 1.0 (no-op); with usage, frequently-surfaced cards edge up — but only on
    # the non-rerank path, since rerank already produced a high-quality order.
    try:
        from scholar_agent.engine import usage as _usage

        counts = _usage.load_usage()
        for r in results:
            r["usage_boost"] = round(_usage.usage_boost(r.get("doc_id", ""), counts), 3)
        if not rerank and counts:
            results.sort(key=lambda r: -(r.get("score", 0.0) * r.get("usage_boost", 1.0)))
    except Exception:
        pass
    return {"query": query, "results": results, "ambiguous": ambiguous}


def main() -> int:
    args = parse_args()
    kwargs = {}
    if args.embedding_index:
        kwargs["embedding_index_path"] = args.embedding_index
    kwargs["bm25_weight"] = args.bm25_weight

    payload = retrieve(args.query, args.index, args.limit, **kwargs)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
