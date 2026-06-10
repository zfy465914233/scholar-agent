"""Multi-stage quality funnel for precision paper recommendations.

4-stage pipeline:
  1. Relevance filter (reuse PaperScorer._fit)
  2. Hard negative filter (rule-based)
  3. LLM structured review (per-paper, 5 yes/no questions)
  4. LLM cross-comparison (batch, select ≤3)

Only papers passing all stages are recommended.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

from scholar_agent.engine.paper_store import PaperStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage 3 LLM prompts
# ---------------------------------------------------------------------------

_STAGE3_SYSTEM = (
    "You are a senior ML/AI researcher performing rigorous paper quality screening. "
    "Evaluate based ONLY on the abstract. Be conservative: if insufficient evidence, answer NO."
)

_STAGE3_USER_TEMPLATE = """Evaluate this research paper for quality. Answer 5 yes/no questions.

Title: {title}
Abstract: {abstract}

Questions:
1. PROBLEM_DEFINED: Is the problem clearly stated and meaningful?
2. METHOD_SPECIFIC: Is the method described specifically enough to evaluate?
3. RESULTS_CONCRETE: Are there quantitative results or theoretical guarantees? (reference only, not a hard gate)
4. CONTRIBUTION_GENUISE: Is there a genuine technical contribution (not just engineering or recombination)?
5. NO_RED_FLAGS: Are there NO red flags from this checklist?
   - Overclaimed ("revolutionary", "groundbreaking") without concrete support
   - Method described too vaguely to reproduce (e.g., "novel architecture" with no details)
   - Only qualitative results with no quantitative backup
   - Incremental contribution presented as breakthrough
   - Self-promotional comparisons rather than objective evaluation

For each question, cite specific text from the abstract as evidence.

Also rate:
- novelty (1-5): How novel/original is the approach?
- credibility (1-5): How credible are the claims?
- depth (1-5): How deep is the technical content?
- rigor (1-5): How rigorous is the methodology?

Respond in this exact JSON format (no markdown fences):
{{"checks": [{{"question": "PROBLEM_DEFINED", "passed": true, "evidence": "..."}}, ...], "novelty": N, "credibility": N, "depth": N, "rigor": N}}"""

# ---------------------------------------------------------------------------
# Stage 4 LLM prompts
# ---------------------------------------------------------------------------

_STAGE4_SYSTEM = (
    "You are a research advisor selecting papers worth reading carefully. "
    "Select at most 3 papers. Quality over quantity. "
    "If no paper meets a high bar, select fewer than 3."
)

_STAGE4_USER_TEMPLATE = """You have {count} candidate papers that passed quality screening.
Select at most {max_rec} papers to recommend for today.

Candidates:
{candidates_text}

For each selected paper, provide:
- index (1-based)
- reason (why this paper is worth 30 minutes of careful reading)
- priority (1=highest, 2, 3)

Also provide an overall rationale for the selection.

