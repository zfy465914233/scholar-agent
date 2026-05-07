"""arXiv search provider for the Scholar Agent search pipeline.

Wraps the ``academic.arxiv_search`` module to implement the
:class:`SearchProvider` protocol, making arXiv + Semantic Scholar
paper search available alongside other search backends.

Usage::

    from search_providers.arxiv_provider import ArxivProvider

    provider = ArxivProvider()
    result = provider.search("transformer attention mechanism", limit=10)
    for candidate in result.candidates:
        print(candidate.title, candidate.url)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any

from common import normalize_date
from search_providers.base import ProviderResult, SearchCandidate, SearchProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults & configuration
# ---------------------------------------------------------------------------

DEFAULT_CATEGORIES: list[str] = ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]

DEFAULT_MAX_RESULTS = 200       # max papers from arXiv Atom API
DEFAULT_RECENT_DAYS = 30        # look-back window for recent papers
DEFAULT_HOT_DAYS = 365          # look-back window for hot / influential papers


class ArxivProvider(SearchProvider):
    """SearchProvider backed by the arXiv + Semantic Scholar hybrid engine.

    Parameters
    ----------
    categories : list[str] | None
        arXiv category codes used for filtering (e.g. ``["cs.AI", "cs.LG"]``).
        Falls back to the ``ARXIV_CATEGORIES`` environment variable or a
        sensible default covering AI / ML / NLP / CV.
    max_results : int
        Upper bound on the number of raw papers fetched from the arXiv API
        per query.
    recent_days : int
        Number of days back to search for *recent* arXiv submissions.
    hot_days : int
        Number of days back to search for *high-influence* papers via
        Semantic Scholar.
    include_hot : bool
        Whether to also query Semantic Scholar for influential / highly-cited
        papers in addition to the arXiv recent-submission search.
    scoring_config : dict[str, Any] | None
        Optional research-interests config forwarded to
        :func:`academic.scoring.score_papers`.  When *None* a lightweight
        default is constructed from the provider's categories.
    """

    provider_name = "arxiv"

    def __init__(
        self,
        categories: list[str] | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
        recent_days: int = DEFAULT_RECENT_DAYS,
        hot_days: int = DEFAULT_HOT_DAYS,
        include_hot: bool = True,
        scoring_config: dict[str, Any] | None = None,
    ) -> None:
        self.categories = categories or _env_categories()
        self.max_results = max_results
        self.recent_days = recent_days
        self.hot_days = hot_days
        self.include_hot = include_hot
        self.scoring_config = scoring_config or _default_scoring_config(self.categories)

    # ------------------------------------------------------------------
    # SearchProvider interface
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int | None = None) -> ProviderResult:
        """Search arXiv (and optionally Semantic Scholar) for academic papers.

        The *query* string is used as the Semantic Scholar query text.  For
        the arXiv Atom API the provider's configured *categories* are used as
        the primary filter.

        Parameters
        ----------
        query : str
            Free-text search query (e.g. ``"large language model"``).
        limit : int | None
            Maximum number of :class:`SearchCandidate` items to return.
            *None* means no hard cap (all found candidates are returned).

        Returns
        -------
        ProviderResult
            Container with provider name, original query, candidate list,
            and metadata about the search.
        """
        if limit is not None and limit <= 0:
            return ProviderResult(provider=self.provider_name, query=query)

        now = datetime.now()
        recent_start = now - timedelta(days=self.recent_days)
        hot_start = now - timedelta(days=self.hot_days)

        candidates: list[SearchCandidate] = []
        seen_urls: set[str] = set()

        # --- Phase 1: recent arXiv submissions by category ---------------
        try:
            raw_arxiv = _search_arxiv_raw(
                categories=self.categories,
                start_date=recent_start,
                end_date=now,
                max_results=self.max_results,
            )
            candidates, seen_urls = _extend_candidates(
                query, raw_arxiv, candidates, seen_urls, limit,
            )
        except Exception:
            logger.warning("arXiv search failed for query '%s'", query, exc_info=True)

        if limit is not None and len(candidates) >= limit:
            return _make_result(query, candidates, metadata_extra={"phase": "arxiv_recent"})

        # --- Phase 2: Semantic Scholar keyword query ---------------------
        if self.include_hot:
            try:
                raw_s2 = _search_semantic_scholar_raw(
                    query=query,
                    start_date=hot_start,
                    end_date=now,
                )
                candidates, seen_urls = _extend_candidates(
                    query, raw_s2, candidates, seen_urls, limit,
                )
            except Exception:
                logger.warning(
                    "Semantic Scholar search failed for query '%s'", query, exc_info=True,
                )

        return _make_result(query, candidates)


# ======================================================================
# Module-level helper functions
# ======================================================================

def _env_categories() -> list[str]:
    """Read arXiv categories from the ``ARXIV_CATEGORIES`` env var."""
    raw = os.environ.get("ARXIV_CATEGORIES", "")
    if raw.strip():
        return [c.strip() for c in raw.split(",") if c.strip()]
    return list(DEFAULT_CATEGORIES)


def _default_scoring_config(categories: list[str]) -> dict[str, Any]:
    """Build a minimal scoring config from category codes."""
    keywords: list[str] = []
    from academic.arxiv_search import _CATEGORY_PHRASES

    for cat in categories:
        kw = _CATEGORY_PHRASES.get(cat, "")
        if kw:
            keywords.extend(kw.split())

    return {
        "research_domains": {
            "default": {
                "keywords": list(dict.fromkeys(keywords))[:10],
                "arxiv_categories": categories,
                "priority": 3,
            },
        },
        "excluded_keywords": [],
    }


# ----------------------------------------------------------------------
# Thin wrappers that delegate to ``academic.arxiv_search`` but normalise
# the output so it can be consumed by the provider pipeline.
# ----------------------------------------------------------------------

def _search_arxiv_raw(
    categories: list[str],
    start_date: datetime,
    end_date: datetime,
    max_results: int = 200,
) -> list[dict[str, Any]]:
    """Fetch recent arXiv papers and normalise to candidate dicts."""
    from academic.arxiv_search import query_arxiv as _search

    papers = _search(categories, start_date, end_date, limit=max_results)
    return [
        {
            "url": p.get("url") or p.get("id", ""),
            "title": p.get("title", ""),
            "content": p.get("summary", ""),
            "publishedDate": p.get("published", ""),
            "source": "arxiv",
        }
        for p in papers
        if p.get("title")  # skip entries without a title
    ]


def _search_semantic_scholar_raw(
    query: str,
    start_date: datetime,
    end_date: datetime,
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """Fetch Semantic Scholar papers and normalise to candidate dicts."""
    from academic.arxiv_search import query_semantic_scholar as _search

    papers = _search(query, start_date, end_date, top_k=top_k)
    return [
        {
            "url": p.get("url") or f"https://doi.org/{p['externalIds']['DOI']}"
            if (p.get("externalIds") or {}).get("DOI")
            else p.get("url", ""),
            "title": p.get("title", ""),
            "content": p.get("abstract", ""),
            "publishedDate": p.get("publicationDate", ""),
            "source": "semantic_scholar",
        }
        for p in papers
        if p.get("title")
    ]


# ----------------------------------------------------------------------
# Candidate list builder (mirrors AcademicProvider pattern)
# ----------------------------------------------------------------------

def _extend_candidates(
    query: str,
    raw_items: list[dict[str, Any]],
    candidates: list[SearchCandidate],
    seen_urls: set[str],
    limit: int | None,
) -> tuple[list[SearchCandidate], set[str]]:
    """Append *raw_items* to *candidates*, deduplicating by URL."""
    for item in raw_items:
        url = (item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        candidates.append(
            SearchCandidate(
                query=query,
                url=url,
                title=(item.get("title") or url).strip(),
                snippet=(item.get("content") or "").strip(),
                published_at=normalize_date(item.get("publishedDate")),
            )
        )

        if limit is not None and len(candidates) >= limit:
            break

    return candidates, seen_urls


def _make_result(
    query: str,
    candidates: list[SearchCandidate],
    metadata_extra: dict[str, Any] | None = None,
) -> ProviderResult:
    """Build a :class:`ProviderResult` with standard metadata."""
    meta: dict[str, Any] = {"source_count": len(candidates)}
    if metadata_extra:
        meta.update(metadata_extra)
    return ProviderResult(
        provider=ArxivProvider.provider_name,
        query=query,
        candidates=candidates,
        metadata=meta,
    )
