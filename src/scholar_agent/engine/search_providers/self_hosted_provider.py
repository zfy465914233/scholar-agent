from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from scholar_agent.engine.common import normalize_date
from scholar_agent.engine.retry import retry_with_backoff
from scholar_agent.engine.search_providers.base import ProviderResult, SearchCandidate, SearchProvider


class AcademicProvider(SearchProvider):
    provider_name = "academic"

    def search(self, query: str, limit: int | None = None) -> ProviderResult:
        if limit is not None and limit <= 0:
            return ProviderResult(provider=self.provider_name, query=query)

        raw_items: list[dict[str, Any]] = []
        candidates: list[SearchCandidate] = []
        seen_urls: set[str] = set()

        raw_items = search_openalex(query)
        candidates, seen_urls = self._extend_candidates(query, raw_items, candidates, seen_urls, limit)
        if limit is not None and len(candidates) >= limit:
            return ProviderResult(
                provider=self.provider_name,
                query=query,
                candidates=candidates,
                metadata={"source_count": len(candidates)},
            )

        raw_items = search_semanticscholar(query)
        candidates, seen_urls = self._extend_candidates(query, raw_items, candidates, seen_urls, limit)

        return ProviderResult(
            provider=self.provider_name,
            query=query,
            candidates=candidates,
            metadata={"source_count": len(candidates)},
        )

    def _extend_candidates(
        self,
        query: str,
        raw_items: list[dict[str, Any]],
        candidates: list[SearchCandidate],
        seen_urls: set[str],
        limit: int | None,
    ) -> tuple[list[SearchCandidate], set[str]]:
        for item in raw_items:
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
            if limit is not None and len(candidates) >= limit:
                break
        return candidates, seen_urls


def search_openalex(query: str) -> list[dict[str, Any]]:
    url = f"https://api.openalex.org/works?search={quote_plus(query)}"
    request = Request(url, headers={"User-Agent": "scholar-agent/1.0 (mailto:scholar@example.com)"})

    def _do_search() -> list[dict[str, Any]]:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        results = []
        for item in payload.get("results", [])[:5]:
            results.append(
                {
                    "url": item.get("doi") or item.get("id"),
                    "title": item.get("title", ""),
                    "content": "",
                    "publishedDate": item.get("publication_date", ""),
                }
            )
        return results

    try:
        return retry_with_backoff(
            _do_search,
            max_retries=2,
            base_delay=2.0,
            retry_on=(HTTPError, URLError, OSError),
        )
    except (HTTPError, URLError, OSError, json.JSONDecodeError):
        return []


def search_semanticscholar(query: str) -> list[dict[str, Any]]:
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={quote_plus(query)}&limit=5&fields=title,url,abstract,year"
    request = Request(url, headers={"User-Agent": "scholar-agent/1.0"})

    def _do_search() -> list[dict[str, Any]]:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        results = []
        for item in payload.get("data", []):
            results.append(
                {
                    "url": item.get("url", ""),
                    "title": item.get("title", ""),
                    "content": item.get("abstract", ""),
                    "publishedDate": f"{item.get('year')}-01-01" if item.get("year") else "",
                }
            )
        return results

    try:
        return retry_with_backoff(
            _do_search,
            max_retries=3,
            base_delay=2.0,
            retry_on=(HTTPError, URLError, OSError),
        )
    except (HTTPError, URLError, OSError, json.JSONDecodeError):
        return []
