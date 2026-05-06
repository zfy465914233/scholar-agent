"""Hybrid academic paper search across arXiv and Semantic Scholar.

Architecture:
  - ``query_arxiv``       — date-range search via the arXiv Atom API
  - ``query_semantic_scholar`` — keyword search over the S2 graph
  - ``collect_hot_papers`` — category-aware hot-paper sweep
  - ``search_and_score``   — combined pipeline → scoring → dedup
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any
from urllib import request as _url_lib

from academic.scoring import score_papers

logger = logging.getLogger(__name__)

try:
    import requests as _http
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

# ---------------------------------------------------------------------------
# API endpoints and field specs
# ---------------------------------------------------------------------------

_S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_S2_FIELDS = (
    "title,abstract,publicationDate,citationCount,influentialCitationCount,"
    "url,authors,authors.affiliations,externalIds"
)

_ATOM_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# Mapping arXiv categories to descriptive query phrases for S2
_CATEGORY_PHRASES: dict[str, str] = {
    "cs.AI": "artificial intelligence",
    "cs.LG": "machine learning",
    "cs.CL": "computational linguistics natural language processing",
    "cs.CV": "computer vision",
    "cs.MM": "multimedia",
    "cs.MA": "multi-agent systems",
    "cs.RO": "robotics",
}

_S2_BACKOFF = 30  # seconds to wait on 429
_S2_INTER_QUERY_GAP = 3  # polite delay between category queries
_S2_KEY = os.environ.get("S2_API_KEY", "")


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def _load_config(config_path: str) -> dict[str, Any]:
    """Read a YAML research-interests file and return a config dict."""
    try:
        import yaml
        with open(config_path, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        global _S2_KEY
        key = cfg.get("semantic_scholar", {}).get("api_key", "")
        if key:
            _S2_KEY = key
        return cfg
    except Exception as exc:
        logger.error("Config load error: %s", exc)
        return {
            "research_domains": {
                "大模型": {
                    "keywords": ["pre-training", "foundation model", "LLM", "transformer"],
                    "arxiv_categories": ["cs.AI", "cs.LG", "cs.CL"],
                    "priority": 5,
                },
            },
            "excluded_keywords": ["3D", "review", "workshop", "survey"],
        }


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _time_windows(
    anchor: datetime | None = None,
) -> tuple[datetime, datetime, datetime, datetime]:
    """(recent_start, now, past_year_start, past_year_end)."""
    ref = anchor or datetime.now()
    recent_start = ref - timedelta(days=30)
    past_year_start = ref - timedelta(days=365)
    past_year_end = ref - timedelta(days=31)
    return recent_start, ref, past_year_start, past_year_end


# ---------------------------------------------------------------------------
# arXiv search
# ---------------------------------------------------------------------------

def query_arxiv(
    categories: list[str],
    from_dt: datetime,
    to_dt: datetime,
    limit: int = 200,
    retries: int = 3,
) -> list[dict[str, Any]]:
    """Fetch recent papers from arXiv Atom API."""
    cat_part = "+OR+".join(f"cat:{c}" for c in categories)
    date_part = (
        f"submittedDate:[{from_dt.strftime('%Y%m%d')}0000"
        f"+TO+{to_dt.strftime('%Y%m%d')}2359]"
    )
    url = (
        f"https://export.arxiv.org/api/query?"
        f"search_query=({cat_part})+AND+{date_part}&"
        f"max_results={limit}&sortBy=submittedDate&sortOrder=descending"
    )
    logger.info("[arXiv] %s → %s", from_dt.date(), to_dt.date())

    for attempt in range(retries):
        try:
            with _url_lib.urlopen(url, timeout=60) as resp:
                body = resp.read().decode("utf-8")
                return _atom_to_papers(body)
        except Exception as exc:
            logger.warning("[arXiv] attempt %d failed: %s", attempt + 1, exc)
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
    logger.error("[arXiv] all attempts exhausted")
    return []


def _atom_to_papers(xml_text: str) -> list[dict[str, Any]]:
    """Parse arXiv Atom XML into a list of paper dicts."""
    papers: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.error("Atom XML parse failure: %s", exc)
        return papers

    ns = _ATOM_NS
    for entry in root.findall("a:entry", ns):
        rec: dict[str, Any] = {}

        eid = entry.find("a:id", ns)
        if eid is not None and eid.text:
            rec["id"] = eid.text
            m = re.search(r"(?:arXiv:)?(\d+\.\d+)", eid.text)
            if m:
                rec["arxiv_id"] = m.group(1)

        ttl = entry.find("a:title", ns)
        if ttl is not None and ttl.text:
            rec["title"] = ttl.text.strip()

        summ = entry.find("a:summary", ns)
        if summ is not None and summ.text:
            rec["summary"] = summ.text.strip()

        names: list[str] = []
        affils: list[str] = []
        for author_node in entry.findall("a:author", ns):
            nm = author_node.find("a:name", ns)
            if nm is not None and nm.text:
                names.append(nm.text)
            af = author_node.find("arxiv:affiliation", ns)
            if af is not None and af.text:
                a = af.text.strip()
                if a and a not in affils:
                    affils.append(a)
        rec["authors"] = names
        rec["affiliations"] = affils

        pub = entry.find("a:published", ns)
        if pub is not None and pub.text:
            rec["published"] = pub.text
            try:
                rec["published_date"] = datetime.fromisoformat(
                    pub.text.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                rec["published_date"] = None

        cats: list[str] = []
        for c in entry.findall("a:category", ns):
            t = c.get("term")
            if t:
                cats.append(t)
        rec["categories"] = cats

        for link in entry.findall("a:link", ns):
            if link.get("title") == "pdf":
                rec["pdf_url"] = link.get("href")
                break

        rec["url"] = rec.get("id", "")
        rec["source"] = "arxiv"
        papers.append(rec)

    return papers


# Keep legacy name
search_arxiv = query_arxiv


# ---------------------------------------------------------------------------
# Semantic Scholar search
# ---------------------------------------------------------------------------

def query_semantic_scholar(
    phrase: str,
    from_dt: datetime,
    to_dt: datetime,
    top_k: int = 20,
    retries: int = 3,
) -> list[dict[str, Any]]:
    """Search S2 graph for papers matching *phrase* in the date window."""
    date_range = f"{from_dt:%Y-%m-%d}:{to_dt:%Y-%m-%d}"
    params = {
        "query": phrase,
        "publicationDateOrYear": date_range,
        "limit": 100,
        "fields": _S2_FIELDS,
    }
    hdrs = {"User-Agent": "ScholarAgent/1.0"}
    if _S2_KEY:
        hdrs["x-api-key"] = _S2_KEY

    logger.info("[S2] '%s' (%s–%s)", phrase, from_dt.date(), to_dt.date())

    for attempt in range(retries):
        try:
            if _HAS_REQUESTS:
                r = _http.get(_S2_SEARCH_URL, params=params, headers=hdrs, timeout=15)
                r.raise_for_status()
                payload = r.json()
            else:
                qs = urllib.parse.urlencode(params)
                req = _url_lib.Request(f"{_S2_SEARCH_URL}?{qs}", headers=hdrs)
                with _url_lib.urlopen(req, timeout=15) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))

            results = payload.get("data", [])
            valid: list[dict[str, Any]] = []
            for p in results:
                if not p.get("title") or not p.get("abstract"):
                    continue
                p["influentialCitationCount"] = p.get("influentialCitationCount") or 0
                p["citationCount"] = p.get("citationCount") or 0
                p["source"] = "semantic_scholar"
                p["hot_score"] = p["influentialCitationCount"]

                if p.get("authors"):
                    affs: list[str] = []
                    for a in p["authors"]:
                        for af in a.get("affiliations") or []:
                            name = af.get("name", "") if isinstance(af, dict) else str(af)
                            if name and name not in affs:
                                affs.append(name)
                    if affs:
                        p["affiliations"] = affs

                ext = p.get("externalIds") or {}
                p["arxiv_id"] = ext.get("ArXiv")
                valid.append(p)

            valid.sort(key=lambda x: x["influentialCitationCount"], reverse=True)
            logger.info("[S2] %d valid hits", len(valid))
            return valid[:top_k]

        except Exception as exc:
            is_rate = "429" in str(exc) or "Too Many Requests" in str(exc)
            if attempt < retries - 1:
                wait = _S2_BACKOFF if is_rate else 2 ** (attempt + 1)
                logger.warning("[S2] retry in %ds: %s", wait, exc)
                time.sleep(wait)
            else:
                logger.error("[S2] all attempts failed")
    return []


# Keep legacy name
search_semantic_scholar = query_semantic_scholar


# ---------------------------------------------------------------------------
# Category-aware hot-paper sweep
# ---------------------------------------------------------------------------

def collect_hot_papers(
    categories: list[str],
    from_dt: datetime,
    to_dt: datetime,
    per_cat: int = 5,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run S2 queries derived from research domains or category labels."""
    bag: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    phrases: list[str] = []
    if config:
        for _, dcfg in config.get("research_domains", {}).items():
            kws = dcfg.get("keywords", [])
            if kws:
                phrases.append(" ".join(kws[:3]))
    if not phrases:
        phrases = [_CATEGORY_PHRASES.get(c, c) for c in categories]

    # dedup
    seen_q: set[str] = set()
    unique: list[str] = []
    for q in phrases:
        lk = q.lower()
        if lk not in seen_q:
            seen_q.add(lk)
            unique.append(q)

    for phrase in unique:
        hits = query_semantic_scholar(phrase, from_dt, to_dt, per_cat)
        for p in hits:
            aid = p.get("arxiv_id")
            if aid:
                if aid in seen_ids:
                    continue
                seen_ids.add(aid)
            bag.append(p)
        time.sleep(_S2_INTER_QUERY_GAP)

    bag.sort(key=lambda x: x.get("influentialCitationCount", 0), reverse=True)
    return bag


