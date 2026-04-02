"""Evaluation runner for the domain agent system.

Runs a set of benchmark queries through the pipeline and produces a structured
report covering route accuracy, retrieval quality, and answer completeness.

Usage:
  python run_eval.py                    # run all benchmark queries
  python run_eval.py --dry-run          # dry-run mode (no LLM calls)
  python run_eval.py --category local   # run only local-led queries

The benchmark cases are defined inline. To add new cases, extend BENCHMARK_CASES.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Import run_pipeline (scripts dir is on sys.path when run as script)
from run_pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "indexes" / "local" / "index.json"
FAKE_HARNESS = ROOT / "tests" / "fake_research_harness.py"


@dataclass
class BenchmarkCase:
    query: str
    category: str
    expected_route: str
    expected_top_evidence_ids: list[str] = field(default_factory=list)
    min_citations: int = 0


BENCHMARK_CASES: list[BenchmarkCase] = [
    # --- Definition queries (local-led) ---
    BenchmarkCase(
        query="What is a Markov chain?",
        category="definition",
        expected_route="local-led",
        expected_top_evidence_ids=["example-markov-chain-definition"],
        min_citations=1,
    ),
    BenchmarkCase(
        query="Define Markov property and stochastic process",
        category="definition",
        expected_route="local-led",
        expected_top_evidence_ids=["example-markov-chain-definition"],
        min_citations=1,
    ),
    BenchmarkCase(
        query="What is the transition matrix in a Markov chain?",
        category="definition",
        expected_route="local-led",
        expected_top_evidence_ids=["example-markov-chain-definition"],
        min_citations=1,
    ),
    # --- Derivation queries (local-led) ---
    BenchmarkCase(
        query="How do you compute the stationary distribution of a Markov chain?",
        category="derivation",
        expected_route="mixed",
        expected_top_evidence_ids=["example-markov-chain-definition"],
        min_citations=1,
    ),
    BenchmarkCase(
        query="Explain the Chapman-Kolmogorov equation for Markov chains",
        category="derivation",
        expected_route="mixed",
        expected_top_evidence_ids=["example-markov-chain-definition"],
        min_citations=1,
    ),
    # --- Freshness queries (web-led) ---
    BenchmarkCase(
        query="What are the latest SOTA methods for sequence modeling in 2026?",
        category="freshness",
        expected_route="web-led",
        expected_top_evidence_ids=[],
        min_citations=0,
    ),
    BenchmarkCase(
        query="What is the newest approach to knowledge distillation?",
        category="freshness",
        expected_route="web-led",
        expected_top_evidence_ids=[],
        min_citations=0,
    ),
    # --- Comparison queries (mixed) ---
    BenchmarkCase(
        query="Compare Markov chains with hidden Markov models",
        category="comparison",
        expected_route="mixed",
        expected_top_evidence_ids=["example-markov-chain-definition"],
        min_citations=0,
    ),
]


def evaluate_case(case: BenchmarkCase, dry_run: bool = False) -> dict:
    """Run a single benchmark case through the pipeline and score it."""
    try:
        output = run_pipeline(
            query=case.query,
            mode="auto",
            index=DEFAULT_INDEX,
            research_script=FAKE_HARNESS,
            dry_run=dry_run,
        )
    except RuntimeError as exc:
        return {
            "query": case.query,
            "category": case.category,
            "status": "error",
            "error": str(exc),
            "scores": {"route_correct": False, "retrieval_hit": False, "min_citations_met": False},
        }

    route = output.get("route", "")
    route_correct = route == case.expected_route

    # Check retrieval: do any expected evidence IDs appear in citations?
    citations = output.get("citations", [])
    citation_ids = {c.get("evidence_id") for c in citations}
    retrieval_hit = (
        not case.expected_top_evidence_ids
        or bool(citation_ids & set(case.expected_top_evidence_ids))
    )

    min_citations_met = len(citations) >= case.min_citations

    # For dry-run, we can't evaluate answer quality
    answer_present = "answer" in output and isinstance(output.get("answer"), dict)

    return {
        "query": case.query,
        "category": case.category,
        "status": output.get("pipeline_status", "unknown"),
        "route": route,
        "scores": {
            "route_correct": route_correct,
            "retrieval_hit": retrieval_hit,
            "min_citations_met": min_citations_met,
            "answer_present": answer_present,
        },
        "details": {
            "expected_route": case.expected_route,
            "expected_evidence_ids": case.expected_top_evidence_ids,
            "citation_count": len(citations),
            "citation_ids": sorted(citation_ids),
        },
    }


def run_evaluation(cases: list[BenchmarkCase], dry_run: bool = False) -> dict:
    """Run all benchmark cases and produce a summary report."""
    results = []
    for case in cases:
        result = evaluate_case(case, dry_run=dry_run)
        results.append(result)

    # Aggregate scores
    total = len(results)
    route_correct = sum(1 for r in results if r["scores"]["route_correct"])
    retrieval_hit = sum(1 for r in results if r["scores"]["retrieval_hit"])
    min_citations_met = sum(1 for r in results if r["scores"]["min_citations_met"])
    answer_present = sum(1 for r in results if r["scores"]["answer_present"])
    errors = sum(1 for r in results if r["status"] == "error")

    # Per-category breakdown
    categories: dict[str, dict] = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"total": 0, "route_correct": 0, "retrieval_hit": 0}
        categories[cat]["total"] += 1
        if r["scores"]["route_correct"]:
            categories[cat]["route_correct"] += 1
        if r["scores"]["retrieval_hit"]:
            categories[cat]["retrieval_hit"] += 1

    return {
        "summary": {
            "total_cases": total,
            "route_accuracy": route_correct / total if total else 0,
            "retrieval_hit_rate": retrieval_hit / total if total else 0,
            "min_citations_rate": min_citations_met / total if total else 0,
            "answer_present_rate": answer_present / total if total else 0,
            "errors": errors,
            "dry_run": dry_run,
        },
        "by_category": categories,
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run benchmark evaluation for the domain agent.")
    parser.add_argument(
        "--category",
        help="Run only cases matching this category (e.g. definition, derivation).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run mode: skip LLM calls.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON report to file instead of stdout.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Ensure index exists
    import subprocess

    if not DEFAULT_INDEX.exists():
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "local_index.py"), "--output", str(DEFAULT_INDEX)],
            check=True,
            capture_output=True,
        )

    cases = BENCHMARK_CASES
    if args.category:
        cases = [c for c in cases if c.category == args.category]
        if not cases:
            print(f"No cases found for category '{args.category}'.", file=sys.stderr)
            return 1

    report = run_evaluation(cases, dry_run=args.dry_run)
    text = json.dumps(report, ensure_ascii=False, indent=2)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
