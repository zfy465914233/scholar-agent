"""Four-dimensional paper scoring engine for academic research.

Dimensions:
  - Relevance: keyword matching against research interests
  - Recency: time-based freshness scoring
  - Popularity: citation-based influence metrics
  - Quality: heuristic quality from abstract text

Adapted from evil-read-arxiv/start-my-day/scripts/search_arxiv.py
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring constants — edit here to tune weights
# ---------------------------------------------------------------------------

SCORE_MAX = 3.0

# Relevance
RELEVANCE_TITLE_KEYWORD_BOOST = 0.5
RELEVANCE_SUMMARY_KEYWORD_BOOST = 0.3
RELEVANCE_CATEGORY_MATCH_BOOST = 1.0

# Recency thresholds (days → score)
RECENCY_THRESHOLDS: list[tuple[int, float]] = [
    (30, 3.0),
    (90, 2.0),
    (180, 1.0),
]
RECENCY_DEFAULT = 0.0

# Popularity: influential citations needed for full score
POPULARITY_INFLUENTIAL_CITATION_FULL_SCORE = 100

# Weight profiles
WEIGHTS_NORMAL: dict[str, float] = {
    "relevance": 0.40,
    "recency": 0.20,
    "popularity": 0.30,
    "quality": 0.10,
}
WEIGHTS_HOT: dict[str, float] = {
    "relevance": 0.35,
    "recency": 0.10,
    "popularity": 0.45,
    "quality": 0.10,
}
WEIGHTS_CONF: dict[str, float] = {
    "relevance": 0.40,
    "popularity": 0.40,
    "quality": 0.20,
}


# ---------------------------------------------------------------------------
# Individual dimension scorers
# ---------------------------------------------------------------------------

def calculate_relevance_score(
    paper: dict[str, Any],
    domains: dict[str, Any],
    excluded_keywords: list[str],
) -> tuple[float, str | None, list[str]]:
    """Score relevance against user research interests.

    Returns (score, best_matching_domain, matched_keywords).
    """
    title = paper.get("title", "").lower()
    summary = (
        paper.get("summary", "") or paper.get("abstract", "")
    ).lower()
    categories = set(paper.get("categories", []))

    for kw in excluded_keywords:
        kw_lower = kw.lower()
        if kw_lower in title or kw_lower in summary:
            return 0.0, None, []

    best_score = 0.0
    best_domain: str | None = None
    best_keywords: list[str] = []

    for domain_name, domain_cfg in domains.items():
        score = 0.0
        matched: list[str] = []

        for keyword in domain_cfg.get("keywords", []):
            kw_lower = keyword.lower()
            if kw_lower in title:
                score += RELEVANCE_TITLE_KEYWORD_BOOST
                matched.append(keyword)
            elif kw_lower in summary:
                score += RELEVANCE_SUMMARY_KEYWORD_BOOST
                matched.append(keyword)

        for cat in domain_cfg.get("arxiv_categories", []):
            if cat in categories:
                score += RELEVANCE_CATEGORY_MATCH_BOOST
                matched.append(cat)

        if score > best_score:
            best_score = score
            best_domain = domain_name
            best_keywords = matched

    return min(best_score, SCORE_MAX), best_domain, best_keywords


def calculate_recency_score(published_date: datetime | None) -> float:
    """Score based on publication freshness."""
    if published_date is None:
        return 0.0
    now = (
        datetime.now(published_date.tzinfo)
        if published_date.tzinfo
        else datetime.now()
    )
    days_diff = (now - published_date).days
    for max_days, score in RECENCY_THRESHOLDS:
        if days_diff <= max_days:
            return score
    return RECENCY_DEFAULT


def calculate_popularity_score(
    influential_citations: int,
    published_date: datetime | None,
    is_hot: bool = False,
) -> float:
    """Score based on citation influence."""
    if is_hot:
        return min(
            influential_citations / (POPULARITY_INFLUENTIAL_CITATION_FULL_SCORE / SCORE_MAX),
            SCORE_MAX,
        )
    # For non-hot papers, estimate from recency
    if published_date is not None:
        now = (
            datetime.now(published_date.tzinfo)
            if published_date.tzinfo
            else datetime.now()
        )
        days_old = (now - published_date).days
        if days_old <= 7:
            return 2.0
        if days_old <= 14:
            return 1.5
        if days_old <= 30:
            return 1.0
    return 0.5


def calculate_quality_score(summary: str) -> float:
    """Heuristic quality score from abstract text."""
    if not summary:
        return 0.0
    score = 0.0
    text = summary.lower()

    strong_innovation = [
        "state-of-the-art", "sota", "breakthrough", "first",
        "surpass", "outperform", "pioneering",
    ]
    weak_innovation = [
        "novel", "propose", "introduce", "new approach",
        "new method", "innovative",
    ]
    method_indicators = [
        "framework", "architecture", "algorithm", "mechanism",
        "pipeline", "end-to-end",
    ]
    quantitative = [
        "outperforms", "improves by", "achieves", "accuracy",
        "f1", "bleu", "rouge", "beats", "surpasses",
    ]
    experiment = [
        "experiment", "evaluation", "benchmark", "ablation",
        "baseline", "comparison",
    ]

    strong_count = sum(1 for w in strong_innovation if w in text)
    if strong_count >= 2:
        score += 1.0
    elif strong_count == 1:
        score += 0.7
    elif any(w in text for w in weak_innovation):
        score += 0.3

    if any(w in text for w in method_indicators):
        score += 0.5

    if any(w in text for w in quantitative):
        score += 0.8
    elif any(w in text for w in experiment):
        score += 0.4

    return min(score, SCORE_MAX)


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

def calculate_recommendation_score(
    relevance: float,
    recency: float,
    popularity: float,
    quality: float,
    *,
    is_hot: bool = False,
    is_conf: bool = False,
) -> float:
    """Weighted composite score (0–10 scale)."""
    dims = {
        "relevance": relevance,
        "recency": recency,
        "popularity": popularity,
        "quality": quality,
    }
    if is_conf:
        weights = WEIGHTS_CONF
        # Conference papers: recency is not meaningful (year is user-specified)
        dims["recency"] = 0.0
    elif is_hot:
        weights = WEIGHTS_HOT
    else:
        weights = WEIGHTS_NORMAL

    normalized = {k: (v / SCORE_MAX) * 10 for k, v in dims.items()}
    return round(sum(normalized[k] * weights.get(k, 0) for k in weights), 2)


def score_papers(
    papers: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    is_hot_batch: bool = False,
    is_conf_batch: bool = False,
) -> list[dict[str, Any]]:
    """Filter and score a batch of papers.

    Papers scoring 0 relevance are dropped. Surviving papers receive a
    ``scores`` dict and are sorted by recommendation score descending.
    """
    domains = config.get("research_domains", {})
    excluded = config.get("excluded_keywords", [])

    scored: list[dict[str, Any]] = []
    for paper in papers:
        relevance, matched_domain, matched_kw = calculate_relevance_score(
            paper, domains, excluded,
        )
        if relevance == 0:
            continue

        # Parse publication date
        pub_date: datetime | None = None
        if "published_date" in paper and paper["published_date"]:
            pub_date = paper["published_date"]
        else:
            pub_str = paper.get("publicationDate")
            if pub_str:
                for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
                    try:
                        pub_date = datetime.strptime(pub_str, fmt)
                        break
                    except (ValueError, TypeError):
                        continue

        recency = calculate_recency_score(pub_date)

        inf_cit = paper.get("influentialCitationCount") or 0
        popularity = calculate_popularity_score(inf_cit, pub_date, is_hot=is_hot_batch)

        summary = paper.get("summary", "") or paper.get("abstract", "")
        quality = calculate_quality_score(summary)

        recommendation = calculate_recommendation_score(
            relevance, recency, popularity, quality,
            is_hot=is_hot_batch, is_conf=is_conf_batch,
        )

        paper["scores"] = {
            "relevance": round(relevance, 2),
            "recency": round(recency, 2),
            "popularity": round(popularity, 2),
            "quality": round(quality, 2),
            "recommendation": recommendation,
        }
        paper["matched_domain"] = matched_domain
        paper["matched_keywords"] = matched_kw
        paper["is_hot_paper"] = is_hot_batch

        scored.append(paper)

    scored.sort(key=lambda p: p["scores"]["recommendation"], reverse=True)
    return scored
