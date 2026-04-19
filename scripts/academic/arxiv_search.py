"""arXiv + Semantic Scholar hybrid paper search.

Provides:
  - search_arxiv: date-range search via arXiv Atom API
  - search_hot_papers: high-influence papers via Semantic Scholar
  - search_and_score: combined pipeline with scoring

Adapted from evil-read-arxiv/start-my-day/scripts/search_arxiv.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib import request as urllib_request

from academic.scoring import score_papers

logger = logging.getLogger(__name__)

try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ---------------------------------------------------------------------------
# API config
# ---------------------------------------------------------------------------

ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_FIELDS = (
    "title,abstract,publicationDate,citationCount,influentialCitationCount,"
    "url,authors,authors.affiliations,externalIds"
)

ARXIV_CATEGORY_KEYWORDS: dict[str, str] = {
    "cs.AI": "artificial intelligence",
    "cs.LG": "machine learning",
    "cs.CL": "computational linguistics natural language processing",
    "cs.CV": "computer vision",
    "cs.MM": "multimedia",
    "cs.MA": "multi-agent systems",
    "cs.RO": "robotics",
}

S2_RATE_LIMIT_WAIT = 30
S2_CATEGORY_REQUEST_INTERVAL = 3

# API key can be set via env var or config
S2_API_KEY = os.environ.get("S2_API_KEY", "")


def _load_config(config_path: str) -> dict[str, Any]:
    """Load research interests YAML config."""
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        global S2_API_KEY
        key = config.get("semantic_scholar", {}).get("api_key", "")
        if key:
            S2_API_KEY = key
        return config
    except Exception as e:
        logger.error("Error loading config: %s", e)
        return {
            "research_domains": {
                "大模型": {
                    "keywords": ["pre-training", "foundation model", "LLM", "transformer"],
                    "arxiv_categories": ["cs.AI", "cs.LG", "cs.CL"],
                    "priority": 5,
                }
            },
            "excluded_keywords": ["3D", "review", "workshop", "survey"],
        }


# ---------------------------------------------------------------------------
# Date windows
# ---------------------------------------------------------------------------

def calculate_date_windows(
    target_date: datetime | None = None,
) -> tuple[datetime, datetime, datetime, datetime]:
    """Return (start_30d, end_30d, start_1y, end_1y)."""
    if target_date is None:
        target_date = datetime.now()
    start_30d = target_date - timedelta(days=30)
    end_30d = target_date
    start_1y = target_date - timedelta(days=365)
    end_1y = target_date - timedelta(days=31)
    return start_30d, end_30d, start_1y, end_1y


# ---------------------------------------------------------------------------
# arXiv search
# ---------------------------------------------------------------------------

def search_arxiv(
    categories: list[str],
    start_date: datetime,
    end_date: datetime,
    max_results: int = 200,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """Search arXiv by date range and categories."""
    cat_query = "+OR+".join(f"cat:{c}" for c in categories)
    date_query = (
        f"submittedDate:[{start_date.strftime('%Y%m%d')}0000"
        f"+TO+{end_date.strftime('%Y%m%d')}2359]"
    )
    url = (
        f"https://export.arxiv.org/api/query?"
        f"search_query=({cat_query})+AND+{date_query}&"
        f"max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
    )
    logger.info("[arXiv] Searching %s — %s", start_date.date(), end_date.date())

    for attempt in range(max_retries):
        try:
            with urllib_request.urlopen(url, timeout=60) as resp:
                xml_content = resp.read().decode("utf-8")
                return _parse_arxiv_xml(xml_content)
        except Exception as e:
            logger.warning("[arXiv] Error (attempt %d/%d): %s", attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep((2 ** attempt) * 2)
            else:
                logger.error("[arXiv] Failed after %d attempts", max_retries)
    return []


def _parse_arxiv_xml(xml_content: str) -> list[dict[str, Any]]:
    """Parse arXiv Atom XML into paper dicts."""
    papers: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logger.error("XML parse error: %s", e)
        return papers

    for entry in root.findall("atom:entry", ARXIV_NS):
        paper: dict[str, Any] = {}

        id_elem = entry.find("atom:id", ARXIV_NS)
        if id_elem is not None and id_elem.text:
            paper["id"] = id_elem.text
            m = re.search(r"(?:arXiv:)?(\d+\.\d+)", id_elem.text)
            if m:
                paper["arxiv_id"] = m.group(1)

        title_elem = entry.find("atom:title", ARXIV_NS)
        if title_elem is not None and title_elem.text:
            paper["title"] = title_elem.text.strip()

        summary_elem = entry.find("atom:summary", ARXIV_NS)
        if summary_elem is not None and summary_elem.text:
            paper["summary"] = summary_elem.text.strip()

        authors: list[str] = []
        affiliations: list[str] = []
        for author in entry.findall("atom:author", ARXIV_NS):
            name_elem = author.find("atom:name", ARXIV_NS)
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text)
            affil = author.find("arxiv:affiliation", ARXIV_NS)
            if affil is not None and affil.text:
                aff = affil.text.strip()
                if aff and aff not in affiliations:
                    affiliations.append(aff)
        paper["authors"] = authors
        paper["affiliations"] = affiliations

        pub_elem = entry.find("atom:published", ARXIV_NS)
        if pub_elem is not None and pub_elem.text:
            paper["published"] = pub_elem.text
            try:
                paper["published_date"] = datetime.fromisoformat(
                    pub_elem.text.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                paper["published_date"] = None

        cats: list[str] = []
        for cat in entry.findall("atom:category", ARXIV_NS):
            term = cat.get("term")
            if term:
                cats.append(term)
        paper["categories"] = cats

        for link in entry.findall("atom:link", ARXIV_NS):
            if link.get("title") == "pdf":
                paper["pdf_url"] = link.get("href")
                break

        paper["url"] = paper.get("id", "")
        paper["source"] = "arxiv"
        papers.append(paper)

    return papers


# ---------------------------------------------------------------------------
# Semantic Scholar hot papers
# ---------------------------------------------------------------------------

def search_semantic_scholar(
    query: str,
    start_date: datetime,
    end_date: datetime,
    top_k: int = 20,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    """Search Semantic Scholar for high-influence papers."""
    import urllib.parse

    date_range = f"{start_date.strftime('%Y-%m-%d')}:{end_date.strftime('%Y-%m-%d')}"
    params = {
        "query": query,
        "publicationDateOrYear": date_range,
        "limit": 100,
        "fields": SEMANTIC_SCHOLAR_FIELDS,
    }
    headers = {"User-Agent": "LoreScholar/1.0"}
    if S2_API_KEY:
        headers["x-api-key"] = S2_API_KEY

    logger.info("[S2] Searching hot papers: '%s' (%s–%s)", query, start_date.date(), end_date.date())

    for attempt in range(max_retries):
        try:
            if HAS_REQUESTS:
                resp = _requests.get(
                    SEMANTIC_SCHOLAR_API_URL, params=params, headers=headers, timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
            else:
                qs = urllib.parse.urlencode(params)
                req = urllib_request.Request(
                    f"{SEMANTIC_SCHOLAR_API_URL}?{qs}", headers=headers,
                )
                with urllib_request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

            results = data.get("data", [])
            valid: list[dict[str, Any]] = []
            for p in results:
                if not p.get("title") or not p.get("abstract"):
                    continue
                p["influentialCitationCount"] = p.get("influentialCitationCount") or 0
                p["citationCount"] = p.get("citationCount") or 0
                p["source"] = "semantic_scholar"
                p["hot_score"] = p["influentialCitationCount"]

                # Extract affiliations
                if p.get("authors"):
                    affs: list[str] = []
                    for a in p["authors"]:
                        for affil in a.get("affiliations") or []:
                            name = affil.get("name", "") if isinstance(affil, dict) else str(affil)
                            if name and name not in affs:
                                affs.append(name)
                    if affs:
                        p["affiliations"] = affs

                ext = p.get("externalIds") or {}
                p["arxiv_id"] = ext.get("ArXiv")
                valid.append(p)

            valid.sort(key=lambda x: x["influentialCitationCount"], reverse=True)
            logger.info("[S2] Found %d valid papers", len(valid))
            return valid[:top_k]

        except Exception as e:
            msg = str(e)
            is_429 = "429" in msg or "Too Many Requests" in msg
            if attempt < max_retries - 1:
                wait = S2_RATE_LIMIT_WAIT if is_429 else (2 ** attempt) * 2
                logger.warning("[S2] Retry in %ds: %s", wait, e)
                time.sleep(wait)
            else:
                logger.error("[S2] Failed after %d attempts", max_retries)
    return []


def search_hot_papers_from_categories(
    categories: list[str],
    start_date: datetime,
    end_date: datetime,
    top_k_per_category: int = 5,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search hot papers for multiple arXiv categories."""
    all_papers: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    queries: list[str] = []
    if config:
        for _, dcfg in config.get("research_domains", {}).items():
            kws = dcfg.get("keywords", [])
            if kws:
                queries.append(" ".join(kws[:3]))
    if not queries:
        queries = [ARXIV_CATEGORY_KEYWORDS.get(c, c) for c in categories]

    # Deduplicate queries
    seen_q: set[str] = set()
    unique: list[str] = []
    for q in queries:
        ql = q.lower()
        if ql not in seen_q:
            seen_q.add(ql)
            unique.append(q)

    for query in unique:
        papers = search_semantic_scholar(query, start_date, end_date, top_k_per_category)
        for p in papers:
            aid = p.get("arxiv_id")
            if aid:
                if aid in seen_ids:
                    continue
                seen_ids.add(aid)
            all_papers.append(p)
        time.sleep(S2_CATEGORY_REQUEST_INTERVAL)

    all_papers.sort(key=lambda x: x.get("influentialCitationCount", 0), reverse=True)
    return all_papers


