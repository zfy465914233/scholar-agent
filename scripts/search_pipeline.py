from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from inputs.external_candidates import ExternalCandidateBatch, parse_external_candidate_batch
from normalizers.evidence_normalizer import normalize_candidate
from search_providers.base import ProviderResult, SearchProvider


def canonicalize_url(url: str | None) -> str | None:
    if url is None:
        return None
    text = str(url).strip()
    if not text:
        return None

    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path or ""
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(parse_qsl(parts.query, keep_blank_values=True))
    canonical = urlunsplit((scheme, netloc, path, query, ""))
    return canonical or None


def candidate_identity(candidate: Any) -> str:
    canonical_url = canonicalize_url(_candidate_value(candidate, "url"))
    if canonical_url:
        return f"url:{canonical_url}"

    payload = "|".join(
        [
            str(_candidate_value(candidate, "provider", "") or _candidate_value(candidate, "provider_name", "") or "").strip(),
            str(_candidate_value(candidate, "query", "") or "").strip(),
            str(_candidate_value(candidate, "title", "") or "").strip(),
            str(_candidate_value(candidate, "snippet", "") or "").strip(),
            str(_candidate_value(candidate, "published_at", "") or "").strip(),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"hash:{digest}"


def merge_candidates(
    internal_candidates: list[Any],
    external_candidates: list[Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    merged: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    total_count = len(internal_candidates) + len(external_candidates)

    for candidate in [*internal_candidates, *external_candidates]:
        serialized = _serialize_candidate(candidate)
        identity = candidate_identity(serialized)
        existing = merged.get(identity)
        if existing is None:
            merged[identity] = serialized
            continue

        duplicate_count += 1
        merged[identity] = _prefer_richer_candidate(existing, serialized)

    return list(merged.values()), {
        "candidate_count": total_count,
        "deduped_count": len(merged),
        "duplicate_count": duplicate_count,
    }


def run_search_pipeline(
    query: str,
    providers: list[SearchProvider],
    external_batch: ExternalCandidateBatch | dict[str, Any] | None = None,
    fetch_contents: bool = False,
) -> dict[str, Any]:
    parsed_external_batch = _coerce_external_batch(external_batch)

    provider_results: list[ProviderResult] = [provider.search(query) for provider in providers]
    serialized_provider_results = [_serialize_provider_result(result) for result in provider_results]

    internal_candidates = [
        {
            **_serialize_candidate(candidate),
            "provider": result.provider,
        }
        for result in provider_results
        for candidate in result.candidates
    ]
    external_candidates = _external_candidates_to_dicts(parsed_external_batch)

    merged_candidates, summary = merge_candidates(internal_candidates, external_candidates)

    evidence = [
        normalize_candidate(
            candidate,
            fetched_text="" if not fetch_contents else "",
        )
        for candidate in merged_candidates
    ]

    return {
        "query": query,
        "provider_results": serialized_provider_results,
        "external_batch": _serialize_external_batch(parsed_external_batch),
        "merged_candidates": merged_candidates,
        "evidence": evidence,
        "summary": {
            "provider_count": len(providers),
            "internal_candidate_count": len(internal_candidates),
            "external_candidate_count": len(external_candidates),
            **summary,
        },
    }


def _coerce_external_batch(
    external_batch: ExternalCandidateBatch | dict[str, Any] | None,
) -> ExternalCandidateBatch | None:
    if external_batch is None:
        return None
    if isinstance(external_batch, ExternalCandidateBatch):
        return external_batch
    return parse_external_candidate_batch(external_batch)


def _external_candidates_to_dicts(batch: ExternalCandidateBatch | None) -> list[dict[str, Any]]:
    if batch is None:
        return []
    return [
        {
            "provider": batch.source,
            "query": batch.query,
            "title": candidate.title,
            "url": candidate.url,
            "snippet": candidate.snippet,
            "published_at": None,
        }
        for candidate in batch.candidates
    ]


def _serialize_provider_result(result: ProviderResult) -> dict[str, Any]:
    return {
        "provider": result.provider,
        "query": result.query,
        "candidates": [_serialize_candidate(candidate) for candidate in result.candidates],
        "metadata": dict(result.metadata),
    }


def _serialize_external_batch(batch: ExternalCandidateBatch | None) -> dict[str, Any] | None:
    if batch is None:
        return None
    return {
        "source": batch.source,
        "query": batch.query,
        "candidates": [
            {
                "title": candidate.title,
                "url": candidate.url,
                "snippet": candidate.snippet,
            }
            for candidate in batch.candidates
        ],
    }


def _serialize_candidate(candidate: Any) -> dict[str, Any]:
    raw = {
        "provider": _candidate_value(candidate, "provider", None) or _candidate_value(candidate, "provider_name", None),
        "query": _candidate_value(candidate, "query", ""),
        "url": canonicalize_url(_candidate_value(candidate, "url")),
        "title": _candidate_value(candidate, "title", ""),
        "snippet": _candidate_value(candidate, "snippet", ""),
        "published_at": _candidate_value(candidate, "published_at", None),
    }
    if raw["url"] is None:
        raw["url"] = _fallback_candidate_uri(raw)
    return raw


def _candidate_value(candidate: Any, name: str, default: Any = None) -> Any:
    if isinstance(candidate, dict):
        return candidate.get(name, default)
    return getattr(candidate, name, default)


def _prefer_richer_candidate(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_score = _candidate_richness(left)
    right_score = _candidate_richness(right)
    if right_score > left_score:
        return right
    return left


def _candidate_richness(candidate: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        1 if candidate.get("url") else 0,
        1 if candidate.get("published_at") else 0,
        len(str(candidate.get("snippet") or "")),
        len(str(candidate.get("title") or "")),
    )


def _fallback_candidate_uri(candidate: dict[str, Any]) -> str:
    payload = "|".join(
        [
            str(candidate.get("provider") or "").strip(),
            str(candidate.get("query") or "").strip(),
            str(candidate.get("title") or "").strip(),
            str(candidate.get("snippet") or "").strip(),
            str(candidate.get("published_at") or "").strip(),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"urn:scholar-agent:candidate:{digest}"
