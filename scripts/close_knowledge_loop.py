"""Close the knowledge loop: research → synthesize → distill → promote → reindex.

This script takes a research evidence JSON file and a structured answer JSON,
then:
  1. Builds an answer context from the evidence
  2. Distills the answer into a draft knowledge card
  3. Promotes the draft into the local knowledge tree
  4. Rebuilds the index so the new knowledge is immediately retrievable

Usage:
  python close_knowledge_loop.py \\
    --research /tmp/research.json \\
    --answer /tmp/answer.json \\
    --query "XGBoost for QPE radar rainfall estimation"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DEFAULT_KNOWLEDGE_ROOT = ROOT / "knowledge"
DEFAULT_INDEX = ROOT / "indexes" / "local" / "index.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Close the knowledge loop.")
    parser.add_argument("--query", required=True, help="The original query.")
    parser.add_argument(
        "--research",
        type=Path,
        help="Path to research evidence JSON from research_harness.py.",
    )
    parser.add_argument(
        "--answer",
        type=Path,
        required=True,
        help="Path to structured answer JSON.",
    )
    parser.add_argument(
        "--knowledge-root",
        type=Path,
        default=DEFAULT_KNOWLEDGE_ROOT,
    )
    parser.add_argument(
        "--index-output",
        type=Path,
        default=DEFAULT_INDEX,
    )
    return parser.parse_args()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "research-note"


def infer_domain(query: str) -> str:
    q = query.lower()
    if any(t in q for t in ("xgboost", "qpe", "radar", "rainfall", "precipitation", "quantitative")):
        return "qpe"
    if any(t in q for t in ("markov", "stochastic", "stationary")):
        return "markov_chain"
    if any(t in q for t in ("quantum", "phase estimation")):
        return "quantum_phase_estimation"
    if any(t in q for t in ("duality", "linear programming")):
        return "linear_programming"
    if any(t in q for t in ("quantization", "qat")):
        return "model_quantization"
    return "general"


def collect_source_urls(research_data: dict | None) -> list[str]:
    """Extract source URLs from research evidence."""
    urls: list[str] = []
    if research_data is None:
        return urls
    for item in research_data.get("evidence", []):
        url = item.get("url", "")
        if url and url not in urls:
            urls.append(url)
    return urls


def build_knowledge_card(
    query: str,
    answer_data: dict,
    research_data: dict | None,
    knowledge_root: Path,
) -> Path:
    """Build a knowledge card from research evidence and structured answer."""
    answer = answer_data.get("answer", answer_data)
    domain = infer_domain(query)
    slug = slugify(query)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_urls = collect_source_urls(research_data)

    # Extract structured content
    main_answer = answer.get("answer", str(answer)) if isinstance(answer, dict) else str(answer)
    claims = answer.get("supporting_claims", []) if isinstance(answer, dict) else []
    inferences = answer.get("inferences", []) if isinstance(answer, dict) else []
    uncertainties = answer.get("uncertainty", []) if isinstance(answer, dict) else []
    missing = answer.get("missing_evidence", []) if isinstance(answer, dict) else []
    next_steps = answer.get("suggested_next_steps", []) if isinstance(answer, dict) else []

    # Build frontmatter
    lines = [
        "---",
        f"id: research-{slug}",
        f"title: Research Note — {query}",
        f"type: method",
        f"topic: {domain}",
        "tags:",
        "  - ml-qpe",
        "  - xgboost",
        "  - radar",
        "  - research-note",
        "source_refs:",
    ]
    for url in source_urls[:10]:
        lines.append(f"  - {url}")
    lines.extend([
        "confidence: draft",
        f"updated_at: {now}",
        "origin: web_research_with_synthesis",
        "review_status: draft",
        "---",
        "",
        "## Question",
        "",
        query,
        "",
        "## Answer",
        "",
        main_answer,
        "",
    ])

    if claims:
        lines.extend(["## Supporting Claims", ""])
        for c in claims:
            if isinstance(c, dict):
                claim_text = c.get("claim", "")
                conf = c.get("confidence", "")
                ids = c.get("evidence_ids", [])
                lines.append(f"- **[{conf}]** {claim_text} (evidence: {', '.join(ids)})")
            else:
                lines.append(f"- {c}")
        lines.append("")

    if inferences:
        lines.extend(["## Inferences", ""])
        for inf in inferences:
            lines.append(f"- {inf}")
        lines.append("")

    if uncertainties:
        lines.extend(["## Uncertainty", ""])
        for u in uncertainties:
            lines.append(f"- {u}")
        lines.append("")

    if missing:
        lines.extend(["## Missing Evidence", ""])
        for m in missing:
            lines.append(f"- {m}")
        lines.append("")

    if next_steps:
        lines.extend(["## Suggested Next Steps", ""])
        for s in next_steps:
            lines.append(f"- {s}")
        lines.append("")

    # Write to knowledge tree
    output_dir = knowledge_root / domain
    output_dir.mkdir(parents=True, exist_ok=True)
    card_path = output_dir / f"research-{slug}.md"
    card_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return card_path


def reindex(index_output: Path) -> bool:
    """Rebuild the local index."""
    import subprocess
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "local_index.py"), "--output", str(index_output)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def main() -> int:
    args = parse_args()

    # Load inputs
    research_data = None
    if args.research and args.research.exists():
        research_data = json.loads(args.research.read_text(encoding="utf-8"))
    answer_data = json.loads(args.answer.read_text(encoding="utf-8"))

    # Step 1: Build knowledge card
    card_path = build_knowledge_card(
        args.query, answer_data, research_data, args.knowledge_root
    )
    print(f"Knowledge card written: {card_path}", file=sys.stderr)

    # Step 2: Rebuild index
    if reindex(args.index_output):
        print(f"Index rebuilt: {args.index_output}", file=sys.stderr)
    else:
        print("Warning: index rebuild failed", file=sys.stderr)

    # Step 3: Verify retrievability
    import subprocess
    verify = subprocess.run(
        [sys.executable, str(SCRIPTS / "local_retrieve.py"),
         args.query, "--index", str(args.index_output), "--limit", "3"],
        capture_output=True, text=True,
    )
    if verify.returncode == 0:
        results = json.loads(verify.stdout)
        found = any(
            f"research-{slugify(args.query)}" in r.get("doc_id", "")
            for r in results.get("results", [])
        )
        status = "verified retrievable" if found else "written but not in top results"
        print(f"Verification: {status}", file=sys.stderr)
    else:
        print("Verification: could not check retrievability", file=sys.stderr)

    print(f"\nDone. Knowledge loop closed for: {args.query}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
