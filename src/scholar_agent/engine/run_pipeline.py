"""Run the full query-to-answer pipeline.

Wires together: orchestrate → answer context → render bundle → synthesize answer.
Each stage is a subprocess call, piping JSON between stages.

Usage:
  python run_pipeline.py "what is a markov chain"
  python run_pipeline.py "latest QPE methods" --mode auto --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
DEFAULT_INDEX = Path.cwd() / "indexes" / "local" / "index.json"

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full query-to-answer pipeline.")
    parser.add_argument("query", help="User query")
    parser.add_argument(
        "--mode",
        choices=("auto", "local-led", "web-led", "mixed", "context-led"),
        default="auto",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX,
        help="Path to the local retrieval index.",
    )
    parser.add_argument(
        "--research-script",
        type=Path,
        default=ENGINE_DIR / "research_harness.py",
        help="Research harness script for web evidence.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LLM model for answer synthesis.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output file path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Stop after rendering the prompt bundle; do not call the LLM.",
    )
    parser.add_argument(
        "--keep-intermediate",
        action="store_true",
        help="Include intermediate outputs (answer context, prompt bundle) in the result.",
    )
    return parser.parse_args()


def _run(script: str, args: list[str], stdin_data: str | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(ENGINE_DIR / script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=stdin_data,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{script} failed (exit {result.returncode}): {result.stderr}")
    return result


def run_pipeline(
    query: str,
    mode: str = "auto",
    index: Path = DEFAULT_INDEX,
    research_script: Path | None = None,
    model: str | None = None,
    dry_run: bool = False,
    keep_intermediate: bool = False,
) -> dict:
    """Execute the full pipeline and return the final output dict."""

    research_script = research_script or ENGINE_DIR / "research_harness.py"

    # Stage 1: Build answer context (includes routing and evidence collection)
    ctx_args = [
        query,
        "--mode",
        mode,
        "--index",
        str(index),
        "--research-script",
        str(research_script),
    ]
    ctx_result = _run("build_answer_context.py", ctx_args)
    answer_context = json.loads(ctx_result.stdout)

    # Stage 2: Render prompt bundle
    render_result = _run("render_answer_bundle.py", ["--answer-context-json", "-"], stdin_data=ctx_result.stdout)
    prompt_bundle = json.loads(render_result.stdout)

    if dry_run:
        output = {
            "query": query,
            "pipeline_status": "dry_run",
            "route": answer_context.get("route"),
            "citations": answer_context.get("citations", []),
            "answer_context_summary": {
                "direct_support_count": len(answer_context.get("direct_support", [])),
                "citations_count": len(answer_context.get("citations", [])),
                "uncertainty_count": len(answer_context.get("uncertainty_notes", [])),
            },
            "prompt_bundle": prompt_bundle,
        }
        if keep_intermediate:
            output["intermediate"] = {
                "answer_context": answer_context,
                "prompt_bundle": prompt_bundle,
            }
        return output

    # Stage 3: Synthesize answer
    synthesize_args = ["--prompt-bundle", "-"]
    if model:
        synthesize_args.extend(["--model", model])
    synth_result = _run("synthesize_answer.py", synthesize_args, stdin_data=render_result.stdout)
    synthesis = json.loads(synth_result.stdout)

    output = {
        "query": query,
        "pipeline_status": "complete",
        "route": answer_context.get("route"),
        "answer": synthesis.get("answer", {}),
        "citations": synthesis.get("citations", []),
        "synthesis_meta": synthesis.get("synthesis_meta", {}),
    }

    if keep_intermediate:
        output["intermediate"] = {
            "answer_context": answer_context,
            "prompt_bundle": prompt_bundle,
        }

    return output


def main() -> int:
    args = parse_args()

    # Ensure index exists
    if not args.index.exists():
        logger.info("Building index at %s...", args.index)
        build_result = subprocess.run(
            [sys.executable, str(ENGINE_DIR / "local_index.py"), "--output", str(args.index)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if build_result.returncode != 0:
            logger.error("Failed to build index: %s", build_result.stderr)
            return 1

    try:
        output = run_pipeline(
            query=args.query,
            mode=args.mode,
            index=args.index,
            research_script=args.research_script,
            model=args.model,
            dry_run=args.dry_run,
            keep_intermediate=args.keep_intermediate,
        )
    except RuntimeError as exc:
        logger.error("Pipeline error: %s", exc)
        return 1

    text = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
