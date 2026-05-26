from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class SearchCandidate:
    query: str
    url: str
    title: str
    snippet: str
    published_at: str | None


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    query: str
    candidates: list[SearchCandidate] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SearchProvider(Protocol):
    provider_name: str

    def search(self, query: str, limit: int | None = None) -> ProviderResult:
        raise NotImplementedError
