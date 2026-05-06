"""Paper scoring engine — class-based multi-dimensional ranking.

Evaluates academic papers across four dimensions (fit, freshness, impact,
rigor), combines them into a weighted recommendation score, and filters
out papers that match exclusion rules.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------

_CAP = 3.0  # per-dimension ceiling

# Dimension weight profiles (keys must match _DIM_NAMES order)
_WEIGHTS_DEFAULT: dict[str, float] = {
    "fit": 0.40,
    "freshness": 0.20,
    "impact": 0.30,
    "rigor": 0.10,
}
_WEIGHTS_TRENDING: dict[str, float] = {
    "fit": 0.35,
    "freshness": 0.10,
    "impact": 0.45,
    "rigor": 0.10,
}
WEIGHTS_CONF: dict[str, float] = {
    "fit": 0.40,
    "impact": 0.40,
    "rigor": 0.20,
}

# Relevance tuning
_TITLE_HIT = 0.5
_ABSTRACT_HIT = 0.3
_CATEGORY_HIT = 1.0

# Recency bands (max_age_days → score)
_FRESH_BANDS: list[tuple[int, float]] = [
    (30, 3.0),
    (90, 2.0),
    (180, 1.0),
]

# Quality signal patterns (lowercased)
_STRONG_CLAIMS = [
    "state-of-the-art", "sota", "breakthrough", "first",
    "surpass", "outperform", "pioneering",
]
_MODERATE_CLAIMS = [
    "novel", "propose", "introduce", "new approach",
    "new method", "innovative",
]
_METHOD_SIGNALS = [
    "framework", "architecture", "algorithm", "mechanism",
    "pipeline", "end-to-end",
]
_QUANT_SIGNALS = [
    "outperforms", "improves by", "achieves", "accuracy",
    "f1", "bleu", "rouge", "beats", "surpasses",
]
_EVAL_SIGNALS = [
    "experiment", "evaluation", "benchmark", "ablation",
    "baseline", "comparison",
]


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
        rec = round(
            sum((dims_raw[k] / _CAP) * 10 * weights.get(k, 0) for k in weights),
            2,
        )

        paper["matched_domain"] = domain
        paper["matched_keywords"] = kw
        paper["is_hot_paper"] = trending

        return {
            "relevance": round(fit_score, 2),
            "recency": round(rec_val, 2),
            "popularity": round(impact, 2),
            "quality": round(rigor, 2),
            "recommendation": rec,
        }

    def _fit(
        self, paper: dict[str, Any],
    ) -> tuple[float, str | None, list[str]]:
        """Keyword / category relevance."""
        title = paper.get("title", "").lower()
        abstract = (paper.get("summary", "") or paper.get("abstract", "")).lower()
        cats = set(paper.get("categories", []))

        # exclusion gate
        for ex in self.excluded:
            if ex in title or ex in abstract:
                return 0.0, None, []

        best = 0.0
        best_domain: str | None = None
        best_kw: list[str] = []

        for name, cfg in self.domains.items():
            pts = 0.0
            matched: list[str] = []
            for kw in cfg.get("keywords", []):
                lk = kw.lower()
                if lk in title:
                    pts += _TITLE_HIT
                    matched.append(kw)
                elif lk in abstract:
                    pts += _ABSTRACT_HIT
                    matched.append(kw)
            for cat in cfg.get("arxiv_categories", []):
                if cat in cats:
                    pts += _CATEGORY_HIT
                    matched.append(cat)
            if pts > best:
                best = pts
                best_domain = name
                best_kw = matched

        return min(best, _CAP), best_domain, best_kw

    @staticmethod
    def _freshness(pub_dt: datetime | None) -> float:
        if pub_dt is None:
            return 0.0
        ref = datetime.now(pub_dt.tzinfo) if pub_dt.tzinfo else datetime.now()
        age = (ref - pub_dt).days
        for ceiling, score in _FRESH_BANDS:
            if age <= ceiling:
                return score
        return 0.0

    @staticmethod
    def _impact(citations: int, pub_dt: datetime | None, *, trending: bool) -> float:
        if trending:
            return min(citations / (_CAP * 33.3), _CAP)
        if pub_dt is not None:
            ref = datetime.now(pub_dt.tzinfo) if pub_dt.tzinfo else datetime.now()
            days = (ref - pub_dt).days
            if days <= 7:
                return 2.0
            if days <= 14:
                return 1.5
            if days <= 30:
                return 1.0
        return 0.5

    @staticmethod
    def _rigor(text: str) -> float:
        if not text:
            return 0.0
        low = text.lower()
        pts = 0.0
        strong = sum(1 for s in _STRONG_CLAIMS if s in low)
        if strong >= 2:
            pts += 1.0
        elif strong == 1:
            pts += 0.7
        elif any(s in low for s in _MODERATE_CLAIMS):
            pts += 0.3
        if any(s in low for s in _METHOD_SIGNALS):
            pts += 0.5
        if any(s in low for s in _QUANT_SIGNALS):
            pts += 0.8
        elif any(s in low for s in _EVAL_SIGNALS):
            pts += 0.4
        return min(pts, _CAP)

    @staticmethod
    def _parse_date(paper: dict[str, Any]) -> datetime | None:
        if paper.get("published_date"):
            return paper["published_date"]
        raw = paper.get("publicationDate")
        if not raw:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
            try:
                return datetime.strptime(raw, fmt)
            except (ValueError, TypeError):
                continue
        return None


# ---------------------------------------------------------------------------
# Module-level convenience (backward compatible)
# ---------------------------------------------------------------------------

# Keep the old names as thin wrappers so existing callers keep working.
_WEIGHTS_NORMAL = _WEIGHTS_DEFAULT
_WEIGHTS_HOT = _WEIGHTS_TRENDING


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