Respond in this exact JSON format (no markdown fences):
{{"selected": [{{"index": N, "reason": "...", "priority": N}}], "rationale": "..."}}"""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class FunnelResult:
    recommended: list[dict[str, Any]]
    stage_counts: dict[str, int] = field(default_factory=dict)
    llm_calls: int = 0
    llm_tokens: int = 0
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# QualityFunnel
# ---------------------------------------------------------------------------


class QualityFunnel:
    """Multi-stage precision funnel for daily paper recommendations."""

    def __init__(self, store: PaperStore, config: dict[str, Any]) -> None:
        self.store = store
        self.config = config
        self.funnel_cfg = config.get("precision_funnel", {})
        self.hard_neg_cfg = self.funnel_cfg.get("hard_negative", {})
        self.llm_cfg = self.funnel_cfg.get("llm_review", {})
        self.cross_cfg = self.funnel_cfg.get("cross_comparison", {})
        self.max_rec = self.funnel_cfg.get("max_daily_recommendations", 3)

    def run_daily(self, papers: list[dict[str, Any]] | None = None) -> FunnelResult:
        """Execute the full 4-stage funnel.

        If *papers* is None, fetches papers with status='fetched' from the store.
        """
        import time as _time

        t0 = _time.monotonic()

        if papers is None:
            papers = self.store.get_papers_by_status("fetched", limit=500)

        stage_counts = {"input": len(papers)}

        # Stage 1
        s1_passed = self.stage1_relevance_filter(papers)
        stage_counts["stage1_passed"] = len(s1_passed)

        # Stage 2
        s2_passed = self.stage2_hard_negative_filter(s1_passed)
        stage_counts["stage2_passed"] = len(s2_passed)

        # Stage 3
        llm_calls = 0
        llm_tokens = 0
        s3_passed, c3, t3 = self.stage3_llm_review(s2_passed)
        llm_calls += c3
        llm_tokens += t3
        stage_counts["stage3_passed"] = len(s3_passed)

        # Stage 4
        s4_passed, c4, t4 = self.stage4_cross_comparison(s3_passed)
        llm_calls += c4
        llm_tokens += t4
        stage_counts["stage4_passed"] = len(s4_passed)

        duration = _time.monotonic() - t0

        return FunnelResult(
            recommended=s4_passed,
            stage_counts=stage_counts,
            llm_calls=llm_calls,
            llm_tokens=llm_tokens,
            duration_seconds=round(duration, 2),
        )

    # -- Stage 1: Relevance --------------------------------------------------

    def stage1_relevance_filter(self, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter papers by relevance to configured research domains.

        Reuses PaperScorer._fit() for keyword matching.
        """
        from scholar_agent.engine.academic.scoring import PaperScorer

        domains = self.config.get("research_domains", {})
        excluded = self.config.get("excluded_keywords", [])
        scorer = PaperScorer(domains=domains, excluded=excluded)

        passed: list[dict[str, Any]] = []
        for p in papers:
            fit_score, domain, keywords = scorer._fit(p)
            if fit_score <= 0:
                self.store.update_status(
                    p.get("_db_id", 0), "skipped", skip_reason="low_relevance"
                )
                continue
            p["relevance_score"] = fit_score
            p["best_domain"] = domain
            p["domain_keywords"] = keywords
            paper_id = p.get("_db_id", 0)
            if paper_id:
                self.store.update_status(
                    paper_id, "stage1_passed",
                    relevance_score=fit_score,
                    best_domain=domain,
                    domain_keywords=json.dumps(keywords, ensure_ascii=False),
                )
            passed.append(p)
        return passed

    # -- Stage 2: Hard negative filter ---------------------------------------

    def stage2_hard_negative_filter(self, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Rule-based hard negative filtering."""
        min_abstract_len = self.hard_neg_cfg.get("min_abstract_length", 500)
        reject_title_patterns = self.hard_neg_cfg.get("reject_title_patterns", [])
        reject_abstract_starters = self.hard_neg_cfg.get("reject_abstract_starters", [])

        passed: list[dict[str, Any]] = []
        for p in papers:
            abstract = (p.get("abstract") or p.get("summary") or "").strip()
            title = (p.get("title") or "").strip().lower()

            # Short abstract
            if len(abstract) < min_abstract_len:
                self._skip(p, "short_abstract")
                continue

            # Title patterns
            rejected = False
            for pattern in reject_title_patterns:
                if pattern.lower() in title:
                    self._skip(p, "survey_title")
                    rejected = True
                    break
            if rejected:
                continue

            # Abstract starters
            abstract_lower = abstract[:100].lower()
            for starter in reject_abstract_starters:
                if starter.lower() in abstract_lower:
                    self._skip(p, "survey_abstract")
                    rejected = True
                    break
            if rejected:
                continue

            paper_id = p.get("_db_id", 0)
            if paper_id:
                self.store.update_status(paper_id, "stage2_passed")
            passed.append(p)
        return passed

    # -- Stage 3: LLM review -------------------------------------------------

    def stage3_llm_review(
        self, papers: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Per-paper LLM quality screening. Returns (passed, llm_calls, llm_tokens)."""
        api_key = os.environ.get("LLM_API_KEY", "")
        if not api_key:
            logger.warning("[QualityFunnel] No LLM_API_KEY, skipping Stage 3 review")
            return papers, 0, 0

        max_survivors = self.llm_cfg.get("max_survivors", 8)
        required_passes = set(self.llm_cfg.get("required_passes", [
            "PROBLEM_DEFINED", "METHOD_SPECIFIC", "CONTRIBUTION_GENUISE", "NO_RED_FLAGS",
        ]))
        delay = self.llm_cfg.get("call_delay_seconds", 1.0)
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

        passed: list[dict[str, Any]] = []
        total_calls = 0
        total_tokens = 0

        for p in papers:
            # Strip authors/affiliations for unbiased evaluation
            title = p.get("title", "")
            abstract = (p.get("abstract") or p.get("summary") or "").strip()

            user_prompt = _STAGE3_USER_TEMPLATE.format(title=title, abstract=abstract)

            try:
                from scholar_agent.engine.synthesize_answer import call_llm

                result = call_llm({
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _STAGE3_SYSTEM},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                })
                total_calls += 1
                total_tokens += result.get("usage", {}).get("total_tokens", 0)

                review = _parse_stage3_response(result.get("raw_content", ""))
                p["_llm_review"] = review
                p["llm_novelty"] = review.get("novelty", 0)
                p["llm_credibility"] = review.get("credibility", 0)
                p["llm_depth"] = review.get("depth", 0)
                p["llm_rigor"] = review.get("rigor", 0)

                # Check required passes
                checks = review.get("checks", [])
                check_map = {c["question"]: c.get("passed", False) for c in checks if isinstance(c, dict)}
                all_required_passed = all(check_map.get(q, False) for q in required_passes)

                paper_id = p.get("_db_id", 0)
                if all_required_passed:
                    if paper_id:
                        self.store.update_status(
                            paper_id, "stage3_passed",
                            llm_review_passed=1,
                            llm_review_detail=json.dumps(review, ensure_ascii=False),
                            llm_novelty=review.get("novelty"),
                            llm_credibility=review.get("credibility"),
                            llm_depth=review.get("depth"),
                            llm_rigor=review.get("rigor"),
                            llm_model=model,
                        )
                    passed.append(p)
                else:
                    if paper_id:
                        self.store.update_status(
                            paper_id, "skipped",
                            skip_reason="llm_review_failed",
                            llm_review_detail=json.dumps(review, ensure_ascii=False),
                            llm_model=model,
                        )

                if delay > 0:
                    time.sleep(delay)

            except Exception as e:
                logger.warning("[QualityFunnel] Stage 3 LLM error for '%s': %s", title, e)
                # On error, skip conservatively
                paper_id = p.get("_db_id", 0)
                if paper_id:
                    self.store.update_status(paper_id, "skipped", skip_reason="llm_error")

        # Cap survivors
        if len(passed) > max_survivors:
            passed.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
            for p in passed[max_survivors:]:
                paper_id = p.get("_db_id", 0)
                if paper_id:
                    self.store.update_status(paper_id, "skipped", skip_reason="stage3_cap")
            passed = passed[:max_survivors]

        return passed, total_calls, total_tokens

    # -- Stage 4: Cross-comparison -------------------------------------------

    def stage4_cross_comparison(
        self, papers: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Batch LLM comparison to select final ≤3 recommendations."""
        if not papers:
            return [], 0, 0

        api_key = os.environ.get("LLM_API_KEY", "")
        if not api_key:
            logger.warning("[QualityFunnel] No LLM_API_KEY, using top relevance fallback")
            selected = sorted(papers, key=lambda x: x.get("relevance_score", 0), reverse=True)
            return selected[:self.max_rec], 0, 0

        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

        candidates_text = ""
        for i, p in enumerate(papers, 1):
            title = p.get("title", "")
            abstract = (p.get("abstract") or p.get("summary", ""))[:300]
            review = p.get("_llm_review", {})
            novelty = review.get("novelty", "N/A")
            credibility = review.get("credibility", "N/A")
            candidates_text += (
                f"\n[{i}] Title: {title}\n"
                f"    Abstract: {abstract}\n"
                f"    Scores: novelty={novelty}, credibility={credibility}\n"
            )

        user_prompt = _STAGE4_USER_TEMPLATE.format(
            count=len(papers),
            max_rec=self.max_rec,
            candidates_text=candidates_text,
        )

        try:
            from scholar_agent.engine.synthesize_answer import call_llm

            result = call_llm({
                "model": model,
                "messages": [
                    {"role": "system", "content": _STAGE4_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 1024,
            })

            llm_response = _parse_stage4_response(result.get("raw_content", ""))
            selected_indices = {s["index"] - 1 for s in llm_response.get("selected", []) if isinstance(s, dict)}

            recommended = []
            for i, p in enumerate(papers):
                paper_id = p.get("_db_id", 0)
                if i in selected_indices:
                    sel = next((s for s in llm_response.get("selected", []) if isinstance(s, dict) and s.get("index") == i + 1), {})
                    p["recommendation_reason"] = sel.get("reason", "")
                    p["recommendation_priority"] = sel.get("priority", 99)
                    if paper_id:
                        self.store.update_status(
                            paper_id, "recommended",
                            recommendation_score=p.get("relevance_score", 0),
                            recommendation_reason=sel.get("reason", ""),
                        )
                    recommended.append(p)
                else:
                    if paper_id:
                        self.store.update_status(paper_id, "skipped", skip_reason="not_selected_stage4")

            recommended.sort(key=lambda x: x.get("recommendation_priority", 99))
            return recommended, 1, result.get("usage", {}).get("total_tokens", 0)

        except Exception as e:
            logger.warning("[QualityFunnel] Stage 4 LLM error: %s — falling back to relevance", e)
            selected = sorted(papers, key=lambda x: x.get("relevance_score", 0), reverse=True)
            for p in selected[:self.max_rec]:
                paper_id = p.get("_db_id", 0)
                if paper_id:
                    self.store.update_status(
                        paper_id, "recommended",
                        recommendation_score=p.get("relevance_score", 0),
                    )
            return selected[:self.max_rec], 0, 0

    # -- Helpers -------------------------------------------------------------

    def _skip(self, paper: dict[str, Any], reason: str) -> None:
        paper_id = paper.get("_db_id", 0)
        if paper_id:
            self.store.update_status(paper_id, "skipped", skip_reason=reason)


# ---------------------------------------------------------------------------
# LLM response parsers
# ---------------------------------------------------------------------------


def _parse_stage3_response(raw: str) -> dict[str, Any]:
    """Parse Stage 3 LLM response into structured review."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    start = text.find("{")
    if start >= 0:
        text = text[start:]

    try:
        data = json.loads(text)
        return {
            "checks": data.get("checks", []),
            "novelty": max(1, min(5, data.get("novelty", 3))),
            "credibility": max(1, min(5, data.get("credibility", 3))),
            "depth": max(1, min(5, data.get("depth", 3))),
            "rigor": max(1, min(5, data.get("rigor", 3))),
        }
    except json.JSONDecodeError:
        # Return conservative defaults
        return {
            "checks": [],
            "novelty": 3,
            "credibility": 3,
            "depth": 3,
            "rigor": 3,
        }


def _parse_stage4_response(raw: str) -> dict[str, Any]:
    """Parse Stage 4 LLM response into selection."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
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
