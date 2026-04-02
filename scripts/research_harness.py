"""Minimal research harness runtime for evidence-driven discovery.

This script turns the repo's instruction-only workflow into an executable
pipeline: formulate queries, search SearXNG, fetch content, cache results,
build evidence objects, validate them, and emit structured JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

from cache_helper import get as cache_get
from cache_helper import put as cache_put


SEARXNG_BASE_URL = os.environ.get("SEARXNG_BASE_URL", "http://localhost:8080")
MAX_FETCH_CHARS = 12000
BLOCKED_FETCH_DOMAINS = {
    "sciencedirect.com",
    "wiley.com",
    "onlinelibrary.wiley.com",
    "ieee.org",
    "ieeexplore.ieee.org",
    "nature.com",
}
SOURCE_TYPE_RULES = {
    "github.com": "github",
    "arxiv.org": "arxiv",
    "paperswithcode.com": "paper",
    "patents.google.com": "patent",
    "worldwide.espacenet.com": "patent",
    "readthedocs.io": "docs",
    "docs.": "docs",
    "reddit.com": "forum",
    "stackoverflow.com": "forum",
}
REQUIRED_FIELDS = {
    "query",
    "source_type",
    "url",
    "title",
    "summary",
    "retrieved_at",
    "retrieval_status",
}
VALID_SOURCE_TYPES = {"github", "arxiv", "blog", "docs", "forum", "paper", "patent", "other"}
VALID_RETRIEVAL_STATUS = {"succeeded", "failed", "partial", "cached"}
VALID_CONFIDENCE = {"confirmed", "likely", "unknown"}


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in {"p", "div", "section", "article", "br", "li", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        raw = unescape("".join(self._parts))
        return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", raw)).strip()


@dataclass
class SearchCandidate:
    query: str
    url: str
    title: str
    snippet: str
    published_at: Optional[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a local evidence-first discovery workflow against SearXNG.",
    )
    parser.add_argument("query", help="Research topic or question")
    parser.add_argument(
        "--depth",
        choices=("quick", "medium", "deep"),
        default="medium",
        help="Search depth controlling query count and fetch coverage",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of fetched evidence items; defaults by depth",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path; defaults to stdout",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    schema = load_schema(root / "schemas" / "evidence.schema.json")

    try:
        evidence = run_discovery(args.query, args.depth, args.limit)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    validation_errors = validate_evidence_items(evidence, schema)
    payload = {
        "query": args.query,
        "depth": args.depth,
        "generated_at": now_iso(),
        "summary": summarize_run(evidence),
        "validation": {
            "ok": not validation_errors,
            "errors": validation_errors,
        },
        "evidence": evidence,
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty or args.output else None)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")
    else:
        print(text)
    return 0 if not validation_errors else 2


def run_discovery(query: str, depth: str, limit: Optional[int]) -> list[dict[str, Any]]:
    queries = formulate_queries(query, depth)
    default_limit = {"quick": 3, "medium": 6, "deep": 10}[depth]
    max_items = limit or default_limit

    candidates = collect_candidates(queries)
    if not candidates:
        raise RuntimeError(
            "No search results returned from SearXNG. Start the local backend with 'docker compose up -d searxng' in the optimizer directory and retry."
        )

    evidence: list[dict[str, Any]] = []
    for candidate in candidates[:max_items]:
        evidence.append(build_evidence(query, candidate))
    return evidence


def formulate_queries(query: str, depth: str) -> list[str]:
    year = datetime.now(timezone.utc).year
    variants = [query]
    if depth in {"medium", "deep"}:
        variants.extend([
            f"{query} latest",
            f"{query} {year}",
            f"{query} open source",
        ])
    if depth == "deep":
        variants.extend([
            f"{query} comparison",
            f"{query} benchmark",
            f"{query} 综述",
        ])
    seen: set[str] = set()
    ordered: list[str] = []
    for item in variants:
        normalized = item.strip()
        if normalized and normalized not in seen:
            ordered.append(normalized)
            seen.add(normalized)
    return ordered


def collect_candidates(queries: list[str]) -> list[SearchCandidate]:
    seen_urls: set[str] = set()
    candidates: list[SearchCandidate] = []
    for query in queries:
        for item in search_searxng(query):
            url = item.get("url") or item.get("link")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append(
                SearchCandidate(
                    query=query,
                    url=url,
                    title=(item.get("title") or url).strip(),
                    snippet=(item.get("content") or item.get("snippet") or "").strip(),
                    published_at=normalize_date(item.get("publishedDate") or item.get("published_date")),
                )
            )
    return candidates


def search_searxng(query: str) -> list[dict[str, Any]]:
    url = f"{SEARXNG_BASE_URL.rstrip('/')}/search?q={quote_plus(query)}&format=json"
    request = Request(url, headers={"User-Agent": "optimizer-research-harness/0.1"})
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"SearXNG request failed for query '{query}': {exc}. "
            "If the container is not running, start it with 'docker compose up -d searxng' in the optimizer directory."
        ) from exc
    return payload.get("results", [])


def build_evidence(user_query: str, candidate: SearchCandidate) -> dict[str, Any]:
    source_type = classify_source_type(candidate.url)
    fetch_result = fetch_content(candidate.url)
    text = fetch_result["content_md"]
    title = fetch_result["title"] or candidate.title
    summary = summarize_text(text, candidate.snippet)
    published_at = candidate.published_at
    confidence = "confirmed" if fetch_result["retrieval_status"] in {"succeeded", "cached"} else "likely"

    evidence = {
        "query": user_query,
        "source_type": source_type,
        "url": candidate.url,
        "title": title,
        "summary": summary,
        "content_md": text,
        "published_at": published_at,
        "retrieved_at": now_iso(),
        "license": None,
        "freshness_signals": {
            "last_commit_date": published_at if source_type == "github" else None,
            "latest_release_date": None,
            "page_updated_date": published_at,
        },
        "community_signals": {
            "stars": None,
            "forks": None,
            "open_issues": None,
            "contributors": None,
        },
        "evidence_spans": pick_evidence_spans(text, candidate.snippet),
        "confidence": confidence,
        "retrieval_status": fetch_result["retrieval_status"],
        "scores": score_evidence(source_type, published_at, fetch_result["retrieval_status"]),
    }

    if fetch_result.get("failure_reason"):
        evidence["summary"] = f"{summary} Retrieval note: {fetch_result['failure_reason']}"
    return evidence


def classify_source_type(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    for key, value in SOURCE_TYPE_RULES.items():
        if key.endswith("."):
            if host.startswith(key):
                return value
            continue
        if host == key or host.endswith(f".{key}"):
            return value
    if any(host.endswith(suffix) for suffix in (".gov", ".edu", ".org")):
        return "docs"
    if any(host.endswith(suffix) for suffix in ("medium.com", "substack.com", "blogspot.com")):
        return "blog"
    return "other"


def fetch_content(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if any(host == domain or host.endswith(f".{domain}") for domain in BLOCKED_FETCH_DOMAINS):
        return {
            "title": "",
            "content_md": "",
            "retrieval_status": "partial",
            "failure_reason": "Domain often blocks automated retrieval; kept search snippet only.",
        }

    cached = cache_get(url)
    if cached is not None:
        return {
            "title": extract_title_from_cached(cached),
            "content_md": cached,
            "retrieval_status": "cached",
            "failure_reason": "",
        }

    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; optimizer-research-harness/0.1)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except (HTTPError, URLError, OSError) as exc:
        return {
            "title": "",
            "content_md": "",
            "retrieval_status": "failed",
            "failure_reason": str(exc),
        }

    title = extract_html_title(raw)
    text = html_to_text(raw)
    content_md = f"# {title}\n\n{text[:MAX_FETCH_CHARS]}".strip() if title else text[:MAX_FETCH_CHARS]
    if content_md:
        cache_put(url, content_md)
    return {
        "title": title,
        "content_md": content_md,
        "retrieval_status": "succeeded" if content_md else "partial",
        "failure_reason": "",
    }


def extract_title_from_cached(markdown: str) -> str:
    first_line = markdown.splitlines()[0] if markdown else ""
    if first_line.startswith("# "):
        return first_line[2:].strip()
    return ""


def extract_html_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", unescape(match.group(1))).strip()


def html_to_text(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html)
    text = parser.text()
    return text[:MAX_FETCH_CHARS]


def summarize_text(text: str, fallback: str) -> str:
    base = text.strip() or fallback.strip()
    if not base:
        return "No textual content retrieved; only metadata is available."
    compact = re.sub(r"\s+", " ", base)
    sentences = re.split(r"(?<=[.!?。！？])\s+", compact)
    selected = [sentence.strip() for sentence in sentences if sentence.strip()][:3]
    if not selected:
        selected = [compact[:280].strip()]
    summary = " ".join(selected)
    return summary[:500]


def pick_evidence_spans(text: str, fallback: str) -> list[str]:
    compact = re.sub(r"\s+", " ", text).strip()
    spans: list[str] = []
    if compact:
        spans.append(compact[:220])
    if fallback.strip() and fallback.strip() not in spans:
        spans.append(fallback.strip()[:220])
    return spans[:2]


def score_evidence(source_type: str, published_at: Optional[str], retrieval_status: str) -> dict[str, float]:
    freshness = score_freshness(published_at)
    credibility_map = {
        "docs": 5,
        "github": 4,
        "arxiv": 4,
        "paper": 4,
        "blog": 3,
        "forum": 2,
        "patent": 4,
        "other": 2,
    }
    reproducibility_map = {
        "github": 5,
        "docs": 4,
        "paper": 3,
        "arxiv": 3,
        "blog": 2,
        "forum": 1,
        "patent": 1,
        "other": 1,
    }
    community = 3 if source_type == "github" and retrieval_status in {"succeeded", "cached"} else 1
    return {
        "freshness": float(freshness),
        "credibility": float(credibility_map.get(source_type, 1)),
        "reproducibility": float(reproducibility_map.get(source_type, 1)),
        "community_activity": float(community),
    }


def score_freshness(published_at: Optional[str]) -> int:
    if not published_at:
        return 0
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return 0
    days = (datetime.now(timezone.utc) - published.astimezone(timezone.utc)).days
    if days <= 90:
        return 5
    if days <= 180:
        return 4
    if days <= 365:
        return 3
    if days <= 730:
        return 2
    return 1


def load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_evidence_items(evidence: list[dict[str, Any]], schema: dict[str, Any]) -> list[str]:
    try:
        from jsonschema import Draft7Validator
    except ImportError:
        return basic_validate_evidence_items(evidence)

    validator = Draft7Validator(schema)
    errors: list[str] = []
    for index, item in enumerate(evidence):
        for err in validator.iter_errors(item):
            path = ".".join(str(part) for part in err.absolute_path) or "<root>"
            errors.append(f"evidence[{index}].{path}: {err.message}")
    return errors


def basic_validate_evidence_items(evidence: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for index, item in enumerate(evidence):
        missing = REQUIRED_FIELDS - item.keys()
        for field in sorted(missing):
            errors.append(f"evidence[{index}].{field}: missing required field")
        if item.get("source_type") not in VALID_SOURCE_TYPES:
            errors.append(f"evidence[{index}].source_type: invalid value '{item.get('source_type')}'")
        if item.get("retrieval_status") not in VALID_RETRIEVAL_STATUS:
            errors.append(
                f"evidence[{index}].retrieval_status: invalid value '{item.get('retrieval_status')}'"
            )
        if item.get("confidence") not in VALID_CONFIDENCE:
            errors.append(f"evidence[{index}].confidence: invalid value '{item.get('confidence')}'")
    return errors


def summarize_run(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for item in evidence:
        by_status[item["retrieval_status"]] = by_status.get(item["retrieval_status"], 0) + 1
        by_type[item["source_type"]] = by_type.get(item["source_type"], 0) + 1
    return {
        "total_evidence": len(evidence),
        "by_status": by_status,
        "by_source_type": by_type,
    }


def normalize_date(value: Any) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(text[:19], fmt)
            return (
                parsed.date().isoformat()
                if "T" not in fmt and " " not in fmt
                else parsed.replace(tzinfo=timezone.utc).isoformat()
            )
        except ValueError:
            continue
    return text


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())