# Keep legacy name
search_hot_papers_from_categories = collect_hot_papers


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
    query: str = "",
) -> dict[str, Any]:
    """Full search → score → dedup pipeline."""
    if categories is None:
        categories = ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]
    if target_date is None:
        target_date = datetime.now()

    rec_start, rec_end, yr_start, yr_end = _time_windows(target_date)

    scored: list[dict[str, Any]] = []

    # Stage 1: recent arXiv
    recent = query_arxiv(categories, rec_start, rec_end, max_results)
    if recent:
        batch = score_papers(recent, config, is_hot_batch=False)
        logger.info("Scored %d recent arXiv papers", len(batch))
        scored.extend(batch)

    # Stage 2: hot S2 papers
    if not skip_hot:
        hot = collect_hot_papers(categories, yr_start, yr_end, per_cat=5, config=config)
        if hot:
            batch = score_papers(hot, config, is_hot_batch=True)
            logger.info("Scored %d hot papers", len(batch))
            scored.extend(batch)

    # Stage 2b: user query against S2
    if query and query.strip():
        q_hits = query_semantic_scholar(query.strip(), yr_start, yr_end, top_k=10)
        if q_hits:
            batch = score_papers(q_hits, config, is_hot_batch=True)
            logger.info("Scored %d query-based papers", len(batch))
            scored.extend(batch)

    # Merge & dedup
    scored.sort(key=lambda p: p["scores"]["recommendation"], reverse=True)
    id_set: set[str] = set()
    title_set: set[str] = set()
    unique: list[dict[str, Any]] = []
    for p in scored:
        aid = p.get("arxiv_id") or p.get("arxivId")
        if aid:
            if aid not in id_set:
                id_set.add(aid)
                unique.append(p)
        else:
            norm = re.sub(r"[^a-z0-9\s]", "", p.get("title", "").lower()).strip()
            if norm and norm not in title_set:
                title_set.add(norm)
                unique.append(p)

    return {
        "papers": unique[:top_n],
        "date_windows": {
            "recent_30d": {"start": rec_start.isoformat(), "end": rec_end.isoformat()},
            "past_year": {"start": yr_start.isoformat(), "end": yr_end.isoformat()},
        },
        "total_found": len(unique),
    }


# Legacy alias
calculate_date_windows = _time_windows
