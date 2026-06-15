"""Retrieval quality benchmark: nDCG@3 and Recall@5 over a curated card set.

Run: pytest tests/test_retrieval_benchmark.py -v

The benchmark loads cards from tests/fixtures/benchmark_cards/, builds a local
index, runs the curated queries in tests/fixtures/retrieval_benchmark.json, and
asserts aggregate nDCG@3 / Recall@5 against baseline thresholds.

Marked with @pytest.mark.benchmark — included in the default suite, but you can
skip via `pytest -m "not benchmark"`.
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

import pytest

from scholar_agent.engine.local_index import build_index
from scholar_agent.engine.local_retrieve import retrieve

BENCHMARK_DIR = Path(__file__).parent / "fixtures" / "benchmark_cards"
BENCHMARK_JSON = Path(__file__).parent / "fixtures" / "retrieval_benchmark.json"


def ndcg_at_k(ranked_doc_ids: list[str], relevant: set[str], k: int = 3) -> float:
    """Discounted cumulative gain at k with binary relevance."""
    if not relevant:
        return 0.0
    dcg = 0.0
    for i, doc_id in enumerate(ranked_doc_ids[:k]):
        if doc_id in relevant:
            dcg += 1.0 / math.log2(i + 2)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg > 0 else 0.0


def recall_at_k(ranked_doc_ids: list[str], relevant: set[str], k: int = 5) -> float:
    if not relevant:
        return 0.0
    hits = sum(1 for doc_id in ranked_doc_ids[:k] if doc_id in relevant)
    return hits / len(relevant)


@pytest.fixture(scope="module")
def benchmark_index(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a local index over benchmark_cards/ once per module run.

    `extra_dirs=[]` disables `_extra_scan_dirs()` so the benchmark is hermetic
    and never picks up production paper-notes from outside the test fixtures.
    """
    index_path = tmp_path_factory.mktemp("bench_idx") / "index.json"
    payload = build_index(BENCHMARK_DIR, extra_dirs=[])
    index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return index_path


@pytest.fixture(scope="module")
def benchmark_cases() -> list[dict]:
    data = json.loads(BENCHMARK_JSON.read_text(encoding="utf-8"))
    return data["queries"]


@pytest.mark.benchmark
def test_retrieval_quality(benchmark_index: Path, benchmark_cases: list[dict]) -> None:
    """Aggregate retrieval quality over the benchmark."""
    ndcgs: list[float] = []
    recalls: list[float] = []
    per_query: list[dict] = []

    for case in benchmark_cases:
        payload = retrieve(case["query"], benchmark_index, limit=5)
        ranked = [r["doc_id"] for r in payload.get("results", [])]
        relevant = set(case["relevant_doc_ids"])
        ndcg = ndcg_at_k(ranked, relevant, k=3)
        recall = recall_at_k(ranked, relevant, k=5)
        ndcgs.append(ndcg)
        recalls.append(recall)
        per_query.append(
            {
                "query": case["query"],
                "category": case.get("category", "?"),
                "ndcg@3": round(ndcg, 3),
                "recall@5": round(recall, 3),
                "top3": ranked[:3],
                "expected": case["relevant_doc_ids"],
            }
        )

    mean_ndcg = statistics.mean(ndcgs)
    mean_recall = statistics.mean(recalls)

    # Per-category breakdown for diagnostic visibility
    by_cat: dict[str, list[float]] = {}
    for entry in per_query:
        by_cat.setdefault(entry["category"], []).append(entry["ndcg@3"])

    print("\n=== Retrieval Benchmark ===")
    for entry in per_query:
        print(
            f"  [{entry['category']:9s}] nDCG={entry['ndcg@3']:.3f}  R={entry['recall@5']:.3f}  "
            f"top={entry['top3']}  expect={entry['expected']}  q={entry['query'][:50]}"
        )
    print(f"\n  Mean nDCG@3 = {mean_ndcg:.3f}")
    print(f"  Mean Recall@5 = {mean_recall:.3f}")
    for cat, vals in sorted(by_cat.items()):
        print(f"  nDCG@3 [{cat}] = {statistics.mean(vals):.3f}  (n={len(vals)})")
    print("=== End Benchmark ===\n")

    # Thresholds set just below the observed baseline (nDCG@3 ≈ 0.91, Recall@5 ≈ 0.92)
    # to catch regressions. Tier 1/2/3 should raise these, not lower.
    assert mean_ndcg >= 0.85, f"mean nDCG@3 regressed below threshold: {mean_ndcg:.3f}"
    assert mean_recall >= 0.85, f"mean Recall@5 regressed below threshold: {mean_recall:.3f}"


@pytest.mark.benchmark
def test_benchmark_corpus_loads() -> None:
    """Smoke test: every relevant_doc_id referenced must exist in the corpus."""
    cards = {p.stem for p in BENCHMARK_DIR.glob("*.md")}
    data = json.loads(BENCHMARK_JSON.read_text(encoding="utf-8"))
    missing: list[str] = []
    for case in data["queries"]:
        for doc_id in case["relevant_doc_ids"]:
            if doc_id not in cards:
                missing.append(f"{doc_id} (in query: {case['query']})")
    assert not missing, f"benchmark references non-existent cards: {missing}"
