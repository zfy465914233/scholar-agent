"""Unified lightweight pipeline for daily paper recommendations.

Replaces the legacy dual-track and single-track paths with a single fast
path optimized for local use:

  Concurrent fetch (arXiv + S2) → CPU pre-filter → 1 batch LLM call → ≤3 papers

Target: ~5-10s total latency, 1 LLM call (~1800 tokens).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from scholar_agent.engine.academic.innovation_scorer import (
    _INNOVATION_SIGNALS,
    _QUANTITATIVE_SIGNALS,
    _RED_FLAG_ABSTRACTS,
    _RED_FLAG_TITLES,
)
from scholar_agent.engine.academic.scoring import PaperScorer

if TYPE_CHECKING:
    from scholar_agent.engine.paper_store import PaperStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Batch LLM prompt templates
# ---------------------------------------------------------------------------

_BATCH_SYSTEM = (
    "You are a research advisor selecting today's top papers. "
    "Select at most {max_select} papers. Quality over quantity. "
    "If no paper meets a high bar, select fewer than the maximum."
)

_BATCH_USER_TEMPLATE = """You have {count} candidate papers to evaluate.
Select at most {max_select} papers worth 30 minutes of careful reading.

Candidates:
{candidates_text}

For each selected paper, provide:
- index (1-based)
- reason (why this paper is worth reading carefully today)
- novelty (1-5)
- credibility (1-5)

Also provide an overall rationale.

Respond in this exact JSON format (no markdown fences):
{{"selected": [{{"index": N, "reason": "...", "novelty": N, "credibility": N}}], "rationale": "..."}}"""


# ---------------------------------------------------------------------------
# Query refinement
# ---------------------------------------------------------------------------


def refine_queries(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Extract (arxiv_categories, s2_query_phrases) from research config.

    arXiv uses configured categories directly.
    S2 uses domain keywords combined into search phrases.
    """
    domains = config.get("research_domains", {})
    arxiv_cats: list[str] = []
    s2_phrases: list[str] = []

    for _name, dcfg in domains.items():
        cats = dcfg.get("arxiv_categories", [])
        kws = dcfg.get("keywords", [])

        for c in cats:
            if c not in arxiv_cats:
                arxiv_cats.append(c)

        if kws:
            phrase = " ".join(kws[:3])
            if phrase.lower() not in {p.lower() for p in s2_phrases}:
                s2_phrases.append(phrase)

    if not arxiv_cats:
        arxiv_cats = ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]

    if not s2_phrases:
        s2_phrases = ["deep learning neural network", "AI agent planning reasoning"]

    return arxiv_cats, s2_phrases


# ---------------------------------------------------------------------------
# Concurrent fetch
# ---------------------------------------------------------------------------


