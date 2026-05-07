"""Hybrid academic paper search across arXiv and Semantic Scholar.

Architecture:
  - ``query_arxiv``       — date-range search via the arXiv Atom API
  - ``query_semantic_scholar`` — keyword search over the S2 graph
  - ``collect_hot_papers`` — concurrent category-aware hot-paper sweep
  - ``search_and_score``   — pluggable pipeline → scoring → dedup
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
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
    "externalIds,title,abstract,publicationDate,"
    "influentialCitationCount,citationCount,url,"
    "authors,authors.affiliations"
)

_ATOM_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# Mapping arXiv categories to descriptive query phrases for S2
_CATEGORY_PHRASES: dict[str, str] = {
    "cs.AI": "AI agent planning reasoning",
    "cs.LG": "deep learning optimization generalization",
    "cs.CL": "NLP language model text generation",
    "cs.CV": "image recognition visual understanding",
    "cs.MM": "multimodal audio video processing",
    "cs.MA": "multi-agent coordination decentralised",
    "cs.RO": "robot control perception navigation",
}

_S2_BACKOFF = 30  # seconds to wait on 429
_S2_INTER_QUERY_GAP = 4  # polite delay between category queries
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
                "deep-learning": {
                    "keywords": ["deep learning", "neural network", "representation learning"],
                    "arxiv_categories": ["cs.LG", "cs.AI"],
                    "priority": 3,
                },
            },
            "excluded_keywords": ["3D reconstruction", "tutorial"],
        }


# ---------------------------------------------------------------------------
# Generic retry helper
# ---------------------------------------------------------------------------

def _with_retry(
    fn,
    *args,
    max_tries: int = 3,
    backoff_base: int = 2,
    log_prefix: str = "",
):
    """Call *fn* with *args*, retrying on exceptions with exponential backoff."""
    for attempt in range(max_tries):
        try:
            return fn(*args)
        except Exception as exc:
            if attempt < max_tries - 1:
                wait = backoff_base ** (attempt + 1)
                logger.warning("%s fetch error (try %d): %s", log_prefix, attempt + 1, exc)
                time.sleep(wait)
            else:
                logger.error("%s: retries exhausted", log_prefix)
    return None


# ---------------------------------------------------------------------------
# DateWindow dataclass
# ---------------------------------------------------------------------------

@dataclass
class DateWindow:
    """Encapsulates the two date ranges used by the search pipeline."""

    recent_start: datetime
    recent_end: datetime
    year_start: datetime
    year_end: datetime

    @classmethod
    def from_target(cls, target: datetime | None = None) -> "DateWindow":
        """Build windows relative to *target* (defaults to now)."""
        ref = target or datetime.now()
        return cls(
            recent_start=ref - timedelta(days=30),
            recent_end=ref,
            year_start=ref - timedelta(days=365),
            year_end=ref - timedelta(days=31),
        )


# ---------------------------------------------------------------------------
# PaperRecord dataclass — bulk XML extraction
# ---------------------------------------------------------------------------

@dataclass
class PaperRecord:
    """Structured representation of a single paper parsed from arXiv Atom XML."""

    arxiv_id: str = ""
    title: str = ""
    summary: str = ""
    authors: list[str] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    published: str = ""
    published_date: datetime | None = None
    categories: list[str] = field(default_factory=list)
    pdf_url: str = ""
    url: str = ""
    source: str = "arxiv"

    def to_dict(self) -> dict[str, Any]:
        """Convert to the dict shape expected by downstream scoring."""
        return {
            "id": self.url or self.arxiv_id,
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "summary": self.summary,
            "authors": self.authors,
            "affiliations": self.affiliations,
            "published": self.published,
            "published_date": self.published_date,
            "categories": self.categories,
            "pdf_url": self.pdf_url,
            "url": self.url,
            "source": self.source,
        }

    @classmethod
    def from_atom_entry(cls, entry, ns: dict) -> "PaperRecord | None":
        """Build a PaperRecord by bulk-extracting all child text into a flat dict.

        Instead of per-field find() calls, this collects all direct children
        into a tag→text mapping first, then maps them to fields in one pass.
        """
        # Bulk extract: collect all direct child text into a lookup
        child_text: dict[str, str] = {}
        for child in entry:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if child.text:
                child_text[tag] = child.text.strip()

        rec = cls()

        # ID extraction
        raw_id = child_text.get("id", "")
        if raw_id:
            rec.url = raw_id
            m = re.search(r"(?:arXiv:)?(\d+\.\d+)", raw_id)
            if m:
                rec.arxiv_id = m.group(1)

        # Direct text fields
        rec.title = child_text.get("title", "")
        rec.summary = child_text.get("summary", "")
        rec.published = child_text.get("published", "")

        # Parse published date
        if rec.published:
            try:
                rec.published_date = datetime.fromisoformat(
                    rec.published.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                rec.published_date = None

        # Authors and affiliations — iterate author nodes
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
        rec.authors = names
        rec.affiliations = affils

        # Categories from attributes
        rec.categories = [
            c.get("term") for c in entry.findall("a:category", ns) if c.get("term")
        ]

        # PDF link from link elements
        for link in entry.findall("a:link", ns):
            if link.get("title") == "pdf":
                rec.pdf_url = link.get("href")
                break

        return rec

    @classmethod
    def parse_feed(cls, xml_text: str) -> list["PaperRecord"]:
        """Parse a full Atom feed into a list of PaperRecord instances."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.error("Atom XML parse failure: %s", exc)
            return []

        return [
            rec
            for entry in root.findall("a:entry", _ATOM_NS)
            if (rec := cls.from_atom_entry(entry, _ATOM_NS)) and rec.title
        ]


