"""Embedding-based retrieval for local knowledge.

Supports two backends (auto-detected in priority order):
  1. sentence-transformers local model (preferred, zero API dependency)
  2. OpenAI-compatible embeddings API (fallback)

Backend selection:
  - If sentence-transformers is installed, uses local model by default.
  - Set EMBEDDING_BACKEND=api to force API backend.
  - If neither is available, all functions return empty results gracefully.

Configuration (environment variables):
  EMBEDDING_BACKEND  – "local" or "api". Default: auto-detect
  EMBEDDING_MODEL    – model name. Default: all-MiniLM-L6-v2 (local) or text-embedding-3-small (api)
  LLM_API_URL       – base URL for API backend. Default: https://api.openai.com/v1
  LLM_API_KEY       – API key for API backend.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ── Backend detection ──────────────────────────────────────────────

_LOCAL_MODEL_AVAILABLE = False
try:
    from sentence_transformers import SentenceTransformer

    _LOCAL_MODEL_AVAILABLE = True
except ImportError:
    pass

# numpy ships with sentence-transformers; vectorise cosine scoring when present
# and fall back to a pure-Python loop otherwise. Both paths are parity-tested.
try:
    import numpy as _np

    _HAS_NUMPY = True
except ImportError:  # pragma: no cover - numpy is a transitive dep
    _HAS_NUMPY = False

_DEFAULT_LOCAL_MODEL = "all-MiniLM-L6-v2"
_DEFAULT_API_MODEL = "text-embedding-3-small"

logger = logging.getLogger(__name__)


def _get_backend() -> str:
    explicit = os.environ.get("EMBEDDING_BACKEND", "").lower()
    if explicit == "api":
        return "api"
    if explicit == "local":
        return "local"
    # Auto-detect: prefer local if available
    return "local" if _LOCAL_MODEL_AVAILABLE else "api"


def _get_model() -> str:
    return os.environ.get("EMBEDDING_MODEL", _DEFAULT_LOCAL_MODEL if _get_backend() == "local" else _DEFAULT_API_MODEL)


# ── Local model cache (singleton) ──────────────────────────────────

_local_model: Any = None


def _get_local_model() -> Any:
    global _local_model
    if _local_model is None and _LOCAL_MODEL_AVAILABLE:
        _local_model = SentenceTransformer(_get_model())
    return _local_model


# ── Query embedding cache ──────────────────────────────────────────

# Plain dict keyed on query text; insertion order gives us LRU eviction for
# free. We avoid functools.lru_cache here because embed_query can return []
# on backend failure and we want to retry rather than cache the miss.
_query_cache: dict[str, list[float]] = {}
_QUERY_CACHE_MAX = 128


# ── Core embedding functions ───────────────────────────────────────


def _embed_local(texts: list[str]) -> list[list[float]]:
    """Embed texts using local sentence-transformers model."""
    model = _get_local_model()
    if model is None:
        return []
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return [emb.tolist() for emb in embeddings]


def _embed_api(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Embed texts using OpenAI-compatible API."""
    api_url = os.environ.get("LLM_API_URL", "https://api.openai.com/v1")
    api_key = os.environ.get("LLM_API_KEY", "")
    model_name = model or _get_model()
    timeout = int(os.environ.get("EMBEDDING_TIMEOUT", "30"))

    url = api_url.rstrip("/") + "/embeddings"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = json.dumps({"model": model_name, "input": texts}).encode("utf-8")
    req = Request(url, data=body, headers=headers, method="POST")

    try:
        with urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError) as exc:
        logger.warning("embedding API call failed: %s", exc)
        return []

    embeddings = []
    for item in sorted(data.get("data", []), key=lambda x: x.get("index", 0)):
        embeddings.append(item["embedding"])
    return embeddings


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using the best available backend.

    Returns list of embedding vectors. Empty list if no backend available.
    """
    if not texts:
        return []

    backend = _get_backend()
    if backend == "local" and _LOCAL_MODEL_AVAILABLE:
        return _embed_local(texts)
    if backend == "api":
        return _embed_api(texts)
    return []


def embed_query(query: str) -> list[float]:
    """Compute embedding for a single query string.

    Results are LRU-cached (size 128) keyed on the query text — repeated
    identical queries skip the underlying ``embed_texts`` call. Clear with
    :func:`clear_embed_cache` (e.g. when the embedding backend changes).
    """
    cached = _query_cache.get(query)
    if cached is not None:
        return cached
    result = embed_texts([query])
    embedding = result[0] if result else []
    # Only cache successful embeddings — failures should retry on next call.
    if embedding:
        if len(_query_cache) >= _QUERY_CACHE_MAX:
            # Drop oldest entry (Python 3.7+ dict preserves insertion order)
            _query_cache.pop(next(iter(_query_cache)))
        _query_cache[query] = embedding
    return embedding


def clear_embed_cache() -> None:
    """Invalidate the query embedding cache."""
    _query_cache.clear()


# ── Similarity ─────────────────────────────────────────────────────


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── Index building ─────────────────────────────────────────────────


def _text_hash(text: str) -> str:
    """Short sha256 of a document's search_text for change detection."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_embedding_index(documents: list[dict], existing_index: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute embeddings for all documents and return an embedding index.

    Each document's ``search_text`` is the embedding input. When
    *existing_index* (a prior index from this function) is supplied,
    embeddings for documents whose ``search_text`` is unchanged (sha256 match)
    are reused — only new or modified documents are re-embedded, so periodic
    reindex stays cheap as the corpus grows. The index carries a
    ``text_hashes`` map for the next call; the field is additive, so older
    readers that only know ``doc_ids`` / ``embeddings`` are unaffected.
    """
    doc_ids = [str(doc.get("doc_id", "")) for doc in documents]
    texts = [str(doc.get("search_text", "")) for doc in documents]
    hashes = [_text_hash(t) for t in texts]

    if not documents:
        return {
            "model": _get_model(),
            "backend": _get_backend(),
            "embeddings": [],
            "doc_ids": [],
            "text_hashes": {},
        }

    prev_emb: dict[str, list[float]] = {}
    prev_hash: dict[str, str] = {}
    if existing_index:
        prev_hash = dict(existing_index.get("text_hashes") or {})
        prev_ids = existing_index.get("doc_ids", [])
        prev_embs = existing_index.get("embeddings", [])
        prev_emb = {d: e for d, e in zip(prev_ids, prev_embs, strict=False) if e}

    # Per document: reuse if unchanged, else queue for (re-)embedding.
    embed_positions: list[int] = []
    to_embed_texts: list[str] = []
    for pos, (doc_id, text, h) in enumerate(zip(doc_ids, texts, hashes, strict=True)):
        if doc_id in prev_emb and prev_hash.get(doc_id) == h:
            continue
        if text.strip():
            embed_positions.append(pos)
            to_embed_texts.append(text)

    new_embeddings: dict[int, list[float]] = {}
    batch_size = 32
    for i in range(0, len(to_embed_texts), batch_size):
        batch_embeddings = embed_texts(to_embed_texts[i : i + batch_size])
        for j, emb in enumerate(batch_embeddings):
            new_embeddings[embed_positions[i + j]] = emb

    all_embeddings: list[list[float]] = []
    for pos, (doc_id, _text, h) in enumerate(zip(doc_ids, texts, hashes, strict=True)):
        hit: list[float] | None = new_embeddings.get(pos)
        if hit:
            all_embeddings.append(hit)
        elif doc_id in prev_emb and prev_hash.get(doc_id) == h:
            all_embeddings.append(prev_emb[doc_id])
        else:
            all_embeddings.append([])

    return {
        "model": _get_model(),
        "backend": _get_backend(),
        "doc_ids": doc_ids,
        "embeddings": all_embeddings,
        "text_hashes": dict(zip(doc_ids, hashes, strict=True)),
    }


# ── Retrieval ──────────────────────────────────────────────────────


def _cosine_topk(
    query_vec: list[float],
    doc_vecs: list[list[float]],
    doc_ids: list[str],
    k: int,
) -> list[tuple[str, float]]:
    """Top-k cosine similarities, descending, positive-only.

    Vectorised with numpy when available — one matrix-vector product over the
    whole document matrix instead of an $O(N \\cdot d)$ Python loop. Falls
    back to a per-document loop otherwise. Both paths return identical
    results (covered by the parity test).
    """
    if not doc_ids:
        return []

    if _HAS_NUMPY:
        q = _np.asarray(query_vec, dtype=_np.float64)
        D = _np.asarray(doc_vecs, dtype=_np.float64)
        if D.ndim != 2 or D.shape[0] == 0:
            return []
        q_norm = _np.linalg.norm(q)
        d_norms = _np.linalg.norm(D, axis=1)
        denom = d_norms * q_norm
        sims = _np.zeros(D.shape[0], dtype=_np.float64)
        nonzero = denom > 0
        if nonzero.any():
            sims[nonzero] = (D[nonzero] @ q) / denom[nonzero]
        positive = _np.where(sims > 0)[0]
        if positive.size == 0:
            return []
        order = _np.argsort(sims[positive])[::-1][: min(k, positive.size)]
        selected = positive[order]
        return [(doc_ids[i], float(sims[i])) for i in selected]

    scores: list[tuple[str, float]] = []
    for doc_id, emb in zip(doc_ids, doc_vecs, strict=False):
        sim = cosine_similarity(query_vec, emb)
        if sim > 0:
            scores.append((doc_id, sim))
    scores.sort(key=lambda x: -x[1])
    return scores[:k]


def retrieve_by_embedding(
    query: str,
    embedding_index: dict[str, Any],
    k: int = 5,
) -> list[tuple[str, float]]:
    """Retrieve top-k documents by embedding similarity.

    Returns list of (doc_id, similarity_score), descending, positive-only.
    """
    query_embedding = embed_query(query)
    if not query_embedding:
        return []

    doc_ids = embedding_index.get("doc_ids", [])
    embeddings = embedding_index.get("embeddings", [])
    # Pair ids with embeddings, dropping docs that have no embedding (e.g.
    # backend failure during index build) so the two lists stay aligned.
    pairs = [(did, emb) for did, emb in zip(doc_ids, embeddings, strict=False) if emb]
    if not pairs:
        return []

    valid_ids = [p[0] for p in pairs]
    valid_vecs = [p[1] for p in pairs]
    return _cosine_topk(query_embedding, valid_vecs, valid_ids, k)


# ── CLI ────────────────────────────────────────────────────────────


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build or test embedding index.")
    sub = parser.add_subparsers(dest="command")

    build = sub.add_parser("build", help="Build embedding index from local index.")
    build.add_argument("--index", type=Path, default=Path("indexes/local/index.json"))
    build.add_argument("--output", type=Path, default=Path("indexes/local/embeddings.json"))

    search = sub.add_parser("search", help="Search using embedding index.")
    search.add_argument("query")
    search.add_argument("--embedding-index", type=Path, default=Path("indexes/local/embeddings.json"))
    search.add_argument("--limit", type=int, default=5)

    args = parser.parse_args()

    if args.command == "build":
        payload = json.loads(args.index.read_text(encoding="utf-8"))
        documents = payload.get("documents", [])
        if not documents:
            logger.info("No documents found in index.")
            return 1

        emb_index = build_embedding_index(documents)
        valid = sum(1 for e in emb_index["embeddings"] if e)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(emb_index, ensure_ascii=False) + "\n", encoding="utf-8")
        logger.info("Embedded %d/%d documents → %s", valid, len(documents), args.output)
        return 0

    if args.command == "search":
        emb_index = json.loads(args.embedding_index.read_text(encoding="utf-8"))
        results = retrieve_by_embedding(args.query, emb_index, args.limit)
        for doc_id, score in results:
            print(f"{score:.4f}  {doc_id}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
