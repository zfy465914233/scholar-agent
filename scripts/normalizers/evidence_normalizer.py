from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse

from common import now_iso


VALID_SOURCE_TYPES = {"github", "arxiv", "blog", "docs", "forum", "paper", "patent", "other"}


def normalize_candidate(candidate: Any, fetched_text: str, retrieval_status: str = "partial") -> dict[str, Any]:
    query = str(_candidate_value(candidate, "query", "") or "")
    candidate_url = _candidate_url(candidate)
    url = candidate_url or _fallback_candidate_uri(candidate)
    title = str(_candidate_value(candidate, "title", "") or "").strip() or _fallback_title(candidate)
    snippet = str(_candidate_value(candidate, "snippet", "") or "").strip()
    published_at = _candidate_published_at(candidate)
    source_type = _infer_source_type(candidate, candidate_url)
    retrieved_at = now_iso()
    content_md = fetched_text.strip()
    summary = _summarize_text(content_md, snippet)

    evidence = {
        "query": query,
        "source_type": source_type,
        "url": url,
        "title": title,
        "summary": summary,
        "content_md": content_md,
        "published_at": published_at,
        "retrieved_at": retrieved_at,
        "provenance": {
            "provider": _candidate_provider(candidate),
            "query": query,
            "retrieved_at": retrieved_at,
            "url": candidate_url,
        },
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
        "evidence_spans": _pick_evidence_spans(content_md, snippet),
        "confidence": "confirmed" if retrieval_status in {"succeeded", "cached"} else "likely",
        "retrieval_status": retrieval_status,
        "scores": _score_evidence(source_type, published_at, retrieval_status),
    }
    return evidence


def _candidate_value(candidate: Any, name: str, default: Any = None) -> Any:
    if isinstance(candidate, dict):
        return candidate.get(name, default)
    return getattr(candidate, name, default)


def _candidate_metadata(candidate: Any) -> dict[str, Any]:
    metadata = _candidate_value(candidate, "provider_metadata", None)
    if isinstance(metadata, dict):
        return metadata
    metadata = _candidate_value(candidate, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    return {}


def _candidate_url(candidate: Any) -> str | None:
    value = _candidate_value(candidate, "url", None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _candidate_published_at(candidate: Any) -> str | None:
    value = _candidate_value(candidate, "published_at", None)
    if value is None:
        value = _candidate_value(candidate, "publishedDate", None)
    return _normalize_published_at(value)


def _candidate_provider(candidate: Any) -> str:
    for name in ("provider", "provider_name"):
        value = _candidate_value(candidate, name, None)
        if value:
            return str(value).strip() or "unknown"
    metadata = _candidate_metadata(candidate)
    value = metadata.get("provider") or metadata.get("provider_name")
    if value:
        return str(value).strip() or "unknown"
    return "unknown"


def _fallback_title(candidate: Any) -> str:
    url = _candidate_url(candidate)
    if url:
        return url
    snippet = str(_candidate_value(candidate, "snippet", "") or "").strip()
    if snippet:
        return snippet[:120]
    return "Untitled result"


def _fallback_candidate_uri(candidate: Any) -> str:
    payload = "|".join(
        [
            _candidate_provider(candidate),
            str(_candidate_value(candidate, "query", "") or "").strip(),
            str(_candidate_value(candidate, "title", "") or "").strip(),
            str(_candidate_value(candidate, "snippet", "") or "").strip(),
            str(
                _normalize_published_at(
                    _candidate_value(candidate, "published_at", None) or _candidate_value(candidate, "publishedDate", None)
                )
                or ""
            ),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"urn:scholar-agent:candidate:{digest}"


def _infer_source_type(candidate: Any, url: str | None) -> str:
    explicit = _candidate_value(candidate, "source_type", None)
    if explicit:
        explicit_text = str(explicit).strip().lower()
        if explicit_text in VALID_SOURCE_TYPES:
            return explicit_text

    metadata = _candidate_metadata(candidate)
    explicit = metadata.get("source_type")
    if explicit:
        explicit_text = str(explicit).strip().lower()
        if explicit_text in VALID_SOURCE_TYPES:
            return explicit_text

    if not url:
        return "other"

    host = urlparse(url).netloc.lower()
    if "github.com" in host:
        return "github"
    if "arxiv.org" in host:
        return "arxiv"
    if any(host.endswith(suffix) for suffix in (".gov", ".edu", ".org")):
        return "docs"
    if any(domain in host for domain in ("medium.com", "substack.com", "blogspot.com")):
        return "blog"
    return "other"


def _summarize_text(text: str, fallback: str) -> str:
    base = text.strip() or fallback.strip()
    if not base:
        return "No textual content retrieved; only metadata is available."
    compact = " ".join(base.split())
    return compact[:500]


def _normalize_published_at(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    for candidate in (normalized, normalized.replace(" ", "T")):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return parsed.date().isoformat()
    try:
        return date.fromisoformat(normalized[:10]).isoformat()
    except ValueError:
        return None


def _pick_evidence_spans(text: str, fallback: str) -> list[str]:
    spans: list[str] = []
    compact = " ".join(text.split()).strip()
    if compact:
        spans.append(compact[:220])
    fallback_text = fallback.strip()
    if fallback_text and fallback_text not in spans:
        spans.append(fallback_text[:220])
    return spans[:2]


def _score_evidence(source_type: str, published_at: str | None, retrieval_status: str) -> dict[str, float]:
    freshness = 0.0 if not published_at else 1.0
    credibility_map = {
        "docs": 5.0,
        "github": 4.0,
        "arxiv": 4.0,
        "paper": 4.0,
        "blog": 3.0,
        "forum": 2.0,
        "patent": 4.0,
        "other": 2.0,
    }
    reproducibility_map = {
        "github": 5.0,
        "docs": 4.0,
        "paper": 3.0,
        "arxiv": 3.0,
        "blog": 2.0,
        "forum": 1.0,
        "patent": 1.0,
        "other": 1.0,
    }
    community = 3.0 if source_type == "github" and retrieval_status in {"succeeded", "cached"} else 1.0
    return {
        "freshness": freshness,
        "credibility": credibility_map.get(source_type, 1.0),
        "reproducibility": reproducibility_map.get(source_type, 1.0),
        "community_activity": community,
    }
