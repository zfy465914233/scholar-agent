"""Promote a distilled Markdown draft into a structured card candidate."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from scholar_agent.engine.common import safe_slug
from scholar_agent.engine.domain_router import infer_domain as _infer_domain


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote a distilled note into a local card candidate.")
    parser.add_argument("--draft", type=Path, required=True, help="Path to the distilled Markdown draft.")
    parser.add_argument(
        "--knowledge-root",
        type=Path,
        default=Path("knowledge"),
        help="Root knowledge directory where promoted candidates should be written.",
    )
    return parser.parse_args()


def extract_section(text: str, heading: str) -> list[str]:
    marker = f"## {heading}\n"
    if marker not in text:
        return []
    tail = text.split(marker, 1)[1]
    next_heading = tail.find("\n## ")
    section = tail if next_heading == -1 else tail[:next_heading]
    return [line.rstrip() for line in section.strip().splitlines()]


def parse_query(text: str) -> str:
    lines = extract_section(text, "Query")
    return lines[0].strip() if lines else "untitled query"


def infer_card_type(query: str) -> str:
    """Infer card type from query. Returns 'method' if procedural, else 'knowledge'."""
    normalized = query.lower().strip()
    procedural_keywords = (
        "how to ",
        "implement",
        "deploy",
        "train",
        "build",
        "configure",
        "setup",
        "install",
        "run ",
        "optimize",
        "tune ",
        "debug",
        "fix ",
        "procedure",
        "algorithm",
    )
    if any(kw in normalized for kw in procedural_keywords):
        return "method"
    return "knowledge"


def infer_domain_folder(query: str, knowledge_root: Path, draft_text: str = "") -> str:
    """Infer domain folder using dynamic matching."""
    summary = draft_text[:500] if draft_text else ""
    slug, _path = _infer_domain(query, knowledge_root, card_title=query, card_summary=summary)
    return slug


def collect_citation_ids(text: str) -> list[str]:
    return re.findall(r"`([^`]+)`", "\n".join(extract_section(text, "Citations")))


def build_candidate_markdown(query: str, card_type: str, citation_ids: list[str], direct_support: list[str]) -> str:
    slug = safe_slug(query)
    lines = [
        "---",
        f"id: distilled-{slug}",
        f"title: {query.title()}",
        f"type: {card_type}",
        "topic: promoted_distillation",
        "tags:",
        "  - promoted",
        "  - distilled",
        "source_refs:",
    ]
    for citation_id in citation_ids:
        lines.append(f"  - {citation_id}")
    lines.extend(
        [
            "confidence: draft",
            "updated_at: 2026-04-01",
            "origin: promoted_from_distilled_note",
            "---",
            "",
            "## Candidate Summary",
            "",
            f"Promoted candidate derived from the distilled note for query: {query}",
            "",
            "## Direct Support",
            "",
        ]
    )
    for line in direct_support:
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    text = args.draft.read_text(encoding="utf-8")
    query = parse_query(text)
    card_type = infer_card_type(query)
    folder = infer_domain_folder(query, args.knowledge_root, draft_text=text)
    citation_ids = collect_citation_ids(text)
    direct_support = extract_section(text, "Direct Support")

    output_dir = args.knowledge_root / folder
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"candidate-{safe_slug(query)}.md"
    output_path.write_text(
        build_candidate_markdown(query, card_type, citation_ids, direct_support),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
