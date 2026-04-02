"""Build a structured answer context from the orchestrated evidence pack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orchestrate_research import build_decision, classify_route, generate_web_evidence
from build_evidence_pack import build_evidence_pack


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a structured answer context with citations.")
    parser.add_argument("query", help="User query")
    parser.add_argument(
        "--mode",
        choices=("auto", "local-led", "web-led", "mixed", "context-led"),
        default="auto",
        help="Routing mode. 'auto' uses heuristic classification.",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("indexes/local/index.json"),
        help="Path to the local retrieval index.",
    )
    parser.add_argument(
        "--web-evidence",
        type=Path,
        help="Optional path to a web evidence JSON bundle.",
    )
    parser.add_argument(
        "--research-script",
        type=Path,
        default=Path("scripts/research_harness.py"),
        help="Script used to generate web evidence when needed.",
    )
    parser.add_argument("--local-limit", type=int, default=5, help="Maximum local evidence items.")
    return parser.parse_args()


def summarize_item(item: dict[str, object]) -> str:
    title = str(item.get("title") or "")
    source_type = str(item.get("source_type") or "")
    if item.get("origin") == "local":
        return f"Local {source_type} card: {title}"
    return f"Web {source_type} source: {title}"


def build_answer_context(query: str, route: str, evidence_pack: dict[str, object], warnings: list[str]) -> dict[str, object]:
    items = evidence_pack.get("items", [])
    direct_support = []
    citations = []

    for item in items:
        citation = {
            "evidence_id": item["evidence_id"],
            "origin": item["origin"],
            "title": item["title"],
            "source_type": item["source_type"],
        }
        if item.get("path") is not None:
            citation["path"] = item["path"]
        if item.get("url") is not None:
            citation["url"] = item["url"]
        citations.append(citation)

        direct_support.append(
            {
                "evidence_id": item["evidence_id"],
                "origin": item["origin"],
                "support": summarize_item(item),
            }
        )

    inference_notes = [f"Route selected: {route}."]
    if direct_support:
        inference_notes.append(
            "Use direct_support items for grounded claims and reserve freeform reasoning for synthesis."
        )
    else:
        inference_notes.append(
            "Direct support is limited for this query, so any answer should stay narrow and explicitly tentative."
        )

    uncertainty_notes = list(warnings)
    if evidence_pack.get("web_count", 0):
        uncertainty_notes.append("Web evidence is present and may require freshness or source-quality review.")
    else:
        uncertainty_notes.append("No web evidence is present in the current answer context.")
    if not direct_support:
        uncertainty_notes.append("No direct evidence was found in the current context.")

    return {
        "query": query,
        "route": route,
        "direct_support": direct_support,
        "inference_notes": inference_notes,
        "uncertainty_notes": uncertainty_notes,
        "citations": citations,
    }


def main() -> int:
    args = parse_args()
    route = classify_route(args.query) if args.mode == "auto" else args.mode

    warnings: list[str] = []
    generated_web_path: Path | None = None
    if route in {"web-led", "mixed"} and args.web_evidence is None:
        generated_web_path, warning = generate_web_evidence(args.query, args.research_script)
        if warning:
            warnings.append(warning)

    include_web = args.web_evidence or generated_web_path if route in {"web-led", "mixed"} else None
    evidence_pack = build_evidence_pack(args.query, args.index, include_web, args.local_limit)
    _ = build_decision(route, has_web_evidence=include_web is not None)
    payload = build_answer_context(args.query, route, evidence_pack, warnings)
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if generated_web_path is not None:
        generated_web_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
