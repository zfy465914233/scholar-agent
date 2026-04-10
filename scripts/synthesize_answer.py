"""Synthesize a structured answer from an evidence-driven prompt bundle.

Supports two modes:
  1. API mode: calls an OpenAI-compatible LLM API
  2. Local mode: uses a pre-written answer JSON (--local-answer)

Configuration (environment variables):
  LLM_API_URL  – base URL for OpenAI-compatible chat completions endpoint.
  LLM_API_KEY  – API key.
  LLM_MODEL    – model identifier. Default: gpt-4o-mini
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LLM_API_URL = os.environ.get("LLM_API_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "60"))

# Schema is defined in schemas/answer.schema.json — this prompt instructs the
# LLM to produce output conforming to that schema.
ANSWER_SYSTEM_PROMPT = (
    "You are a domain research assistant. Produce a structured JSON answer "
    "from the provided evidence. You MUST respond with valid JSON only.\n\n"
    "Required JSON schema (see schemas/answer.schema.json for full definition):\n"
    "{\n"
    '  "answer": "detailed direct answer — must be actionable for agents",\n'
    '  "supporting_claims": [\n'
    '    {"claim": "specific factual claim with numbers", "evidence_ids": ["id1"], "confidence": "high|medium|low"}\n'
    "  ],\n"
    '  "inferences": ["reasoning and practical recommendations drawn from evidence"],\n'
    '  "uncertainty": ["known limitations and caveats"],\n'
    '  "missing_evidence": ["evidence gaps that would strengthen the answer"],\n'
    '  "suggested_next_steps": ["concrete actionable steps ordered by priority"]\n'
    "}\n\n"
    "Rules:\n"
    "- Every factual claim MUST reference at least one evidence_id from the context.\n"
    "- If evidence is weak or absent, keep the answer narrow and explicitly tentative.\n"
    "- Do NOT fabricate evidence IDs that are not in the context.\n"
    "- Separate what the evidence directly says (supporting_claims) from your reasoning (inferences).\n"
    "- List what is unknown or uncertain under uncertainty.\n"
    "- If critical information is missing, describe it under missing_evidence.\n"
    "- The answer field must be detailed enough for an agent to design a technical roadmap.\n"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synthesize a structured answer from a rendered prompt bundle.",
    )
    parser.add_argument(
        "--prompt-bundle",
        required=True,
        help="Path to prompt-bundle JSON from render_answer_bundle, or '-' for stdin.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"LLM model. Default: {LLM_MODEL}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output file path. Defaults to stdout.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the API request payload without calling the LLM.",
    )
    parser.add_argument(
        "--local-answer",
        type=Path,
        default=None,
        help=(
            "Path to a JSON file containing a pre-written structured answer. "
            "Skips the LLM API call entirely. Use this when the LLM answer is "
            "provided externally (e.g. by a host agent)."
        ),
    )
    return parser.parse_args()


def load_prompt_bundle(path_or_stdin: str) -> dict[str, Any]:
    if path_or_stdin == "-":
        return json.loads(sys.stdin.read())
    return json.loads(Path(path_or_stdin).read_text(encoding="utf-8"))


def build_chat_request(prompt_bundle: dict[str, Any], model: str) -> dict[str, Any]:
    system_prompt = prompt_bundle.get("system_prompt", "")
    user_prompt = prompt_bundle.get("user_prompt", "")
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 2048,
    }


def call_llm(request_payload: dict[str, Any]) -> dict[str, Any]:
    """Call an OpenAI-compatible chat completions endpoint."""
    if not LLM_API_KEY:
        raise RuntimeError(
            "LLM_API_KEY environment variable is not set. "
            "Export it or use --local-answer to skip LLM calls."
        )
    url = LLM_API_URL.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    body = json.dumps(request_payload).encode("utf-8")
    req = Request(url, data=body, headers=headers, method="POST")

    try:
        with urlopen(req, timeout=LLM_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(
            f"LLM API returned HTTP {exc.code}: {detail}"
        ) from exc
    except (URLError, OSError) as exc:
        raise RuntimeError(f"LLM API request failed: {exc}") from exc

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(f"LLM API returned no choices: {json.dumps(data)}")

    content = choices[0].get("message", {}).get("content", "")
    usage = data.get("usage", {})
    return {
        "raw_content": content,
        "model": data.get("model", request_payload["model"]),
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
    }


def parse_answer(raw_content: str) -> dict[str, Any]:
    """Extract structured answer JSON from the LLM response."""
    text = raw_content.strip()

    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
        else:
            return {
                "answer": text,
                "supporting_claims": [],
                "inferences": [],
                "uncertainty": ["LLM response was not valid JSON; raw text returned."],
                "missing_evidence": [],
                "suggested_next_steps": [],
                "_parse_error": True,
            }

    return {
        "answer": parsed.get("answer", ""),
        "supporting_claims": parsed.get("supporting_claims", []),
        "inferences": parsed.get("inferences", []),
        "uncertainty": parsed.get("uncertainty", []),
        "missing_evidence": parsed.get("missing_evidence", []),
        "suggested_next_steps": parsed.get("suggested_next_steps", []),
    }


def validate_claims(answer: dict[str, Any], valid_evidence_ids: set[str]) -> dict[str, Any]:
    """Validate that claims reference existing evidence IDs.

    Strips invalid evidence_ids from supporting_claims and adds
    a warning to uncertainty for each invalid reference found.
    """
    claims = answer.get("supporting_claims", [])
    if not claims:
        return answer

    warnings: list[str] = []
    cleaned_claims: list[dict[str, Any]] = []

    for claim in claims:
        if not isinstance(claim, dict):
            cleaned_claims.append(claim)
            continue

        ids = claim.get("evidence_ids", [])
        valid = [eid for eid in ids if str(eid) in valid_evidence_ids]
        invalid = [eid for eid in ids if str(eid) not in valid_evidence_ids]

        if invalid:
            warnings.append(
                f"Claim references non-existent evidence IDs: {invalid}"
            )
            cleaned = {**claim, "evidence_ids": valid}
            if not valid:
                cleaned["_orphaned"] = True
            cleaned_claims.append(cleaned)
        else:
            cleaned_claims.append(claim)

    result = {**answer, "supporting_claims": cleaned_claims}
    if warnings:
        uncertainty = list(answer.get("uncertainty", []))
        uncertainty.extend(warnings)
        result["uncertainty"] = uncertainty

    return result


def build_synthesis_output(
    answer: dict[str, Any],
    prompt_bundle: dict[str, Any],
    model: str,
    usage: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the final synthesis output with metadata."""
    # Validate claim evidence IDs against citations
    valid_ids = {
        c.get("evidence_id")
        for c in prompt_bundle.get("citations", [])
        if c.get("evidence_id")
    }
    if valid_ids:
        answer = validate_claims(answer, valid_ids)
    return {
        "query": prompt_bundle.get("metadata", {}).get("query", ""),
        "route": prompt_bundle.get("metadata", {}).get("route", ""),
        "answer": answer,
        "citations": prompt_bundle.get("citations", []),
        "synthesis_meta": {
            "model": model,
            "usage": usage,
        },
    }


def synthesize(
    prompt_bundle: dict[str, Any],
    model: str,
    dry_run: bool = False,
    local_answer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full synthesis pipeline.

    If local_answer is provided, it is used directly without calling any API.
    """
    if local_answer is not None:
        return build_synthesis_output(
            local_answer, prompt_bundle, model, {"source": "local"}
        )

    request_payload = build_chat_request(prompt_bundle, model)

    if dry_run:
        return {
            "dry_run": True,
            "request_payload": request_payload,
        }

    llm_response = call_llm(request_payload)
    answer = parse_answer(llm_response["raw_content"])
    return build_synthesis_output(answer, prompt_bundle, model, llm_response["usage"])


def main() -> int:
    args = parse_args()
    model = args.model or LLM_MODEL
    prompt_bundle = load_prompt_bundle(args.prompt_bundle)

    local_answer = None
    if args.local_answer:
        local_answer = json.loads(args.local_answer.read_text(encoding="utf-8"))

    output = synthesize(prompt_bundle, model, dry_run=args.dry_run, local_answer=local_answer)
    text = json.dumps(output, ensure_ascii=False, indent=2)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
