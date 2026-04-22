"""Conference paper search via DBLP + Semantic Scholar enrichment.

Supports CVPR/ICCV/ECCV/ICLR/AAAI/NeurIPS/ICML/ACL/EMNLP/MICCAI.

Adapted from evil-read-arxiv/conf-papers/scripts/search_conf_papers.py
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
# Venue config
# ---------------------------------------------------------------------------

DBLP_VENUES: dict[str, dict[str, Any]] = {
    "CVPR": {"toc": "conf/cvpr", "toc_name": "cvpr{year}"},
    "ICCV": {"toc": "conf/iccv", "toc_name": "iccv{year}"},
    "ECCV": {"toc": "conf/eccv", "toc_name": None, "venue_query": "ECCV"},
    "ICLR": {"toc": "conf/iclr", "toc_name": "iclr{year}"},
    "AAAI": {"toc": "conf/aaai", "toc_name": "aaai{year}"},
    "NeurIPS": {"toc": "conf/nips", "toc_name": "neurips{year}"},
    "ICML": {"toc": "conf/icml", "toc_name": "icml{year}"},
    "MICCAI": {"toc": "conf/miccai", "toc_name": None, "venue_query": "MICCAI"},
    "ACL": {"toc": "conf/acl", "toc_name": "acl{year}"},
    "EMNLP": {"toc": "conf/emnlp", "toc_name": None, "venue_query": "EMNLP"},
}

VENUE_TO_CATEGORIES: dict[str, list[str]] = {
    "CVPR": ["cs.CV"],
    "ICCV": ["cs.CV"],
    "ECCV": ["cs.CV"],
    "ICLR": ["cs.LG", "cs.AI"],
    "ICML": ["cs.LG"],
    "NeurIPS": ["cs.LG", "cs.AI", "cs.CL"],
    "AAAI": ["cs.AI"],
    "MICCAI": ["cs.CV", "eess.IV"],
    "ACL": ["cs.CL"],
    "EMNLP": ["cs.CL"],
}

S2_API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "title,abstract,citationCount,influentialCitationCount,externalIds,url,authors,authors.affiliations"
S2_RATE_LIMIT_WAIT = 30
S2_API_KEY = os.environ.get("S2_API_KEY", "")

DBLP_API_URL = "https://dblp.org/search/publ/api"


# ---------------------------------------------------------------------------
# DBLP search
# ---------------------------------------------------------------------------

def search_dblp_conference(
    venue_key: str,
    year: int,
    max_results: int = 1000,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """Search DBLP for papers from a specific conference/year."""
    venue_info = DBLP_VENUES.get(venue_key)
    if not venue_info:
        logger.warning("[DBLP] Unknown venue: %s", venue_key)
        return []

    # Build query list
    queries: list[str] = []
    toc_name = venue_info.get("toc_name")
    if toc_name:
        toc_path = venue_info["toc"]
        queries.append(f"toc:db/{toc_path}/{toc_name.format(year=year)}.bht:")
    queries.append(f"venue:{venue_info.get('venue_query', venue_key)} year:{year}")

    for query_str in queries:
        papers: list[dict[str, Any]] = []
        offset = 0
        batch_size = min(max_results, 1000)

        while offset < max_results:
            params = {"q": query_str, "format": "json", "h": batch_size, "f": offset}
            url = f"{DBLP_API_URL}?{urllib.parse.urlencode(params)}"
            logger.info("[DBLP] %s %d (offset=%d)", venue_key, year, offset)

            success = False
            for attempt in range(max_retries):
                try:
                    if HAS_REQUESTS:
                        resp = _requests.get(url, headers={"User-Agent": "ScholarAgent/1.0"}, timeout=60)
                        resp.raise_for_status()
                        data = resp.json()
                    else:
                        req = urllib.request.Request(url, headers={"User-Agent": "ScholarAgent/1.0"})
                        with urllib.request.urlopen(req, timeout=60) as resp:
                            data = json.loads(resp.read().decode("utf-8"))

                    hits = data.get("result", {}).get("hits", {})
                    total = int(hits.get("@total", 0))
                    hit_list = hits.get("hit", [])

                    if not hit_list:
                        if papers:
                            return papers
                        break  # Try next query

                    for hit in hit_list:
                        info = hit.get("info", {})
                        title = info.get("title", "").rstrip(".")
                        if not title:
                            continue
                        authors_info = info.get("authors", {}).get("author", [])
                        if isinstance(authors_info, dict):
                            authors_info = [authors_info]
                        authors = [a.get("text", "") for a in authors_info if a.get("text")]

                        papers.append({
                            "title": title,
                            "authors": authors,
                            "dblp_url": info.get("url", ""),
                            "year": int(info.get("year", year)),
                            "conference": venue_key,
                            "doi": info.get("doi", ""),
                            "venue": info.get("venue", venue_key),
                            "source": "dblp",
                            "categories": VENUE_TO_CATEGORIES.get(venue_key, []),
                        })

                    offset += len(hit_list)
                    success = True
                    break  # success, exit retry loop

                except Exception as e:
                    logger.warning("[DBLP] Error (attempt %d/%d): %s", attempt + 1, max_retries, e)
                    if attempt < max_retries - 1:
                        time.sleep((2 ** attempt) * 3)

            if not success:
                break  # All retries failed, stop paginating

            if offset >= total or offset >= max_results:
                break

            time.sleep(1)

        if papers:
            logger.info("[DBLP] %s %d: found %d papers", venue_key, year, len(papers))
            return papers

    return []


def search_all_conferences(
    year: int,
    venues: list[str] | None = None,
    max_per_venue: int = 1000,
) -> list[dict[str, Any]]:
    """Search multiple conferences and deduplicate."""
    if venues is None:
        venues = list(DBLP_VENUES.keys())

    all_papers: list[dict[str, Any]] = []
    seen: set[str] = set()

    for venue in venues:
        papers = search_dblp_conference(venue, year, max_per_venue)
        for p in papers:
            tn = re.sub(r"[^a-z0-9\s]", "", p["title"].lower()).strip()
            if tn and tn not in seen:
                seen.add(tn)
                all_papers.append(p)
        time.sleep(1)

    return all_papers


# ---------------------------------------------------------------------------
# Semantic Scholar enrichment
# ---------------------------------------------------------------------------

def _title_similarity(a: str, b: str) -> float:
    """Jaccard similarity on normalized title words."""
    def _norm(s: str) -> set[str]:
        return set(re.sub(r"[^a-z0-9\s]", "", s.lower()).strip().split())
    wa = _norm(a)
    wb = _norm(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def enrich_with_semantic_scholar(
    papers: list[dict[str, Any]],
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """Enrich DBLP papers with S2 data (abstract, citations, arxiv_id)."""
    if not HAS_REQUESTS:
        logger.warning("[S2] requests not available, skipping enrichment")
        for p in papers:
            p.setdefault("abstract", None)
            p.setdefault("citationCount", 0)
            p.setdefault("influentialCitationCount", 0)
            p["s2_matched"] = False
        return papers

    headers = {"User-Agent": "ScholarAgent/1.0"}
    if S2_API_KEY:
        headers["x-api-key"] = S2_API_KEY

    for i, paper in enumerate(papers):
        title = paper.get("title", "")
        if not title:
            paper.setdefault("abstract", None)
            paper.setdefault("citationCount", 0)
            paper.setdefault("influentialCitationCount", 0)
            paper["s2_matched"] = False
            continue

        if (i + 1) % 10 == 0:
            logger.info("[S2] Enrichment progress: %d/%d", i + 1, len(papers))

        params = {"query": title, "limit": 3, "fields": S2_FIELDS}
        matched = False

        for attempt in range(max_retries):
            try:
                resp = _requests.get(S2_API_URL, params=params, headers=headers, timeout=15)
                if resp.status_code == 429:
                    time.sleep(S2_RATE_LIMIT_WAIT)
                    continue
                resp.raise_for_status()
                data = resp.json()

                results = data.get("data", [])
                if not results:
                    break

                best = max(results, key=lambda r: _title_similarity(title, r.get("title", "")))
                sim = _title_similarity(title, best.get("title", ""))

                if sim >= 0.6:
                    paper["abstract"] = best.get("abstract")
                    paper["citationCount"] = best.get("citationCount") or 0
                    paper["influentialCitationCount"] = best.get("influentialCitationCount") or 0
                    paper["s2_url"] = best.get("url", "")

                    ext = best.get("externalIds") or {}
                    if ext.get("ArXiv"):
                        paper["arxiv_id"] = ext["ArXiv"]
                    if ext.get("DOI"):
                        paper["doi"] = paper.get("doi") or ext["DOI"]

                    # Affiliations
                    if best.get("authors"):
                        affs: list[str] = []
                        for a in best["authors"]:
                            for affil in a.get("affiliations") or []:
                                name = affil.get("name", "") if isinstance(affil, dict) else str(affil)
                                if name and name not in affs:
                                    affs.append(name)
                        if affs:
                            paper["affiliations"] = affs

                    paper["s2_matched"] = True
                    paper["s2_similarity"] = round(sim, 2)
                    matched = True
                break

            except Exception as e:
                msg = str(e)
                if "429" in msg:
                    time.sleep(S2_RATE_LIMIT_WAIT)
                elif attempt < max_retries - 1:
                    time.sleep(2 ** attempt)

        if not matched:
            paper.setdefault("abstract", None)
            paper.setdefault("citationCount", 0)
            paper.setdefault("influentialCitationCount", 0)
            paper["s2_matched"] = False

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
    """Full conference search → keyword filter → S2 enrich → score pipeline."""
    # Step 1: DBLP search
    all_papers = search_all_conferences(year, venues)

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
        logger.info("[ConfFilter] %d → %d after keyword filter", len(all_papers), len(filtered))
        all_papers = filtered

    if not all_papers:
        return {"papers": [], "year": year, "total_found": 0}

    # Step 3: S2 enrichment
    enriched = enrich_with_semantic_scholar(all_papers[:100])  # limit to avoid rate limits

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
    from academic.scoring import calculate_relevance_score

    now_year = __import__("datetime").datetime.now().year
    if years is None:
        years = list(range(2020, now_year + 1))
    if venues is None:
        venues = ["NeurIPS", "ICML", "ICLR", "CVPR", "ACL"]

    # 1. DBLP search per year
    all_papers: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for year in years:
        batch = search_all_conferences(year, venues, max_per_venue=200)
        for p in batch:
            tn = re.sub(r"[^a-z0-9\s]", "", p["title"].lower()).strip()
            if tn and tn not in seen_titles:
                seen_titles.add(tn)
                all_papers.append(p)

    if not all_papers:
        return []

    logger.info("[ConfMultiYear] DBLP total: %d papers across %d years", len(all_papers), len(years))

    # 2. S2 enrichment (cap to keep runtime low)
    enriched = enrich_with_semantic_scholar(all_papers[:max_enrich])

    # 3. Relevance filter — drop papers with 0 relevance
    domains = config.get("research_domains", {})
    excluded = config.get("excluded_keywords", [])
    relevant: list[dict[str, Any]] = []
    for p in enriched:
        score, domain, keywords = calculate_relevance_score(p, domains, excluded)
        if score > 0:
            p["_relevance_score"] = score
            p["matched_domain"] = domain
            p["matched_keywords"] = keywords
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