# ---------------------------------------------------------------------------
# arXiv search
# ---------------------------------------------------------------------------

def _fetch_arxiv_xml(url: str) -> str:
    """Fetch raw XML body from arXiv (single attempt, may raise)."""
    with _url_lib.urlopen(url, timeout=60) as resp:
        return resp.read().decode("utf-8")


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
    logger.info("arxiv query %s..%s", from_dt.date(), to_dt.date())

    body = _with_retry(
        _fetch_arxiv_xml, url,
        max_tries=retries, backoff_base=2, log_prefix="arxiv",
    )
    if body is None:
        return []

    return [r.to_dict() for r in PaperRecord.parse_feed(body)]


# ---------------------------------------------------------------------------
# Semantic Scholar search — functional pipeline
# ---------------------------------------------------------------------------

def _fetch_s2_json(url: str, params: dict, headers: dict) -> dict:
    """Fetch a single S2 API page (may raise)."""
    if _HAS_REQUESTS:
        r = _http.get(url, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()
    else:
        qs = urllib.parse.urlencode(params)
        req = _url_lib.Request(f"{url}?{qs}", headers=headers)
        with _url_lib.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))


def _enrich_s2_author_affiliations(authors: list[dict]) -> list[str]:
    """Extract unique affiliation names from S2 author dicts."""
    names: set[str] = set()
    for entry in authors:
        raw_affils = entry.get("affiliations")
        if not raw_affils:
            continue
        for aff in raw_affils:
            # Handle both dict {"name": X} and plain string forms
            label = aff["name"] if isinstance(aff, dict) and "name" in aff else (str(aff) if aff else "")
            label = label.strip()
            if label:
                names.add(label)
    return list(names)


def _s2_paper_to_dict(p: dict) -> dict[str, Any]:
    """Transform a single S2 API result into the normalized paper dict."""
    p["influentialCitationCount"] = p.get("influentialCitationCount") or 0
    p["citationCount"] = p.get("citationCount") or 0
    p["source"] = "s2_graph"
    p["impact_signal"] = p["influentialCitationCount"]

    if p.get("authors"):
        affs = _enrich_s2_author_affiliations(p["authors"])
        if affs:
            p["affiliations"] = affs

    ext = p.get("externalIds") or {}
    p["arxiv_id"] = ext.get("ArXiv")
    return p


def _normalize_s2_results(payload: dict, top_k: int) -> list[dict[str, Any]]:
    """Filter and normalize raw S2 API data using a functional pipeline.

    Instead of a for-loop with append, uses filter→map→sort→slice.
    """
    results = payload.get("data", [])
    # Filter: require both title and abstract
    valid = filter(lambda p: p.get("title") and p.get("abstract"), results)
    # Transform: normalize each paper dict
    transformed = list(map(_s2_paper_to_dict, valid))
    # Sort by influence and take top-k
    transformed.sort(key=lambda x: x["influentialCitationCount"], reverse=True)
    return transformed[:top_k]


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

    logger.info("s2 query '%s' range=%s..%s", phrase, from_dt.date(), to_dt.date())

    payload = _with_retry(
        _fetch_s2_json, _S2_SEARCH_URL, params, hdrs,
        max_tries=retries, backoff_base=2, log_prefix="s2",
    )
    if payload is None:
        return []

    results = _normalize_s2_results(payload, top_k)
    logger.info("s2 returned %d filtered results", len(results))
    return results


# ---------------------------------------------------------------------------
# Concurrent hot-paper sweep
# ---------------------------------------------------------------------------

