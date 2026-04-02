"""Minimal routing and orchestration for hybrid local/web evidence building."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from build_evidence_pack import build_evidence_pack


LATEST_PATTERNS = (
    "latest",
    "newest",
    "recent",
    "today",
    "current",
    "sota",
)
DEFINITION_PATTERNS = (
    "what is",
    "define",
    "definition",
    "derive",
    "derivation",
    "theorem",
    "proof",
)
CODE_PATTERNS = (
    "bug",
    "error",
    "stack trace",
    "failing test",
    "script",
    "code",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Route a query and build a minimal evidence pack.")
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


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def classify_route(query: str) -> str:
    normalized = normalize_text(query)

    if any(pattern in normalized for pattern in LATEST_PATTERNS):
        return "web-led"
    if any(pattern in normalized for pattern in DEFINITION_PATTERNS):
        return "local-led"
    if any(pattern in normalized for pattern in CODE_PATTERNS):
        return "context-led"
    return "mixed"


def build_decision(route: str, has_web_evidence: bool) -> dict[str, object]:
    if route == "web-led":
        return {
            "primary_source": "web",
            "web_requested": True,
            "web_available": has_web_evidence,
            "note": "Route prefers web evidence for freshness-sensitive queries.",
        }
    if route == "local-led":
        return {
            "primary_source": "local",
            "web_requested": has_web_evidence,
            "web_available": has_web_evidence,
            "note": "Route prefers local knowledge for definitions and derivations.",
        }
    if route == "context-led":
        return {
            "primary_source": "context",
            "web_requested": False,
            "web_available": has_web_evidence,
            "note": "Route would normally prefer direct repo/context inspection first.",
        }
    return {
        "primary_source": "mixed" if has_web_evidence else "local",
        "web_requested": has_web_evidence,
        "web_available": has_web_evidence,
        "note": "Route blends local and web evidence when available.",
    }


def generate_web_evidence(query: str, research_script: Path) -> tuple[Path | None, str | None]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        output_path = Path(handle.name)

    command = [
        sys.executable,
        str(research_script),
        query,
        "--depth",
        "quick",
        "--output",
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        output_path.unlink(missing_ok=True)
        return None, f"research harness failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    return output_path, None


def main() -> int:
    args = parse_args()
    route = classify_route(args.query) if args.mode == "auto" else args.mode
    generated_web_path: Path | None = None
    warnings: list[str] = []

    if route in {"web-led", "mixed"} and args.web_evidence is None:
        generated_web_path, warning = generate_web_evidence(args.query, args.research_script)
        if warning:
            warnings.append(warning)

    include_web = args.web_evidence or generated_web_path
    evidence_pack = build_evidence_pack(args.query, args.index, include_web, args.local_limit)
    decision = build_decision(route, has_web_evidence=include_web is not None)

    payload = {
        "query": args.query,
        "route": route,
        "decision": decision,
        "evidence_pack": evidence_pack,
        "warnings": warnings,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if generated_web_path is not None:
        generated_web_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
