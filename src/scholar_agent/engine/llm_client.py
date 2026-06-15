"""Unified LLM client — single entry point for all LLM calls.

Consolidates credential resolution, provider format normalization,
retry logic, and error handling.  Every LLM call in the codebase
should route through this module.

Provider priority:
  1. SCHOLAR_FILLER_* explicit override
  2. ANTHROPIC_* credentials
  3. OpenAI-compatible (SCHOLAR_ROUTER_* / LLM_* / OPENAI_* / GITHUB_TOKEN)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scholar_agent.engine.retry import retry_with_backoff

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""

    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    provider_format: str = ""


@dataclass
class ProviderConfig:
    """A single LLM provider configuration."""

    format: str  # "anthropic" or "openai"
    url: str
    key: str
    model: str


# ---------------------------------------------------------------------------
# Credential resolution (3-priority system, with short-lived cache)
# ---------------------------------------------------------------------------

_resolved_cache: list[ProviderConfig] | None = None
_cache_ts: float = 0.0
_CACHE_TTL = 300.0  # seconds


def resolve_providers(force: bool = False) -> list[ProviderConfig]:
    """Resolve available LLM providers from environment variables.

    Returns a deduplicated list ordered by priority.  Results are cached
    for 5 minutes unless *force* is True.
    """
    global _resolved_cache, _cache_ts

    if not force and _resolved_cache is not None and time.monotonic() - _cache_ts < _CACHE_TTL:
        return _resolved_cache

    providers: list[ProviderConfig] = []
    seen: set[tuple[str, str]] = set()

    def _add(fmt: str, url: str, key: str, model: str) -> None:
        sig = (fmt, url.rstrip("/"))
        if sig not in seen and key:
            seen.add(sig)
            providers.append(ProviderConfig(format=fmt, url=url, key=key, model=model))

    # Priority 1 — explicit SCHOLAR_FILLER_* override
    if os.getenv("SCHOLAR_FILLER_API_FORMAT") or os.getenv("SCHOLAR_FILLER_API_URL"):
        fmt = os.getenv("SCHOLAR_FILLER_API_FORMAT", "").lower()
        if fmt not in ("anthropic", "openai"):
            fmt = "openai"
        key = (
            os.getenv("SCHOLAR_FILLER_API_KEY", "")
            or os.getenv("ANTHROPIC_AUTH_TOKEN", "")
            or os.getenv("ANTHROPIC_API_KEY", "")
        )
        if fmt == "anthropic":
            url = os.getenv("SCHOLAR_FILLER_API_URL", "") or os.getenv(
                "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
            )
            model = os.getenv("SCHOLAR_FILLER_MODEL", "") or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        else:
            url = os.getenv("SCHOLAR_FILLER_API_URL", "") or os.getenv("LLM_API_URL", "https://api.openai.com/v1")
            model = os.getenv("SCHOLAR_FILLER_MODEL", "") or os.getenv("LLM_MODEL", "gpt-4o-mini")
        _add(fmt, url, key, model)

    # Priority 2 — Anthropic credentials
    anth_key = os.getenv("ANTHROPIC_AUTH_TOKEN", "") or os.getenv("ANTHROPIC_API_KEY", "")
    if anth_key:
        _add(
            "anthropic",
            os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            anth_key,
            os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        )

    # Priority 3 — OpenAI-compatible credentials
    oai_key = (
        os.getenv("SCHOLAR_ROUTER_API_KEY", "")
        or os.getenv("LLM_API_KEY", "")
        or os.getenv("OPENAI_API_KEY", "")
        or os.getenv("GITHUB_TOKEN", "")
    )
    if oai_key:
        oai_url = (
            os.getenv("SCHOLAR_ROUTER_API_URL", "")
            or os.getenv("LLM_API_URL", "")
            or os.getenv("OPENAI_BASE_URL", "")
            or "https://api.openai.com/v1"
        )
        oai_model = os.getenv("SCHOLAR_ROUTER_MODEL", "") or os.getenv("LLM_MODEL", "") or "gpt-4o-mini"
        _add("openai", oai_url, oai_key, oai_model)

    _resolved_cache = providers
    _cache_ts = time.monotonic()
    return providers


def resolve_openai_provider() -> ProviderConfig | None:
    """Resolve a single OpenAI-compatible provider (for domain_router etc.).

    Falls back to SCHOLAR_ROUTER_* → LLM_* → OPENAI_* → GITHUB_TOKEN.
    """
    key = (
        os.getenv("SCHOLAR_ROUTER_API_KEY", "")
        or os.getenv("LLM_API_KEY", "")
        or os.getenv("OPENAI_API_KEY", "")
        or os.getenv("GITHUB_TOKEN", "")
    )
    if not key:
        return None
    url = (
        os.getenv("SCHOLAR_ROUTER_API_URL", "")
        or os.getenv("LLM_API_URL", "")
        or os.getenv("OPENAI_BASE_URL", "")
        or "https://api.openai.com/v1"
    )
    model = os.getenv("SCHOLAR_ROUTER_MODEL", "") or os.getenv("LLM_MODEL", "") or "gpt-4o-mini"
    return ProviderConfig(format="openai", url=url, key=key, model=model)


# ---------------------------------------------------------------------------
# HTTP transport helpers
# ---------------------------------------------------------------------------


def _send_anthropic(
    provider: ProviderConfig,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    timeout: float = 300.0,
) -> dict[str, Any]:
    """Build and send an Anthropic Messages API request."""
    system_parts: list[str] = []
    chat_msgs: list[dict[str, str]] = []
    for msg in messages:
        if msg["role"] == "system":
            system_parts.append(msg["content"])
        else:
            chat_msgs.append({"role": msg["role"], "content": msg["content"]})

    body: dict[str, Any] = {
        "model": provider.model,
        "max_tokens": max_tokens,
        "messages": chat_msgs or [{"role": "user", "content": ""}],
    }
    if system_parts:
        body["system"] = "\n".join(system_parts)
    if temperature != 1.0:
        body["temperature"] = temperature

    base = provider.url.rstrip("/")
    if base.endswith("/messages"):
        url = base
    elif base.endswith("/v1"):
        url = base + "/messages"
    else:
        url = base + "/v1/messages"

    req = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": provider.key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        return dict(json.loads(resp.read().decode("utf-8")))  # type: ignore[arg-type]


def _send_openai(
    provider: ProviderConfig,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Build and send an OpenAI Chat Completions API request."""
    body: dict[str, Any] = {
        "model": provider.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    base = provider.url.rstrip("/")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if provider.key:
        headers["Authorization"] = f"Bearer {provider.key}"

    req = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        return dict(json.loads(resp.read().decode("utf-8")))  # type: ignore[arg-type]


def _parse_anthropic(data: dict[str, Any]) -> LLMResponse:
    """Parse Anthropic Messages API response into LLMResponse."""
    if "error" in data:
        err = data["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise RuntimeError(f"Anthropic API error: {msg}")

    content = ""
    blocks = data.get("content", [])
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                content = block.get("text", "")
                break

    if not content:
        for key in ("output", "text", "response", "result"):
            if key in data:
                val = data[key]
                if isinstance(val, str):
                    content = val
                    break
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict) and item.get("type") == "text":
                            content = item.get("text", "")
                            break
                    if content:
                        break

    if not content:
        raise KeyError(
            f"Anthropic response missing 'content' key. "
            f"Available keys: {list(data.keys())}. "
            f"Response preview: {json.dumps(data)[:200]}"
        )

    usage = data.get("usage", {})
    return LLMResponse(
        content=content.strip(),
        model=data.get("model", ""),
        usage={
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        },
        provider_format="anthropic",
    )


def _parse_openai(data: dict[str, Any]) -> LLMResponse:
    """Parse OpenAI Chat Completions API response into LLMResponse."""
    if "error" in data:
        err = data["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise RuntimeError(f"OpenAI API error: {msg}")

    choices = data.get("choices", [])
    content: str = ""
    if choices:
        content = choices[0].get("message", {}).get("content", "") or ""

    resp_usage = data.get("usage", {})
    return LLMResponse(
        content=str(content).strip() if content else "",
        model=data.get("model", ""),
        usage={
            "prompt_tokens": resp_usage.get("prompt_tokens", 0),
            "completion_tokens": resp_usage.get("completion_tokens", 0),
            "total_tokens": resp_usage.get("total_tokens", 0),
        },
        provider_format="openai",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUTS: dict[str, float] = {
    "anthropic": 300.0,
    "openai": 60.0,
}


def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    timeout: float | None = None,
    max_retries: int = 2,
    provider: ProviderConfig | None = None,
) -> LLMResponse:
    """Send a chat completion request.

    If *provider* is None, resolves the highest-priority provider from
    environment variables.  Uses retry_with_backoff for transient errors.
    """
    if provider is None:
        providers = resolve_providers()
        if not providers:
            raise RuntimeError("No LLM provider configured. Set LLM_API_KEY or ANTHROPIC_API_KEY.")
        provider = providers[0]

    effective = provider
    if model and model != provider.model:
        effective = ProviderConfig(
            format=provider.format,
            url=provider.url,
            key=provider.key,
            model=model,
        )

    tout = timeout or _DEFAULT_TIMEOUTS.get(effective.format, 60.0)

    def _call() -> LLMResponse:
        logger.debug("LLM request: %s %s msgs=%d", effective.format, effective.model, len(messages))
        if effective.format == "anthropic":
            raw = _send_anthropic(effective, messages, max_tokens=max_tokens, temperature=temperature, timeout=tout)
            resp = _parse_anthropic(raw)
        else:
            raw = _send_openai(effective, messages, max_tokens=max_tokens, temperature=temperature, timeout=tout)
            resp = _parse_openai(raw)
        logger.debug("LLM response: %d chars, usage=%s", len(resp.content), resp.usage)
        return resp

    try:
        response = retry_with_backoff(
            _call,
            max_retries=max_retries,
            retry_on=(HTTPError, URLError, OSError, RuntimeError),
        )
    except Exception:
        # All retries exhausted — record the failure for observability.
        from scholar_agent.engine import metrics

        metrics.record_llm_call(failed=True)
        raise

    from scholar_agent.engine import metrics

    metrics.record_llm_call(response.usage)
    return response


def chat_with_fallback(
    messages: list[dict[str, str]],
    *,
    providers: list[ProviderConfig] | None = None,
    max_retries: int = 0,
    **kwargs: Any,
) -> LLMResponse:
    """Try providers in priority order until one succeeds.

    Falls back to resolve_providers() if *providers* is None.
    """
    provider_list = providers or resolve_providers()
    last_exc: Exception | None = None

    for prov in provider_list:
        try:
            return chat(messages, provider=prov, max_retries=max_retries, **kwargs)
        except Exception as exc:
            logger.warning("Provider %s (%s) failed: %s — trying next", prov.format, prov.model, exc)
            last_exc = exc

    if last_exc:
        raise last_exc
    raise RuntimeError("No LLM providers available")
