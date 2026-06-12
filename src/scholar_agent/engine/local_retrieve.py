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

from scholar_agent.engine.bm25 import BM25

logger = logging.getLogger(__name__)

DEFAULT_INDEX = Path("indexes/local/index.json")

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
        default=0.6,
        help="Weight for BM25 scores in hybrid ranking (0-1). Default: 0.6",
    )
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of results to return.")
    return parser.parse_args()


def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    """Normalize scores to [0, 1] range."""
    if not scores:
        return {}
    min_s = min(scores.values())
    max_s = max(scores.values())
    rng = max_s - min_s
    if rng == 0:
        return {k: 1.0 for k in scores}
    return {k: (v - min_s) / rng for k, v in scores.items()}


def retrieve_bm25(query: str, documents: list[dict], limit: int, index_path: Path | None = None) -> list[dict]:
    """BM25-only retrieval."""
    bm25 = _get_bm25(documents, index_path) if index_path is not None else BM25(documents)
    results = []
    for doc_idx, score, matched_terms in bm25.top_k(query, limit):
        doc = documents[doc_idx]
        results.append(
            {
                "doc_id": doc.get("doc_id", ""),
                "path": doc.get("path", ""),
                "title": doc.get("title", ""),
                "type": doc.get("type", ""),
                "topic": doc.get("topic", ""),
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
    """Hybrid retrieval: BM25 + embedding reranking."""
    bm25 = _get_bm25(documents, index_path) if index_path is not None else BM25(documents)
    bm25_results = bm25.top_k(query, limit * 3)  # fetch more candidates for reranking

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
    matched_terms_map: dict[str, list[str]] = {}
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
                "score": round(score, 4),
                "matched_terms": sorted(set(matched_terms_map.get(doc_id, []))),
                "source": "hybrid",
            }
        )
    return results


from typing import Any


def retrieve(query: str, index_path: Path, limit: int, **kwargs) -> dict[str, Any]:
    """Main retrieval entry point — backward compatible with existing callers."""
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

    bm25_weight = kwargs.get("bm25_weight", 0.6)

    if embedding_index is not None:
        results = retrieve_hybrid(query, documents, embedding_index, bm25_weight, limit, index_path=index_path)
    else:
        results = retrieve_bm25(query, documents, limit, index_path=index_path)

    return {"query": query, "results": results}


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
