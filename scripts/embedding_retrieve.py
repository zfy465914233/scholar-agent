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

import json
import math
import os
import sys
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

_DEFAULT_LOCAL_MODEL = "all-MiniLM-L6-v2"
_DEFAULT_API_MODEL = "text-embedding-3-small"


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
    except (HTTPError, URLError, OSError):
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
    """Compute embedding for a single query string."""
    result = embed_texts([query])
    return result[0] if result else []


# ── Similarity ─────────────────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── Index building ─────────────────────────────────────────────────

def build_embedding_index(documents: list[dict]) -> dict[str, Any]:
    """Compute embeddings for all documents and return an embedding index.

    Each document's ``search_text`` field is used as the embedding input.
    """
    texts = [str(doc.get("search_text", "")) for doc in documents]
    if not texts:
        return {"model": _get_model(), "backend": _get_backend(), "embeddings": [], "doc_ids": []}

    # Batch embed
    batch_size = 32
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        non_empty = [(j, t) for j, t in enumerate(batch) if t.strip()]
        if not non_empty:
            all_embeddings.extend([[] for _ in batch])
            continue
        indices, valid_texts = zip(*non_empty)
        batch_embeddings = embed_texts(list(valid_texts))
        result = [[] for _ in batch]
        for idx, emb in zip(indices, batch_embeddings):
            result[idx] = emb
        all_embeddings.extend(result)

    return {
        "model": _get_model(),
        "backend": _get_backend(),
        "doc_ids": [str(doc.get("doc_id", "")) for doc in documents],
        "embeddings": all_embeddings,
    }


# ── Retrieval ──────────────────────────────────────────────────────

def retrieve_by_embedding(
    query: str,
    embedding_index: dict[str, Any],
    k: int = 5,
) -> list[tuple[str, float]]:
    """Retrieve top-k documents by embedding similarity.

    Returns list of (doc_id, similarity_score).
    """
    # Prefer local embedding for query to match the index backend
    query_embedding = embed_query(query)
    if not query_embedding:
        return []

    doc_ids = embedding_index.get("doc_ids", [])
    embeddings = embedding_index.get("embeddings", [])

    scores: list[tuple[str, float]] = []
    for doc_id, doc_emb in zip(doc_ids, embeddings):
        if not doc_emb:
            continue
        sim = cosine_similarity(query_embedding, doc_emb)
        if sim > 0:
            scores.append((doc_id, sim))

    scores.sort(key=lambda x: -x[1])
    return scores[:k]


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
            print("No documents found in index.", file=sys.stderr)
            return 1

        emb_index = build_embedding_index(documents)
        valid = sum(1 for e in emb_index["embeddings"] if e)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(emb_index, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Embedded {valid}/{len(documents)} documents → {args.output}", file=sys.stderr)
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
