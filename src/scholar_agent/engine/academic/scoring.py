"""Paper scoring engine — class-based multi-dimensional ranking.

Evaluates academic papers across four dimensions (fit, freshness, impact,
rigor), combines them into a weighted recommendation score, and filters
out papers that match exclusion rules.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime
from typing import Any, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------

_CEILING = 5.0  # per-dimension maximum

# Weight profiles — emphasis differs by use case
_WEIGHTS_DEFAULT: dict[str, float] = {
    "fit": 0.34,
    "freshness": 0.14,
    "impact": 0.32,
    "rigor": 0.20,
}
_WEIGHTS_TRENDING: dict[str, float] = {
    "fit": 0.28,
    "freshness": 0.07,
    "impact": 0.45,
    "rigor": 0.20,
}
WEIGHTS_CONF: dict[str, float] = {
    "fit": 0.34,
    "impact": 0.38,
    "rigor": 0.28,
}

# Relevance: precompiled pattern weights
_TITLE_PTS = 1.0
_ABSTRACT_PTS = 0.3
_CATEGORY_PTS = 1.0

# Quality: flat weighted lexicon — each term has a pre-assigned weight.
# Sum all matching weights, cap at _CEILING.  No branching logic.
_QUALITY_WEIGHTS: dict[str, float] = {
    # --- Theoretical rigor signals ---
    "theorem": 0.50, "proof": 0.50, "proposition": 0.45, "lemma": 0.40,
    "corollary": 0.40, "formal": 0.45, "formal verification": 0.50,
    "axiomatic": 0.45, "derivation": 0.35, "rigorous": 0.40,
    # --- Methodological depth ---
    "principled": 0.45, "methodology": 0.40, "systematic": 0.35,
    "theoretical analysis": 0.50, "theoretical framework": 0.45,
    "complexity": 0.35, "convergence": 0.40, "bound": 0.35,
    "optimal": 0.40, "optimality": 0.45, "guarantee": 0.40,
    # --- Statistical / mathematical ---
    "bayesian": 0.45, "calibration": 0.45, "likelihood": 0.40,
    "probabilistic": 0.40, "estimation": 0.35, "variance": 0.30,
    "bias": 0.30, "statistical": 0.40, "distribution": 0.30,
    # --- Validation methodology ---
    "validate": 0.40, "validation": 0.40, "verify": 0.40,
    "verification": 0.45, "robustness": 0.40, "sensitivity analysis": 0.45,
    "reproducib": 0.40, "fairness": 0.35,
    # --- Technical depth (engineering) ---
    "architecture": 0.30, "framework": 0.30, "algorithm": 0.30,
    "module": 0.20, "pipeline": 0.25, "encoder": 0.25,
    "decoder": 0.25, "backbone": 0.20, "attention mechanism": 0.35,
    "training scheme": 0.20,
    # --- Empirical rigor ---
    "ablation": 0.40, "benchmark": 0.30, "baseline comparison": 0.35,
    "statistical significance": 0.45, "cross-validation": 0.40,
    "human evaluation": 0.45, "error analysis": 0.35,
    # --- Novelty ---
    "first": 0.30, "novel": 0.25, "new": 0.15, "unprecedented": 0.35,
    "breakthrough": 0.40, "pioneering": 0.35, "innovative": 0.25,
    "previously unexplored": 0.35,
    # --- Performance claims ---
    "state-of-the-art": 0.40, "sota": 0.40, "outperform": 0.35,
    "surpass": 0.35, "superior": 0.30, "improves": 0.25,
    "beats": 0.25, "significantly better": 0.35,
    # --- Quantitative evidence ---
    "accuracy": 0.20, "f1 score": 0.25, "bleu": 0.20, "rouge": 0.20,
    "perplexity": 0.20, "auc": 0.20, "recall": 0.15, "precision": 0.15,
}


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

class PaperScorer:
    """Stateless scorer — instantiate once, call ``rank()`` many times."""

    def __init__(
        self,
        domains: dict[str, Any],
        excluded: Sequence[str] = (),
    ) -> None:
        self.domains = domains
        self.excluded = [kw.lower() for kw in excluded]
        # Precompile exclusion patterns for single-pass rejection
        self._excl_pattern = (
            re.compile("|".join(re.escape(e) for e in self.excluded), re.IGNORECASE)
            if self.excluded else None
        )
        # Precompile domain keyword patterns for single-pass matching
        self._domain_patterns: list[tuple[str, re.Pattern[str], list[str], list[str]]] = []
        for name, cfg in domains.items():
            kws = cfg.get("keywords", [])
            cats = cfg.get("arxiv_categories", [])
            if kws:
                pat = re.compile(
                    "|".join(re.escape(kw.lower()) for kw in kws),
                    re.IGNORECASE,
                )
            else:
                pat = re.compile(r"(?!)")  # never matches
            self._domain_patterns.append((name, pat, kws, cats))

    # -- public API ----------------------------------------------------------

    def rank(
        self,
        papers: list[dict[str, Any]],
        *,
        trending: bool = False,
        conference: bool = False,
    ) -> list[dict[str, Any]]:
        """Filter, score, and sort papers.  Returns a new list."""
        results: list[dict[str, Any]] = []
        for p in papers:
            dims = self._evaluate(p, trending=trending, conference=conference)
            if dims is None:
                continue
            p["scores"] = dims
            results.append(p)
        results.sort(key=lambda x: x["scores"]["recommendation"], reverse=True)
        return results

    # -- dimension evaluators ------------------------------------------------

    def _evaluate(
        self,
        paper: dict[str, Any],
        *,
        trending: bool,
        conference: bool,
    ) -> dict[str, Any] | None:
        fit_score, domain, kw = self._fit(paper)
        if fit_score <= 0:
            return None

        pub_dt = self._parse_date(paper)
        fresh = self._freshness(pub_dt)

        citations = paper.get("influentialCitationCount") or 0
        impact = self._impact(citations, pub_dt, trending=trending)

        abstract = paper.get("summary", "") or paper.get("abstract", "")
        rigor = self._rigor(abstract)

        weights = _WEIGHTS_CONF if conference else (
            _WEIGHTS_TRENDING if trending else _WEIGHTS_DEFAULT
        )

        rec_val = 0.0 if conference else fresh
        dims_raw = {"fit": fit_score, "freshness": rec_val, "impact": impact, "rigor": rigor}
        # Linear normalization: simple, transparent, creates natural score spread.
        def _norm(v: float) -> float:
            """Linear mapping from [0, _CEILING] to [0, 10]."""
            if v <= 0:
                return 0.0
            return min(v / _CEILING * 10.0, 10.0)

        rec = round(
            sum(_norm(dims_raw[k]) * weights.get(k, 0) for k in weights),
            2,
        )

        paper["best_domain"] = domain
        paper["domain_keywords"] = kw
        paper["trending"] = trending

        return {
            "fit": round(fit_score, 2),
            "freshness": round(rec_val, 2),
            "impact": round(impact, 2),
            "rigor": round(rigor, 2),
            "recommendation": rec,
        }

    def _fit(
        self, paper: dict[str, Any],
    ) -> tuple[float, str | None, list[str]]:
        """Single-pass keyword matching using precompiled regex patterns."""
        corpus = (
            paper.get("title", "").lower() + "\n"
            + (paper.get("summary", "") or paper.get("abstract", "")).lower()
        )
        title_text = paper.get("title", "").lower()
        cats = set(paper.get("categories", []))

        # Exclusion: single regex test instead of per-keyword loop
        if self._excl_pattern and self._excl_pattern.search(corpus):
            return 0.0, None, []

        # Find which domain keywords appear via regex match positions
        best = 0.0
        best_domain: str | None = None
        best_kw: list[str] = []

        for name, pat, kws, domain_cats in self._domain_patterns:
            pts = 0.0
            matched: list[str] = []
            seen_words: set[str] = set()

            # Count each keyword at most once — title takes priority.
            for m in pat.finditer(corpus):
                matched_word = m.group().lower()
                if matched_word in seen_words:
                    continue
                seen_words.add(matched_word)
                if matched_word in title_text:
                    pts += _TITLE_PTS
                else:
                    pts += _ABSTRACT_PTS
                for kw in kws:
                    if kw.lower() == matched_word and kw not in matched:
                        matched.append(kw)

            for cat in domain_cats:
                if cat in cats:
                    pts += _CATEGORY_PTS
                    matched.append(cat)

            if pts > best:
                best = pts
                best_domain = name
                best_kw = matched

        return min(best, _CEILING), best_domain, best_kw

    @staticmethod
    def _freshness(pub_dt: datetime | None) -> float:
        """Logarithmic freshness decay instead of step-function windows."""
        if pub_dt is None:
            return 0.0
        ref = datetime.now(pub_dt.tzinfo) if pub_dt.tzinfo else datetime.now()
        age_days = max((ref - pub_dt).days, 0)
        if age_days > 365:
            return 0.0
        # Smooth decay: 3.0 at day 0, ~1.0 at 180 days, ~0.0 at 365+
        return round(max(3.0 * (1.0 - age_days / 365.0), 0.0), 2)

    @staticmethod
    def _impact(citations: int, pub_dt: datetime | None, *, trending: bool) -> float:
        if trending:
            return min(citations / 80.0, _CEILING)
        if pub_dt is not None:
            ref = datetime.now(pub_dt.tzinfo) if pub_dt.tzinfo else datetime.now()
            days = (ref - pub_dt).days
            if days <= 10:
                return 2.2
            if days <= 21:
                return 1.6
            if days <= 45:
                return 0.9
        return 0.4

    @staticmethod
    def _rigor(text: str) -> float:
        """Weighted bag-of-words quality scoring.

        Each quality signal term has a pre-assigned weight.  We sum the
        weights of all terms found in the text.  No branching logic —
        pure additive model.
        """
        if not text:
            return 0.0
        low = text.lower()
        total = sum(w for term, w in _QUALITY_WEIGHTS.items() if term in low)
        return min(total, _CEILING)

    @staticmethod
    def _parse_date(paper: dict[str, Any]) -> datetime | None:
        """Parse publication date from multiple field names with fallback."""
        if paper.get("published_date"):
            return paper["published_date"]
        raw = paper.get("publicationDate") or paper.get("published")
        if not raw:
            return None
        # Try ISO format first, then common patterns
        for parser in (
            lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
            lambda s: datetime.strptime(s[:10], "%Y-%m-%d"),
            lambda s: datetime.strptime(s[:7], "%Y-%m"),
            lambda s: datetime.strptime(s[:4], "%Y"),
        ):
            try:
                return parser(raw)
            except (ValueError, TypeError, IndexError):
                continue
        return None


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def score_papers(
    papers: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    is_hot_batch: bool = False,
    is_conf_batch: bool = False,
    is_conf: bool = False,
) -> list[dict[str, Any]]:
    """Filter and score a batch of papers."""
    conference = is_conf_batch or is_conf
    scorer = PaperScorer(
        domains=config.get("research_domains", {}),
        excluded=config.get("excluded_keywords", []),
    )
    return scorer.rank(papers, trending=is_hot_batch, conference=conference)