def concurrent_fetch(
    arxiv_categories: list[str],
    target_date: datetime | None = None,
    arxiv_days: int = 7,
    max_arxiv: int = 200,
    s2_top_k: int = 10,
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch papers from arXiv and S2 concurrently.

    S2 builds its own query phrases from *config*, so no explicit
    phrase list is needed here.

    Returns (arxiv_papers, s2_papers).
    """
    from scholar_agent.engine.academic.arxiv_search import (
        collect_hot_papers,
        query_arxiv,
    )

    now = target_date or datetime.now()
    arxiv_start = now - timedelta(days=arxiv_days)
    s2_start = now - timedelta(days=365)
    s2_end = now - timedelta(days=31)

    arxiv_result: list[dict[str, Any]] = []
    s2_result: list[dict[str, Any]] = []

    def _fetch_arxiv():
        try:
            return query_arxiv(arxiv_categories, arxiv_start, now, limit=max_arxiv)
        except Exception as exc:
            logger.warning("arXiv fetch failed: %s", exc)
            return []

    def _fetch_s2():
        try:
            return collect_hot_papers(
                categories=arxiv_categories,
                from_dt=s2_start,
                to_dt=s2_end,
                per_cat=s2_top_k,
                config=config,
                # Daily feed prefers recent work, but must NOT hard-exclude classic
                # papers. Search the full S2 corpus (time_agnostic) and let the
                # heuristic pre-filter apply a *soft* recency preference instead.
                time_agnostic=True,
            )
        except Exception as exc:
            logger.warning("S2 fetch failed: %s", exc)
            return []

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            pool.submit(_fetch_arxiv): "arxiv",
            pool.submit(_fetch_s2): "s2",
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                papers = future.result()
                if source == "arxiv":
                    arxiv_result.extend(papers)
                else:
                    s2_result.extend(papers)
            except Exception as exc:
                logger.warning("%s fetch failed: %s", source, exc)

    logger.info("Fetched %d arXiv + %d S2 papers", len(arxiv_result), len(s2_result))
    return arxiv_result, s2_result


# ---------------------------------------------------------------------------
# Dedup + already-analyzed filter
# ---------------------------------------------------------------------------


def _dedup_papers(
    arxiv_papers: list[dict[str, Any]],
    s2_papers: list[dict[str, Any]],
    existing_ids: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """Merge, dedup by arxiv_id, and remove already-analyzed papers."""
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    skipped = 0

    for p in arxiv_papers + s2_papers:
        aid = p.get("arxiv_id") or ""
        if not aid:
            url = p.get("url") or p.get("id") or ""
            m = re.search(r"(?:arXiv:)?(\d+\.\d+)", url)
            aid = m.group(1) if m else ""

        if aid:
            p["arxiv_id"] = aid
            if aid in existing_ids:
                skipped += 1
                continue
            if aid in seen:
                continue
            seen.add(aid)
        else:
            # Fallback: dedup by normalized title for papers without arxiv_id
            title_key = p.get("title", "").strip().lower()
            if title_key and title_key in seen:
                continue
            if title_key:
                seen.add(title_key)
        merged.append(p)

    return merged, skipped


# ---------------------------------------------------------------------------
# Heuristic pre-filter (pure CPU)
# ---------------------------------------------------------------------------


def heuristic_pre_filter(
    papers: list[dict[str, Any]],
    config: dict[str, Any],
    max_candidates: int = 15,
) -> list[dict[str, Any]]:
    """CPU-only filter: relevance + hard negatives + innovation signals.

    Returns up to *max_candidates* papers sorted by composite score.
    """
    domains = config.get("research_domains", {})
    excluded = config.get("excluded_keywords", [])
    scorer = PaperScorer(domains=domains, excluded=excluded)

    scored: list[tuple[float, dict[str, Any]]] = []
    for p in papers:
        title = p.get("title", "").lower()
        abstract = (p.get("summary", "") or p.get("abstract", "")).lower()
        score = 0.0

        # 1. Relevance via PaperScorer._fit
        fit_score, domain, keywords = scorer._fit(p)
        if fit_score <= 0:
            continue
        score += fit_score

        # 2. Innovation signals
        if any(sig in abstract for sig in _INNOVATION_SIGNALS):
            score += 2.0
        if any(sig in abstract for sig in _QUANTITATIVE_SIGNALS):
            score += 1.5

        # 3. Hard negatives
        if len(abstract) < 300:
            score -= 5.0
        if any(rf in title for rf in _RED_FLAG_TITLES):
            score -= 5.0
        if any(rf in abstract for rf in _RED_FLAG_ABSTRACTS):
            score -= 5.0

        # 4. Rigor bonus
        rigor = PaperScorer._rigor(abstract)
        score += rigor * 0.5

        # 5. Soft recency preference — the daily feed leans toward newer work, but
        # unlike the old hard 365-day cutoff this never *excludes* a paper. A
        # high-quality classic can still surface; it just yields to an equally
        # good recent one. Bonus decays linearly to 0 at one year.
        pub_dt = PaperScorer._parse_date(p)
        if pub_dt is not None:
            ref = datetime.now(pub_dt.tzinfo) if pub_dt.tzinfo else datetime.now()
            age_days = max((ref - pub_dt).days, 0)
            score += max(1.5 * (1.0 - age_days / 365.0), 0.0)

        p["_heuristic_score"] = round(score, 2)
        p["scores"] = {
            "fit": round(fit_score, 2),
            "recommendation": round(score, 2),
        }
        p["relevance_score"] = fit_score
        p["best_domain"] = domain
        p["domain_keywords"] = keywords
        scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:max_candidates]]


# ---------------------------------------------------------------------------
# Batch LLM selection (1 call)
# ---------------------------------------------------------------------------


def _ensure_scores(p: dict[str, Any]) -> dict[str, Any]:
    """Guarantee the stable ``scores`` contract on a returned paper.

    Every paper leaving the unified pipeline carries ``scores.fit`` and
    ``scores.recommendation`` — downstream shells (MCP, CLI, library
    consumers) read those keys instead of the internal ``_heuristic_score``.
    """
    scores: dict[str, Any] = p.setdefault("scores", {})
    scores.setdefault("fit", round(p.get("relevance_score", 0) or 0, 2))
    scores.setdefault("recommendation", p.get("_heuristic_score", 0) or 0)
    return scores


def _parse_batch_response(raw: str) -> dict[str, Any]:
    """Parse batch LLM selection response, tolerating markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines)

    start = text.find("{")
    if start >= 0:
        text = text[start:]

    try:
        data = json.loads(text)
        return {
            "selected": data.get("selected", []),
            "rationale": data.get("rationale", ""),
        }
    except json.JSONDecodeError:
        return {"selected": [], "rationale": ""}


