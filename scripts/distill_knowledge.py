"""Distill a structured answer context into a reusable Markdown draft."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Distill an answer context into a Markdown knowledge draft.")
    parser.add_argument(
        "--answer-context",
        type=Path,
        required=True,
        help="Path to the answer-context JSON produced by build_answer_context.py",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination Markdown path for the distilled draft.",
    )
    return parser.parse_args()


def slugify(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return normalized or "distilled-note"


def build_markdown(payload: dict[str, object]) -> str:
    query = str(payload.get("query", "")).strip()
    route = str(payload.get("route", "")).strip()
    direct_support = payload.get("direct_support", [])
    inference_notes = payload.get("inference_notes", [])
    uncertainty_notes = payload.get("uncertainty_notes", [])
    citations = payload.get("citations", [])

    lines = [
        "---",
        f"id: distilled-{slugify(query)}",
        f"title: Distilled Note - {query}",
        "type: distilled_note",
        "topic: research_distillation",
        "tags:",
        "  - distilled",
        "  - answer-context",
        "source_refs:",
        "  - answer_context",
        "confidence: draft",
        "updated_at: 2026-04-01",
        "origin: generated_from_answer_context",
        "---",
        "",
        "## Query",
        "",
        query,
        "",
        "## Route",
        "",
        route,
        "",
        "## Direct Support",
        "",
    ]

    for item in direct_support:
        lines.append(f"- `{item['evidence_id']}`: {item['support']}")

    lines.extend(["", "## Inference Notes", ""])
    for note in inference_notes:
        lines.append(f"- {note}")

    lines.extend(["", "## Uncertainty Notes", ""])
    for note in uncertainty_notes:
        lines.append(f"- {note}")

    lines.extend(["", "## Citations", ""])
    for citation in citations:
        source = citation.get("path") or citation.get("url") or ""
        lines.append(
            f"- `{citation['evidence_id']}` ({citation['origin']} / {citation['source_type']}): "
            f"{citation['title']} | {source}"
        )

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    payload = json.loads(args.answer_context.read_text(encoding="utf-8"))
    markdown = build_markdown(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
