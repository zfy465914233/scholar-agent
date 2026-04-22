"""arXiv innovation scoring: heuristic pre-filter + LLM batch evaluation."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any

logger = logging.getLogger(__name__)

_SCRIPTS = str(__import__("pathlib").Path(__file__).resolve().parents[1])
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INNOVATION_SIGNALS = [
    "novel", "first", "paradigm", "unified", "breakthrough",
    "state-of-the-art", "sota", "pioneering", "new framework",
    "new method", "new approach", "innovative", "fundamental",
]

_QUANTITATIVE_SIGNALS = [
    "outperforms", "improves by", "achieves", "accuracy",
    "f1", "bleu", "rouge", "beats", "surpasses", "reduces by",
]

_RED_FLAG_TITLES = ["survey", "review", "tutorial", "workshop", "special session"]
_RED_FLAG_ABSTRACTS = ["we present a survey", "we review", "this survey"]

_MAX_HEURISTIC_TITLE_BOOST = 4.0
_MAX_HEURISTIC_ABSTRACT_BOOST = 3.0


# ---------------------------------------------------------------------------
# Heuristic pre-filter
# ---------------------------------------------------------------------------

def innovation_pre_filter(
    papers: list[dict[str, Any]],
    config: dict[str, Any],
    max_candidates: int = 15,
) -> list[dict[str, Any]]:
    """Score and filter arXiv papers by a lightweight heuristic.

    Returns up to *max_candidates* papers sorted by heuristic score desc.
    Each paper gains a ``_heuristic_score`` field.
    """
    # Flatten keywords from all research domains
    all_keywords: set[str] = set()
    for domain_cfg in config.get("research_domains", {}).values():
        for kw in domain_cfg.get("keywords", []):
            all_keywords.add(kw.lower())

    scored: list[tuple[float, dict[str, Any]]] = []
    for p in papers:
        title = p.get("title", "").lower()
        abstract = (p.get("summary", "") or p.get("abstract", "")).lower()
        score = 0.0

        # --- Relevance keywords ---
        title_boost = 0.0
        for kw in all_keywords:
            if kw in title:
                title_boost += 2.0
        score += min(title_boost, _MAX_HEURISTIC_TITLE_BOOST)

        abstract_boost = 0.0
        for kw in all_keywords:
            if kw in abstract:
                abstract_boost += 1.0
        score += min(abstract_boost, _MAX_HEURISTIC_ABSTRACT_BOOST)

        # --- Innovation signals ---
        if any(sig in abstract for sig in _INNOVATION_SIGNALS):
            score += 3.0

        # --- Quantitative evidence ---
        if any(sig in abstract for sig in _QUANTITATIVE_SIGNALS):
            score += 2.0

        # --- Red flags ---
        if len(abstract) < 200:
            score -= 5.0
        if any(rf in title for rf in _RED_FLAG_TITLES):
            score -= 5.0
        if any(rf in abstract for rf in _RED_FLAG_ABSTRACTS):
            score -= 5.0

        p["_heuristic_score"] = round(score, 2)
        scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:max_candidates]]


# ---------------------------------------------------------------------------
# LLM batch scoring
# ---------------------------------------------------------------------------

def innovation_llm_batch_score(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Call LLM once to score all candidates for novelty and credibility.

    Falls back to heuristic-only when LLM_API_KEY is unset or parsing fails.
    """
    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        logger.warning("[InnovationScorer] No LLM_API_KEY, using heuristic-only")
        return _fallback_heuristic(candidates)

    # Build prompt
    papers_block: list[str] = []
    for i, p in enumerate(candidates, 1):
        title = p.get("title", "Untitled")
        abstract = (p.get("summary", "") or p.get("abstract", ""))[:300]
        papers_block.append(f"[{i}] Title: {title}\n    Abstract: {abstract}")

    user_prompt = (
        "Evaluate the following research preprints for **innovation** and **credibility**.\n"
        "For each paper provide:\n"
        '- novelty (1-5): How novel/original is the approach vs existing work?\n'
        '- credibility (1-5): How credible are the claims? Consider: specific '
        "benchmark results, ablation mentions, code release promises, author track record cues.\n"
        "- comment: One-line assessment.\n\n"
        + "\n".join(papers_block)
        + "\n\nRespond in this exact JSON format (no markdown fences):\n"
        '{"evaluations": [{"index": 1, "novelty": N, "credibility": N, "comment": "..."}, ...]}'
    )

    request_payload = {
        "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": "You are a senior ML researcher evaluating preprints."},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }

    try:
        from synthesize_answer import call_llm
        result = call_llm(request_payload)
        raw = result.get("raw_content", "")
        evaluations = _parse_llm_response(raw, len(candidates))
    except Exception as e:
        logger.warning("[InnovationScorer] LLM call failed: %s — falling back to heuristic", e)
        return _fallback_heuristic(candidates)

    # Merge LLM scores with heuristic
    for p in candidates:
        p["_llm_score"] = 0.0
        p["_llm_comment"] = ""

    for ev in evaluations:
        idx = ev.get("index", 0) - 1
        if 0 <= idx < len(candidates):
            novelty = max(1, min(5, ev.get("novelty", 3)))
            credibility = max(1, min(5, ev.get("credibility", 3)))
            candidates[idx]["_llm_score"] = (novelty + credibility) / 2.0
            candidates[idx]["_llm_comment"] = ev.get("comment", "")

    # Combine: 0.4 * heuristic_norm + 0.6 * llm_norm
    max_h = max((p["_heuristic_score"] for p in candidates), default=1) or 1
    for p in candidates:
        h_norm = p["_heuristic_score"] / max_h
        l_norm = p["_llm_score"] / 5.0
        p["_innovation_final_score"] = round(0.4 * h_norm + 0.6 * l_norm, 3)

    candidates.sort(key=lambda x: x.get("_innovation_final_score", 0), reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_llm_response(raw: str, expected: int) -> list[dict]:
    """Parse JSON from LLM response, tolerating markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    # Try to find JSON object
    start = text.find("{")
    if start >= 0:
        text = text[start:]

    try:
        data = json.loads(text)
        evals = data.get("evaluations", [])
        if isinstance(evals, list) and len(evals) > 0:
            return evals
    except json.JSONDecodeError:
        pass

    logger.warning("[InnovationScorer] Could not parse LLM JSON, returning defaults")
    return [{"index": i + 1, "novelty": 3, "credibility": 3, "comment": ""} for i in range(expected)]


def _fallback_heuristic(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure heuristic fallback when LLM is unavailable."""
    for p in candidates:
        p["_llm_score"] = 0.0
        p["_llm_comment"] = "(heuristic-only)"
        max_h = max((c.get("_heuristic_score", 1) for c in candidates), default=1) or 1
        p["_innovation_final_score"] = round(p.get("_heuristic_score", 0) / max_h, 3)

    candidates.sort(key=lambda x: x.get("_innovation_final_score", 0), reverse=True)
    return candidates