# ---------------------------------------------------------------------------
# Combined pipeline
# ---------------------------------------------------------------------------

def search_and_score(
    config: dict[str, Any],
    categories: list[str] | None = None,
    target_date: datetime | None = None,
    max_results: int = 200,
    top_n: int = 10,
    skip_hot: bool = False,
) -> dict[str, Any]:
    """Full arXiv + S2 search → score → dedup pipeline.

    Returns a dict with 'papers', 'date_windows', 'total_found'.
    """
    if categories is None:
        categories = ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]

    if target_date is None:
        target_date = datetime.now()

    w30_start, w30_end, w1y_start, w1y_end = calculate_date_windows(target_date)

    all_scored: list[dict[str, Any]] = []

    # Step 1: recent arXiv papers
    recent = search_arxiv(categories, w30_start, w30_end, max_results)
    if recent:
        scored = score_papers(recent, config, is_hot_batch=False)
        logger.info("Scored %d recent arXiv papers", len(scored))
        all_scored.extend(scored)

    # Step 2: hot papers from S2
    if not skip_hot:
        hot = search_hot_papers_from_categories(
            categories, w1y_start, w1y_end, top_k_per_category=5, config=config,
        )
        if hot:
            scored_hot = score_papers(hot, config, is_hot_batch=True)
            logger.info("Scored %d hot papers", len(scored_hot))
            all_scored.extend(scored_hot)

    # Step 3: merge and dedup
    all_scored.sort(key=lambda p: p["scores"]["recommendation"], reverse=True)

    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[dict[str, Any]] = []
    for p in all_scored:
        aid = p.get("arxiv_id") or p.get("arxivId")
        if aid:
            if aid not in seen_ids:
                seen_ids.add(aid)
                unique.append(p)
        else:
            tn = re.sub(r"[^a-z0-9\s]", "", p.get("title", "").lower()).strip()
            if tn and tn not in seen_titles:
                seen_titles.add(tn)
                unique.append(p)

    return {
        "papers": unique[:top_n],
        "date_windows": {
            "recent_30d": {"start": w30_start.isoformat(), "end": w30_end.isoformat()},
            "past_year": {"start": w1y_start.isoformat(), "end": w1y_end.isoformat()},
        },
        "total_found": len(unique),
    }
