"""Render a model-facing prompt bundle from structured answer context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SYSTEM_PROMPT = (
    "Answer using the provided evidence context. Separate directly supported claims from inference. "
    "Do not hide uncertainty. Cite evidence IDs when making important claims."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a model-facing prompt bundle from answer-context JSON.")
    parser.add_argument(
        "--answer-context-json",
        required=True,
        help="Path to answer-context JSON, or '-' to read from stdin.",
    )
    return parser.parse_args()


def load_payload(path_or_stdin: str) -> dict[str, object]:
    if path_or_stdin == "-":
        return json.loads(sys.stdin.read())
    return json.loads(Path(path_or_stdin).read_text(encoding="utf-8"))


def render_user_prompt(payload: dict[str, object]) -> str:
    direct_support = payload.get("direct_support", [])
    inference_notes = payload.get("inference_notes", [])
    uncertainty_notes = payload.get("uncertainty_notes", [])
    citations = payload.get("citations", [])

    lines = [
        f"Question: {payload.get('query', '')}",
        f"Route: {payload.get('route', '')}",
        "",
        "Direct Support:",
    ]
    for item in direct_support:
        lines.append(f"- [{item['evidence_id']}] {item['support']}")

    lines.extend(["", "Inference Notes:"])
    for note in inference_notes:
        lines.append(f"- {note}")

    lines.extend(["", "Uncertainty Notes:"])
    for note in uncertainty_notes:
        lines.append(f"- {note}")

    lines.extend(["", "Citations:"])
    for citation in citations:
        source = citation.get("path") or citation.get("url") or ""
        lines.append(
            f"- [{citation['evidence_id']}] {citation['title']} "
            f"({citation['origin']} / {citation['source_type']}) {source}"
        )

    lines.extend(
        [
            "",
            "Instructions:",
            "- Use direct support first.",
            "- Mark any synthesis as inference.",
            "- Preserve uncertainty when evidence is limited.",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    payload = load_payload(args.answer_context_json)
    bundle = {
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": render_user_prompt(payload),
        "metadata": {
            "query": payload.get("query", ""),
            "route": payload.get("route", ""),
        },
        "citations": payload.get("citations", []),
    }
    print(json.dumps(bundle, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
