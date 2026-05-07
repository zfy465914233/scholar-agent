"""Conference paper search via DBLP + Semantic Scholar enrichment.

Supports CVPR/ICCV/ECCV/ICLR/AAAI/NeurIPS/ICML/ACL/EMNLP/MICCAI.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Any

from academic.scoring import score_papers

logger = logging.getLogger(__name__)

try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ---------------------------------------------------------------------------
# Venue config — derived from DBLP taxonomy and arXiv category mappings
# ---------------------------------------------------------------------------

from dataclasses import dataclass

@dataclass(frozen=True)
class _VenueSpec:
    """DBLP venue specification with optional TOC path and arXiv categories."""
    dblp_prefix: str          # e.g. "conf/cvpr"
    toc_fmt: str | None       # e.g. "cvpr{year}" — None means use venue_query
    venue_label: str          # e.g. "CVPR" — used in venue:year queries
    arxiv_cats: tuple[str, ...] = ()

    def toc_path(self, year: int) -> str | None:
        if not self.toc_fmt:
            return None
        return f"toc:db/{self.dblp_prefix}/{self.toc_fmt.format(year=year)}.bht:"

_CONF_CATALOG: dict[str, _VenueSpec] = {
    "CVPR":    _VenueSpec("conf/cvpr",   "cvpr{year}",    "CVPR",    ("cs.CV",)),
    "ICCV":    _VenueSpec("conf/iccv",   "iccv{year}",    "ICCV",    ("cs.CV",)),
    "ECCV":    _VenueSpec("conf/eccv",   None,            "ECCV",    ("cs.CV",)),
    "ICLR":    _VenueSpec("conf/iclr",   "iclr{year}",    "ICLR",    ("cs.LG", "cs.AI")),
    "AAAI":    _VenueSpec("conf/aaai",   "aaai{year}",    "AAAI",    ("cs.AI",)),
    "NeurIPS": _VenueSpec("conf/nips",   "neurips{year}", "NeurIPS", ("cs.LG", "cs.AI", "cs.CL")),
    "ICML":    _VenueSpec("conf/icml",   "icml{year}",    "ICML",    ("cs.LG",)),
    "MICCAI":  _VenueSpec("conf/miccai", None,            "MICCAI",  ("cs.CV", "eess.IV")),
    "ACL":     _VenueSpec("conf/acl",    "acl{year}",     "ACL",     ("cs.CL",)),
    "EMNLP":   _VenueSpec("conf/emnlp",  None,            "EMNLP",   ("cs.CL",)),
}

_S2_SEARCH_ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"
_S2_PAPER_FIELDS = "externalIds,title,abstract,influentialCitationCount,citationCount,url,authors,authors.affiliations"
_S2_THROTTLE = 30
_S2_KEY = os.environ.get("S2_API_KEY", "")

_DBLP_API = "https://dblp.org/search/publ/api"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fingerprint(text: str) -> str:
    """Normalize text for dedup comparison via slugify."""
    return re.sub(r"[-\s]+", "-", re.sub(r"[^a-z0-9\s-]", "", text.lower())).strip("-")


def _dice_title_overlap(a: str, b: str) -> float:
    """Dice coefficient on normalized title words."""
    def _norm(s: str) -> set[str]:
        return set(re.sub(r"[^a-z0-9\s]", "", s.lower()).strip().split())
    wa = _norm(a)
    wb = _norm(b)
    if not wa or not wb:
        return 0.0
    shared = len(wa & wb)
    return 2.0 * shared / (len(wa) + len(wb))


# ---------------------------------------------------------------------------
# DBLP: separated query builder, fetcher, parser
# ---------------------------------------------------------------------------

def _build_dblp_url(venue_key: str, year: int, offset: int, batch_size: int) -> str | None:
    """Build a DBLP API URL for a given venue/year/offset."""
    spec = _CONF_CATALOG.get(venue_key)
    if not spec:
        return None

    # Prefer TOC-based query, fall back to venue:year
    query = spec.toc_path(year) or f"venue:{spec.venue_label} year:{year}"
    params = {"q": query, "format": "json", "h": batch_size, "f": offset}
    return f"{_DBLP_API}?{urllib.parse.urlencode(params)}"


def _fetch_dblp_page(url: str, max_retries: int = 3) -> dict | None:
    """Fetch and parse a single DBLP API page. Returns parsed JSON or None."""
    for attempt in range(max_retries):
        try:
            if HAS_REQUESTS:
                resp = _requests.get(url, headers={"User-Agent": "ScholarAgent/1.0"}, timeout=60)
                resp.raise_for_status()
                return resp.json()
            else:
                req = urllib.request.Request(url, headers={"User-Agent": "ScholarAgent/1.0"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("dblp request failed try %d/%d: %s", attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(int(1.5 ** attempt * 4))
    return None


def _parse_dblp_hits(data: dict, venue_key: str, year: int) -> tuple[list[dict[str, Any]], int]:
    """Parse DBLP API response into paper dicts. Returns (papers, total_count)."""
    hits = data.get("result", {}).get("hits", {})
    total = int(hits.get("@total", 0))
    hit_list = hits.get("hit", [])

    spec = _CONF_CATALOG.get(venue_key)

    papers: list[dict[str, Any]] = []
    for hit in hit_list:
        info = hit.get("info", {})
        # Normalize title: strip trailing punctuation
        title = info.get("title", "")
        while title.endswith("."):
            title = title[:-1]
        if not title:
            continue

        # Extract author names, normalizing single-author edge case
        raw_authors = info.get("authors", {}).get("author", [])
        if isinstance(raw_authors, dict):
            raw_authors = [raw_authors]
        author_names = [a.get("text", "") for a in raw_authors if a.get("text")]

        papers.append({
            "title": title,
            "authors": author_names,
            "year": int(info.get("year", year)),
            "conference": venue_key,
            "doi": info.get("doi", ""),
            "venue": info.get("venue", venue_key),
            "categories": list(spec.arxiv_cats) if spec else [],
            "dblp_url": info.get("url", ""),
            "source": "dblp",
        })

    return papers, total


def _collect_all_dblp_pages(
    venue_key: str,
    year: int,
    max_results: int = 1000,
) -> list[dict[str, Any]]:
    """Fetch all DBLP pages for a venue/year using offset-based accumulation.

    Instead of generator-based pagination, this collects all pages first,
    then returns the combined list. Uses a fixed delay between pages.
    """
    batch_size = min(max_results, 1000)
    all_papers: list[dict[str, Any]] = []
    offset = 0

    while offset < max_results:
        url = _build_dblp_url(venue_key, year, offset, batch_size)
        if not url:
            break

        logger.info("dblp fetch venue=%s year=%d offset=%d", venue_key, year, offset)
        data = _fetch_dblp_page(url)
        if not data:
            break

        papers, total = _parse_dblp_hits(data, venue_key, year)
        if not papers:
            break

        all_papers.extend(papers)
        offset += len(papers)

        if offset >= total or offset >= max_results:
            break

        time.sleep(1)

    logger.info("dblp venue=%s year=%d collected %d results", venue_key, year, len(all_papers))
    return all_papers


def gather_venue_papers(
    year: int,
    venues: list[str] | None = None,
    max_per_venue: int = 1000,
) -> list[dict[str, Any]]:
    """Search multiple conferences and deduplicate."""
    if venues is None:
        venues = list(_CONF_CATALOG.keys())

    all_papers: list[dict[str, Any]] = []
    seen: set[str] = set()

    for venue in venues:
        batch = _collect_all_dblp_pages(venue, year, max_per_venue)
        for p in batch:
            fp = _fingerprint(p["title"])
            if fp and fp not in seen:
                seen.add(fp)
                all_papers.append(p)
        time.sleep(1)

    return all_papers


# ---------------------------------------------------------------------------
# Semantic Scholar: two-phase enrichment
# ---------------------------------------------------------------------------

def _batch_search_s2(
    titles: list[str],
    headers: dict,
    per_query: int = 3,
) -> dict[str, dict]:
    """Phase 1: Search S2 for all titles, return {title_lower: best_match}.

    Groups titles into batches and searches concurrently. Caches all results
    for Phase 2 matching.
    """
    cache: dict[str, dict] = {}

    for title in titles:
        if not title:
            continue
        params = {"query": title, "limit": per_query, "fields": _S2_PAPER_FIELDS}

        for attempt in range(3):
            try:
                resp = _requests.get(_S2_SEARCH_ENDPOINT, params=params, headers=headers, timeout=15)
                if resp.status_code == 429:
                    logger.warning("s2 throttled...")
                    time.sleep(_S2_THROTTLE)
                    continue
                resp.raise_for_status()
                data = resp.json()

                results = data.get("data", [])
                if results:
                    best = max(results, key=lambda r: _dice_title_overlap(title, r.get("title", "")))
                    sim = _dice_title_overlap(title, best.get("title", ""))
                    if sim >= 0.55:
                        best["_similarity"] = round(sim, 2)
                        cache[title.lower()] = best
                break

            except Exception as e:
                msg = str(e)
                if "429" in msg:
                    logger.warning("s2 throttled...")
                    time.sleep(_S2_THROTTLE)
                elif attempt < 2:
                    time.sleep(2 ** attempt)

    return cache


def _extract_s2_fields(match: dict) -> dict[str, Any]:
    """Extract structured fields from an S2 match result."""
    result: dict[str, Any] = {
        "abstract": match.get("abstract"),
        "citationCount": match.get("citationCount") or 0,
        "influentialCitationCount": match.get("influentialCitationCount") or 0,
        "s2_url": match.get("url", ""),
        "s2_matched": True,
        "s2_similarity": match.get("_similarity", 0.0),
    }

    ext = match.get("externalIds") or {}
    if ext.get("ArXiv"):
        result["arxiv_id"] = ext["ArXiv"]
    if ext.get("DOI"):
        result["doi_ext"] = ext["DOI"]

    if match.get("authors"):
        seen_affs: set[str] = set()
        for author_entry in match["authors"]:
            raw = author_entry.get("affiliations")
            if not raw:
                continue
            for aff in raw:
                label = aff["name"] if isinstance(aff, dict) and "name" in aff else (str(aff) if aff else "")
                label = label.strip()
                if label and label not in seen_affs:
                    seen_affs.add(label)
        if seen_affs:
            result["affiliations"] = list(seen_affs)

    return result


def _set_default_s2_fields(paper: dict) -> None:
    paper.setdefault("abstract", None)
    paper.setdefault("citationCount", 0)
    paper.setdefault("influentialCitationCount", 0)
    paper["s2_matched"] = False


def enrich_paper_batch(papers: list[dict[str, Any]], max_retries: int = 3) -> list[dict[str, Any]]:
    """Two-phase enrichment: batch search all titles first, then match.

    Phase 1: Search S2 for all titles and cache results.
    Phase 2: Match each paper against the cache.

    This avoids per-paper sequential search+match interleaving.
    """
    if not HAS_REQUESTS:
        logger.warning("s2 enrich skipped: requests library missing")
        for p in papers:
            _set_default_s2_fields(p)
        return papers

    headers = {"User-Agent": "ScholarAgent/1.0"}
    if _S2_KEY:
        headers["x-api-key"] = _S2_KEY

    # Phase 1: Batch search all titles
    titles = [p.get("title", "") for p in papers]
    logger.info("s2 phase 1: searching %d titles", len(titles))
    cache = _batch_search_s2(titles, headers)

    # Phase 2: Match papers against cache
    logger.info("s2 phase 2: matching against %d cached results", len(cache))
    for paper in papers:
        title = paper.get("title", "")
        if not title:
            _set_default_s2_fields(paper)
            continue

        match = cache.get(title.lower())
        if match:
            extras = _extract_s2_fields(match)
            doi_ext = extras.pop("doi_ext", None)
            paper.update(extras)
            if doi_ext and not paper.get("doi"):
                paper["doi"] = doi_ext
        else:
            _set_default_s2_fields(paper)

    return papers


# ---------------------------------------------------------------------------
# Conference search pipeline
# ---------------------------------------------------------------------------

def search_and_score_conferences(
    config: dict[str, Any],
    year: int,
    venues: list[str] | None = None,
    keywords: list[str] | None = None,
    excluded_keywords: list[str] | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """Full conference search -> keyword filter -> S2 enrich -> score pipeline."""
    # Step 1: DBLP search
    all_papers = gather_venue_papers(year, venues)

    # Step 2: lightweight keyword filter
    kws = set(kw.lower() for kw in (keywords or []))
    excl = set(kw.lower() for kw in (excluded_keywords or []))

    if kws or excl:
        filtered: list[dict[str, Any]] = []
        for p in all_papers:
            tl = p["title"].lower()
            if any(ex in tl for ex in excl):
                continue
            if kws and not any(kw in tl for kw in kws):
                continue
            filtered.append(p)
        logger.info("conference keyword filter: %d -> %d", len(all_papers), len(filtered))
        all_papers = filtered

    if not all_papers:
        return {"papers": [], "year": year, "total_found": 0}

    # Step 3: S2 enrichment
    enriched = enrich_paper_batch(all_papers[:100])  # limit to avoid rate limits

    # Step 4: Score
    scored = score_papers(enriched, config, is_conf_batch=True)

    return {
        "papers": scored[:top_n],
        "year": year,
        "total_found": len(scored),
    }


# ---------------------------------------------------------------------------
# Multi-year conference search (for daily_recommend dual-track)
# ---------------------------------------------------------------------------

def search_conferences_multi_year(
    config: dict[str, Any],
    years: list[int] | None = None,
    venues: list[str] | None = None,
    max_enrich: int = 100,
) -> list[dict[str, Any]]:
    """Search top conferences across multiple years, enrich, and relevance-filter.

    Returns papers ranked by impact: influentialCitationCount / (years_since + 1).
    """
    from academic.scoring import PaperScorer

    now_year = __import__("datetime").datetime.now().year
    if years is None:
        years = list(range(2020, now_year + 1))
    if venues is None:
        venues = ["NeurIPS", "ICML", "ICLR", "CVPR", "ACL"]

    # 1. DBLP search per year
    all_papers: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for year in years:
        batch = gather_venue_papers(year, venues, max_per_venue=200)
        for p in batch:
            fp = _fingerprint(p["title"])
            if fp and fp not in seen_titles:
                seen_titles.add(fp)
                all_papers.append(p)

    if not all_papers:
        return []

    logger.info("multi-year conference scan: %d papers across %d years", len(all_papers), len(years))

    # 2. S2 enrichment (cap to keep runtime low)
    enriched = enrich_paper_batch(all_papers[:max_enrich])

    # 3. Relevance filter -- drop papers with 0 relevance
    domains = config.get("research_domains", {})
    excluded = config.get("excluded_keywords", [])
    scorer = PaperScorer(domains=domains, excluded=excluded)
    relevant: list[dict[str, Any]] = []
    for p in enriched:
        score, domain, keywords = scorer._fit(p)
        if score > 0:
            p["_relevance_score"] = score
            p["best_domain"] = domain
            p["domain_keywords"] = keywords
            relevant.append(p)

    if not relevant:
        return []

    # 4. Impact ranking: influentialCitationCount / (years_since + 1)
    for p in relevant:
        inf = p.get("influentialCitationCount") or 0
        pub_year = p.get("year", now_year)
        years_since = max(now_year - int(pub_year), 0)
        p["_impact_score"] = inf / (years_since + 1)

    relevant.sort(key=lambda x: x.get("_impact_score", 0), reverse=True)
    return relevant
