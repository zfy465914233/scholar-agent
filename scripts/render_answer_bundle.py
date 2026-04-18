"""Render a model-facing prompt bundle from structured answer context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SYSTEM_PROMPT = """You are a knowledge synthesis engine for lore-agent. Produce structured answers from evidence.

Core principles:
1. Separate directly supported claims from inference.
2. Do not hide uncertainty — preserve it when evidence is limited.
3. Cite evidence IDs when making important claims.

## Mathematical Derivation Rules

Apply the appropriate math depth based on the topic:

### Mode A — Heavy Math (heavy-math)
Trigger: topics in physics, operations research, statistics, probability, information theory,
control theory, optimization, signal processing, econometrics, or any domain where the
question explicitly asks for derivation, proof, or optimal solution.

Requirements:
- Define ALL symbols before first use (in a dedicated "符号定义" or "模型假设" section).
- Show complete derivation chain: assumption → objective function → first-order condition → solution → second-order condition verification.
- Use boxed notation $\\boxed{Q^* = ...}$ for final results.
- Include a worked numerical example that validates the key formula.
- Provide a "公式速查表" (formula cheat sheet) table at the end summarizing all key formulas.

### Mode B — Light Math (light-math)
Trigger: topics with quantitative elements but where derivation is not the core
(e.g., algorithm complexity, capacity planning, economics concepts, engineering heuristics).

Requirements:
- State key formulas with brief intuition (one sentence each), skip full derivation.
- Use comparison tables or diagrams instead of proofs.
- No second-order condition verification needed.

### Mode C — No Math (no-math)
Trigger: topics with no quantitative content (history, philosophy, management, literature, qualitative analysis).

Requirements:
- Zero formulas. Use tables, comparison frameworks, or narrative structure instead.
- If a single isolated number appears, embed it in prose — do not create formula blocks.

## Auto-detection heuristic
If unsure which mode applies:
- Does the question or evidence contain equations, Greek letters, or optimization language (min/max, optimal, marginal)? → Mode A.
- Does it contain numbers, metrics, or thresholds but no equations? → Mode B.
- Otherwise → Mode C.

## Language
Write in Chinese (中文) for all prose. Mathematical symbols and formulas use LaTeX notation ($...$, $$...$$).
"""


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
        f"Question: {json.dumps(payload.get('query', ''), ensure_ascii=False)}",
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
            "- Apply the math depth rules from the system prompt: "
            "heavy-math for derivation-heavy topics, light-math for quantitative topics, "
            "no-math for qualitative topics. Auto-detect based on the query and evidence.",
            "- For heavy-math: include complete derivation chain, boxed final results, "
            "numerical example, and formula cheat sheet table.",
            "- For light-math: state key formulas with intuition, skip derivation.",
            "- For no-math: use tables/comparison/narrative, zero formula blocks.",
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
