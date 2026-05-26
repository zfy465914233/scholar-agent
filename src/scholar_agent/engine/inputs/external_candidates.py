from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ExternalCandidate:
    title: str
    url: str | None
    snippet: str


@dataclass(slots=True)
class ExternalCandidateBatch:
    source: str
    query: str
    candidates: list[ExternalCandidate]


def _require_non_empty_string(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing or invalid {key}")
    return value


def parse_external_candidate_batch(payload: dict) -> ExternalCandidateBatch:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dictionary")

    source = _require_non_empty_string(payload, "source")
    query = _require_non_empty_string(payload, "query")

    candidates_payload = payload.get("candidates")
    if not isinstance(candidates_payload, list) or not candidates_payload:
        raise ValueError("missing or invalid candidates")

    candidates: list[ExternalCandidate] = []
    for candidate_payload in candidates_payload:
        if not isinstance(candidate_payload, dict):
            raise ValueError("candidate entries must be dictionaries")

        title = _require_non_empty_string(candidate_payload, "title")
        snippet = _require_non_empty_string(candidate_payload, "snippet")
        url = candidate_payload.get("url")
        if url is not None and (not isinstance(url, str) or not url.strip()):
            raise ValueError("candidate url must be a string or null")

        candidates.append(ExternalCandidate(title=title, url=url, snippet=snippet))

    return ExternalCandidateBatch(source=source, query=query, candidates=candidates)