def collect_hot_papers(
    categories: list[str],
    from_dt: datetime,
    to_dt: datetime,
    per_cat: int = 5,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run S2 queries concurrently across research domains.

    Uses ThreadPoolExecutor for parallel queries instead of sequential loops.
    """
    phrases: list[str] = []
    if config:
        for domain_name, dcfg in config.get("research_domains", {}).items():
            kws = dcfg.get("keywords", [])
            cats = dcfg.get("arxiv_categories", [])
            if kws:
                # Use top 2 keywords + domain name for richer queries
                query_parts = kws[:2]
                if domain_name and len(query_parts) < 3:
                    query_parts.append(domain_name)
                phrases.append(" ".join(query_parts))
            elif cats:
                phrases.extend(_CATEGORY_PHRASES.get(c, c) for c in cats[:2])
    if not phrases:
        phrases = [_CATEGORY_PHRASES.get(c, c) for c in categories]

    # Deduplicate phrases
    seen_q: set[str] = set()
    unique: list[str] = []
    for q in phrases:
        lk = q.lower()
        if lk not in seen_q:
            seen_q.add(lk)
            unique.append(q)

    # Concurrent execution
    bag: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _query_phrase(phrase: str) -> list[dict[str, Any]]:
        return query_semantic_scholar(phrase, from_dt, to_dt, per_cat)

    with ThreadPoolExecutor(max_workers=min(len(unique), 4)) as pool:
        futures = {pool.submit(_query_phrase, q): q for q in unique}
        for future in as_completed(futures):
            try:
                hits = future.result()
                for p in hits:
                    aid = p.get("arxiv_id")
                    if aid:
                        if aid in seen_ids:
                            continue
                        seen_ids.add(aid)
                    bag.append(p)
            except Exception as exc:
                logger.warning("Hot paper query failed: %s", exc)

    bag.sort(key=lambda x: x.get("influentialCitationCount", 0), reverse=True)
    return bag


# ---------------------------------------------------------------------------
# Pluggable pipeline
# ---------------------------------------------------------------------------

@dataclass
class _PipelineStep:
    """A single stage in the search pipeline."""
    name: str
    execute: Callable[[], list[dict[str, Any]]]
    is_hot: bool = False


def _slugify(text: str) -> str:
    """Normalize text to a slug for dedup: lowercase, strip non-alnum, collapse."""
    return re.sub(r"[-\s]+", "-", re.sub(r"[^a-z0-9\s-]", "", text.lower())).strip("-")


def search_and_score(
    config: dict[str, Any],
    categories: list[str] | None = None,
    target_date: datetime | None = None,
    max_results: int = 200,
    top_n: int = 10,
    skip_hot: bool = False,
    query: str = "",
) -> dict[str, Any]:
    """Full search → score → dedup pipeline.

    Uses a pluggable step-based architecture instead of hardcoded stages.
    """
    if categories is None:
        categories = ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]
    if target_date is None:
        target_date = datetime.now()

    dw = DateWindow.from_target(target_date)

    # Build pipeline steps dynamically
    steps: list[_PipelineStep] = [
        _PipelineStep(
            name="recent_arxiv",
            execute=lambda: query_arxiv(categories, dw.recent_start, dw.recent_end, max_results),
            is_hot=False,
        ),
    ]

    if not skip_hot:
        steps.append(_PipelineStep(
            name="hot_papers",
            execute=lambda: collect_hot_papers(categories, dw.year_start, dw.year_end, per_cat=5, config=config),
            is_hot=True,
        ))

    if query and query.strip():
        steps.append(_PipelineStep(
            name="user_query",
            execute=lambda: query_semantic_scholar(query.strip(), dw.year_start, dw.year_end, top_k=10),
            is_hot=True,
        ))

    # Execute each step and score
    scored: list[dict[str, Any]] = []
    for step in steps:
        try:
            raw = step.execute()
            if raw:
                batch = score_papers(raw, config, is_hot_batch=step.is_hot)
                logger.info("Step '%s': scored %d papers", step.name, len(batch))
                scored.extend(batch)
        except Exception as exc:
            logger.error("Pipeline step '%s' failed: %s", step.name, exc)

    # Merge & dedup — use slug-based normalization instead of regex strip
    scored.sort(key=lambda p: p["scores"].get("recommendation", 0), reverse=True)
    seen_keys: set[str] = set()
    unique: list[dict[str, Any]] = []
    for p in scored:
        aid = p.get("arxiv_id") or p.get("arxivId")
        key = aid if aid else _slugify(p.get("title", ""))
        if key and key not in seen_keys:
            seen_keys.add(key)
            unique.append(p)

    return {
        "papers": unique[:top_n],
        "date_windows": {
            "recent_30d": {
                "start": dw.recent_start.isoformat(),
                "end": dw.recent_end.isoformat(),
            },
            "past_year": {
                "start": dw.year_start.isoformat(),
                "end": dw.year_end.isoformat(),
            },
        },
        "total_found": len(unique),
    }
