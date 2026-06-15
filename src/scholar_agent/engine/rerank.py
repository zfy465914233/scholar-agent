"""LLM-based cross-encoder rerank for retrieval candidates.

Two strategies:

- **Batched** (default): all candidates are sent in a single LLM call with a
  numbered list prompt; the model returns one score per line. Costs 1 LLM
  call regardless of candidate count. Falls back to per-candidate scoring
  if the batched response cannot be parsed.
- **Per-candidate**: each ``(query, candidate)`` pair is a separate LLM call.
  Robust but expensive (N calls for N candidates).

Uses :func:`scholar_agent.engine.llm_client.chat` for transport, retry, and
timeout so rerank benefits from the same provider resolution and error
handling as other LLM calls.

Enable by passing ``rerank=True`` to :func:`local_retrieve.retrieve` or by
setting ``rerank=True`` on the ``query_knowledge`` MCP tool. Rerank is opt-in.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from scholar_agent.engine.llm_client import LLMResponse, chat

logger = logging.getLogger(__name__)

_BATCH_PROMPT_TEMPLATE = """Rate each document's relevance to the query on a scale of 0 to 10.

Query: {query}

Documents:
{list_block}

Output exactly one line per document in the form "<id> <score>". Example:
1 8
2 3
3 9
Output ONLY those lines, nothing else."""

_PER_CANDIDATE_PROMPT_TEMPLATE = """Rate how relevant this document is to the query on a scale of 0 to 10.

Query: {query}

Document title: {title}
Document excerpt:
{excerpt}

Reply with ONLY a single integer from 0 (irrelevant) to 10 (perfect match). No other text, no explanation."""

_NEUTRAL_SCORE = 5.0
_SCORE_RE = re.compile(r"\b(10|[0-9])\b")
_BATCH_LINE_RE = re.compile(r"^\s*(\d+)\D+(\d{1,2})\s*$", re.MULTILINE)
# Trigger fallback when fewer than this fraction of candidates are scored.
_BATCH_FALLBACK_RATIO = 0.5


def _parse_score(raw: str) -> float:
    """Extract the first 0-10 integer from raw LLM output.

    Returns :data:`_NEUTRAL_SCORE` on any parse failure so a malformed
    response never crashes the rerank pipeline.
    """
    match = _SCORE_RE.search(raw.strip())
    if not match:
        return _NEUTRAL_SCORE
    try:
        score = float(match.group(1))
    except ValueError:
        return _NEUTRAL_SCORE
    return score if 0.0 <= score <= 10.0 else _NEUTRAL_SCORE


def _parse_batch_scores(raw: str, n_expected: int) -> dict[int, float] | None:
    """Parse LLM output of "<id> <score>" lines into {1-based-id: score}.

    Returns None when too few lines parsed (caller should fall back to
    per-candidate scoring).
    """
    scores: dict[int, float] = {}
    for match in _BATCH_LINE_RE.finditer(raw):
        try:
            doc_id = int(match.group(1))
            score = float(match.group(2))
        except ValueError:
            continue
        if 1 <= doc_id <= n_expected and 0.0 <= score <= 10.0:
            scores[doc_id] = score  # last-wins on duplicates, fine
    threshold = max(1, math.ceil(n_expected * _BATCH_FALLBACK_RATIO))
    if len(scores) < threshold:
        return None
    return scores


def _build_list_block(candidates: list[dict[str, Any]], max_chars: int) -> str:
    """Format candidates as a numbered list for the batch prompt."""
    lines: list[str] = []
    for i, candidate in enumerate(candidates, start=1):
        title = str(candidate.get("title", ""))[:200]
        excerpt = str(candidate.get("search_text") or candidate.get("summary") or candidate.get("path", ""))[:max_chars]
        excerpt = excerpt.replace("\n", " ")[:max_chars]
        lines.append(f"{i}. {title} — {excerpt}")
    return "\n".join(lines)


def _rerank_batched(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    model: str | None,
    max_chars: int,
) -> list[float] | None:
    """Single LLM call scoring all candidates. Returns None on parse failure."""
    prompt = _BATCH_PROMPT_TEMPLATE.format(
        query=query[:500],
        list_block=_build_list_block(candidates, max_chars),
    )
    try:
        response: LLMResponse = chat(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.0,
            max_tokens=64 + 8 * len(candidates),
        )
    except Exception as exc:
        logger.warning("rerank batch LLM call failed: %s", exc)
        return None

    scores_by_id = _parse_batch_scores(response.content, len(candidates))
    if scores_by_id is None:
        logger.info("rerank batch parse incomplete; falling back to per-candidate")
        return None

    return [scores_by_id.get(i + 1, _NEUTRAL_SCORE) for i in range(len(candidates))]


def _rerank_per_candidate(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    model: str | None,
    max_chars: int,
) -> list[float]:
    """Score each candidate in a separate LLM call."""
    scores: list[float] = []
    for orig_idx, candidate in enumerate(candidates):
        title = str(candidate.get("title", ""))[:200]
        excerpt = str(candidate.get("search_text") or candidate.get("summary") or candidate.get("path", ""))[:max_chars]
        prompt = _PER_CANDIDATE_PROMPT_TEMPLATE.format(query=query[:500], title=title, excerpt=excerpt)

        score = _NEUTRAL_SCORE
        try:
            response: LLMResponse = chat(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                temperature=0.0,
                max_tokens=8,
            )
            score = _parse_score(response.content)
        except Exception as exc:
            logger.warning("rerank LLM call failed for candidate %d (%s): %s", orig_idx, title[:60], exc)
        scores.append(score)
    return scores


def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    top_k: int = 5,
    model: str | None = None,
    max_chars: int = 500,
    batched: bool = True,
) -> list[dict[str, Any]]:
    """Rerank *candidates* by LLM-judged relevance to *query*.

    With ``batched=True`` (default), sends all candidates in a single LLM
    call and falls back to per-candidate scoring if the batched response
    cannot be parsed. Candidates are sorted by score descending; ties break
    by original order. Returns at most ``top_k`` candidates, each annotated
    with a ``rerank_score`` field.

    On any LLM failure, the affected candidate receives
    :data:`_NEUTRAL_SCORE`. An empty ``candidates`` list returns ``[]``.
    """
    if not candidates or top_k <= 0:
        return []

    if batched:
        scores = _rerank_batched(query, candidates, model=model, max_chars=max_chars)
        if scores is None:
            scores = _rerank_per_candidate(query, candidates, model=model, max_chars=max_chars)
            from scholar_agent.engine import metrics

            metrics.record_rerank_call(fallback=True)
        else:
            from scholar_agent.engine import metrics

            metrics.record_rerank_call(fallback=False)
    else:
        scores = _rerank_per_candidate(query, candidates, model=model, max_chars=max_chars)
        from scholar_agent.engine import metrics

        metrics.record_rerank_call(fallback=False)

    scored: list[tuple[float, int, dict[str, Any]]] = []
    for orig_idx, (candidate, score) in enumerate(zip(candidates, scores, strict=True)):
        reranked = dict(candidate)
        reranked["rerank_score"] = score
        scored.append((score, orig_idx, reranked))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [item[2] for item in scored[:top_k]]