def batch_llm_select(
    candidates: list[dict[str, Any]],
    max_select: int = 3,
) -> tuple[list[dict[str, Any]], int, int]:
    """1 LLM call: select ≤max_select papers from candidates.

    Returns (selected_papers, llm_calls, llm_tokens).
    Falls back to heuristic ranking when LLM_API_KEY is unset.
    """
    if not candidates:
        return [], 0, 0

    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        logger.info("[UnifiedPipeline] No LLM_API_KEY, using heuristic-only selection")
        selected = candidates[:max_select]
        for p in selected:
            _ensure_scores(p)
        return selected, 0, 0

    # Build candidates text
    candidates_text = ""
    for i, p in enumerate(candidates, 1):
        title = p.get("title", "Untitled")
        abstract = (p.get("summary", "") or p.get("abstract", ""))[:300]
        h_score = p.get("_heuristic_score", 0)
        candidates_text += f"\n[{i}] Title: {title}\n    Abstract: {abstract}\n    Heuristic score: {h_score}\n"

    system_prompt = _BATCH_SYSTEM.format(max_select=max_select)
    user_prompt = _BATCH_USER_TEMPLATE.format(
        count=len(candidates),
        max_select=max_select,
        candidates_text=candidates_text,
    )

    try:
        from scholar_agent.engine.synthesize_answer import call_llm

        result = call_llm(
            {
                "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 1024,
            }
        )

        tokens = result.get("usage", {}).get("total_tokens", 0)
        llm_response = _parse_batch_response(result.get("raw_content", ""))

        selected_indices: dict[int, dict[str, Any]] = {}
        for s in llm_response.get("selected", []):
            if isinstance(s, dict):
                idx = s.get("index", 0) - 1
                if 0 <= idx < len(candidates):
                    selected_indices[idx] = s

        if not selected_indices:
            logger.warning("[UnifiedPipeline] LLM selected no papers, falling back to heuristic")
            fallback = candidates[:max_select]
            for p in fallback:
                _ensure_scores(p)
            return fallback, 1, tokens

        recommended = []
        for idx in sorted(selected_indices):
            sel = selected_indices[idx]
            p = candidates[idx]
            p["recommendation_reason"] = sel.get("reason", "")
            p["llm_novelty"] = max(1, min(5, sel.get("novelty", 3)))
            p["llm_credibility"] = max(1, min(5, sel.get("credibility", 3)))
            scores = _ensure_scores(p)
            scores["llm_novelty"] = p["llm_novelty"]
            scores["llm_credibility"] = p["llm_credibility"]
            recommended.append(p)

        return recommended[:max_select], 1, tokens

    except Exception as exc:
        logger.warning("[UnifiedPipeline] LLM call failed: %s — heuristic fallback", exc)
        fallback = candidates[:max_select]
        for p in fallback:
            _ensure_scores(p)
        return fallback, 0, 0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_unified_pipeline(
    config: dict[str, Any],
    paper_notes_dir: str,
    target_date: datetime | None = None,
    unified_config: dict[str, Any] | None = None,
    existing_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Run the unified lightweight recommendation pipeline.

    Steps:
      1. Refine queries from config
      2. Concurrent fetch (arXiv + S2)
      3. Merge, dedup, filter already-analyzed + recently-rejected
      4. Heuristic pre-filter (CPU, ≤15 candidates)
      5. Batch LLM select (1 call, ≤3 papers)
      6. Persist run + all reviewed candidates to SQLite, return results

    Returns a dict with ``papers``, ``total_found``, ``skipped``,
    ``unified_pipeline``, ``stats`` — plus ``warnings`` surfacing degraded
    behavior (e.g. LLM selection skipped without ``LLM_API_KEY``).
    """
    t0 = time.monotonic()

    uc = unified_config or {}
    max_rec = uc.get("max_daily_recommendations", 3)
    arxiv_days = uc.get("arxiv_days", 7)
    max_candidates = uc.get("max_candidates", 15)
    max_arxiv = uc.get("max_arxiv_results", 200)
    reject_dedup_days = int(uc.get("reject_dedup_days", 14) or 0)

    date_str = (target_date or datetime.now()).strftime("%Y-%m-%d")
    warnings: list[str] = []

    run_id = _start_funnel_run(date_str, uc)
    try:
        # 1. Refine queries
        arxiv_cats, _s2_phrases = refine_queries(config)

        # 2. Concurrent fetch
        arxiv_papers, s2_papers = concurrent_fetch(
            arxiv_categories=arxiv_cats,
            target_date=target_date,
            arxiv_days=arxiv_days,
            max_arxiv=max_arxiv,
            config=config,
        )
        _record_fetch_checkpoints(date_str, len(arxiv_papers), len(s2_papers))

        # 3. Dedup + skip already-analyzed + skip recently-rejected
        if existing_ids is None:
            from scholar_agent.engine.academic.daily_workflow import get_analyzed_paper_ids

            existing_ids = get_analyzed_paper_ids(paper_notes_dir)
        if reject_dedup_days > 0:
            rejected_ids = _get_recently_rejected_ids(reject_dedup_days)
            if rejected_ids:
                existing_ids = set(existing_ids) | rejected_ids
        merged, skipped = _dedup_papers(arxiv_papers, s2_papers, existing_ids)

        if not merged:
            stats = {
                "arxiv_fetched": len(arxiv_papers),
                "s2_fetched": len(s2_papers),
                "after_dedup": 0,
                "candidates": 0,
                "llm_calls": 0,
                "llm_tokens": 0,
                "duration_seconds": round(time.monotonic() - t0, 2),
            }
            _persist_results(run_id, [], [], stats)
            return {
                "papers": [],
                "total_found": 0,
                "skipped": 0,
                "unified_pipeline": True,
                "warnings": warnings,
                "stats": stats,
            }

        # 4. Heuristic pre-filter
        candidates = heuristic_pre_filter(merged, config, max_candidates=max_candidates)

        # 5. Batch LLM select
        selected, llm_calls, llm_tokens = batch_llm_select(candidates, max_select=max_rec)
        if candidates and llm_calls == 0:
            if os.environ.get("LLM_API_KEY"):
                warnings.append("LLM selection failed — fell back to heuristic ranking")
            else:
                warnings.append("LLM selection skipped (LLM_API_KEY not set) — heuristic ranking used")

        # Candidates the selection did not pick (LLM-rejected, or below the
        # cut when degraded to heuristic ranking).
        selected_ids = {id(p) for p in selected}
        rejected = [p for p in candidates if id(p) not in selected_ids]

        # 6. Persist run + all reviewed candidates in one transaction
        stats = {
            "arxiv_fetched": len(arxiv_papers),
            "s2_fetched": len(s2_papers),
            "after_dedup": len(merged),
            "candidates": len(candidates),
            "llm_calls": llm_calls,
            "llm_tokens": llm_tokens,
            "duration_seconds": round(time.monotonic() - t0, 2),
        }
        _persist_results(run_id, selected, rejected, stats)
    except Exception as exc:
        _fail_funnel_run(run_id, exc)
        raise

    for p in selected:
        p["track"] = "unified_pipeline"

    logger.info(
        "Unified pipeline: %d arXiv + %d S2 → %d merged → %d candidates → %d recommended (%.1fs)",
        stats["arxiv_fetched"],
        stats["s2_fetched"],
        stats["after_dedup"],
        stats["candidates"],
        len(selected),
        stats["duration_seconds"],
    )

    return {
        "papers": selected,
        "total_found": len(merged),
        "skipped": skipped,
        "unified_pipeline": True,
        "warnings": warnings,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# Persistence (SQLite paper store)
# ---------------------------------------------------------------------------


def _open_store() -> PaperStore:
    """Open the configured paper store (caller closes)."""
    from scholar_agent.engine.paper_store import PaperStore
    from scholar_agent.engine.scholar_config import get_paper_db_path

    db_path = get_paper_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = PaperStore(db_path)
    store.initialize()
    return store


def _start_funnel_run(date_str: str, unified_config: dict[str, Any]) -> int | None:
    """Record the start of a pipeline run; None when persistence is unavailable."""
    try:
        with _open_store() as store:
            return store.start_funnel_run(date_str, {"unified_pipeline": unified_config})
    except Exception:
        logger.debug("funnel_runs tracking unavailable", exc_info=True)
        return None


def _record_fetch_checkpoints(date_str: str, arxiv_count: int, s2_count: int) -> None:
    """Checkpoint per-source fetch progress for the run date."""
    try:
        with _open_store() as store, store.transaction():
            store.set_checkpoint("unified_arxiv", "", date_str, arxiv_count)
            store.set_checkpoint("unified_s2", "", date_str, s2_count)
    except Exception:
        logger.debug("fetch checkpoint write failed", exc_info=True)


def _get_recently_rejected_ids(days: int) -> set[str]:
    """Arxiv IDs rejected within the dedup window (best-effort)."""
    try:
        from scholar_agent.engine.scholar_config import get_paper_db_path

        if not get_paper_db_path().exists():
            return set()
        with _open_store() as store:
            return store.get_recently_rejected_ids(days)
    except Exception:
        logger.debug("reject dedup lookup unavailable", exc_info=True)
        return set()


def _persist_results(
    run_id: int | None,
    selected: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    stats: dict[str, Any],
) -> None:
    """Persist all reviewed candidates and close out the funnel run.

    Every candidate that entered LLM review (or heuristic selection when
    degraded) is stored: winners as ``recommended`` (score + reason), the
    rest as ``rejected`` (score + ``rejected_at``) so the reject-dedup
    window can keep them out of future runs. Candidates dropped earlier by
    the heuristic pre-filter are NOT persisted. One transaction, one commit.
    """
    try:
        with _open_store() as store, store.transaction():
            for p in selected:
                row_id = store.upsert_paper(p)
                fields: dict[str, Any] = {
                    "recommendation_score": p.get("_heuristic_score", 0),
                    "recommendation_reason": p.get("recommendation_reason", ""),
                }
                if run_id is not None:
                    fields["funnel_run_id"] = run_id
                store.update_status(row_id, "recommended", **fields)
            for p in rejected:
                row_id = store.upsert_paper(p)
                fields = {
                    "recommendation_score": p.get("_heuristic_score", 0),
                    "skip_reason": "not_selected",
                }
                if run_id is not None:
                    fields["funnel_run_id"] = run_id
                store.update_status(row_id, "rejected", **fields)
            if run_id is not None:
                store.update_funnel_run(
                    run_id,
                    stage1_input=stats.get("arxiv_fetched", 0) + stats.get("s2_fetched", 0),
                    stage2_output=stats.get("after_dedup", 0),
                    stage3_output=stats.get("candidates", 0),
                    stage4_output=len(selected),
                    recommended=len(selected),
                    llm_calls=stats.get("llm_calls", 0),
                    llm_tokens=stats.get("llm_tokens", 0),
                    duration_seconds=stats.get("duration_seconds", 0),
                    status="success",
                )
    except Exception as exc:
        logger.warning("Failed to save to SQLite: %s", exc)


def _fail_funnel_run(run_id: int | None, exc: Exception) -> None:
    """Mark the funnel run as failed (best-effort)."""
    if run_id is None:
        return
    try:
        with _open_store() as store:
            store.update_funnel_run(run_id, status="failed", error_message=str(exc))
    except Exception:
        logger.debug("funnel run failure write failed", exc_info=True)
