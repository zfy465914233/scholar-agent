"""Scholar Agent — MCP server exposing knowledge tools to Claude Code and Copilot.

SCHOLAR_TOOLSET selects which tools the server exposes (see resolve_toolset):
unset / ``default`` / ``all`` = everything; otherwise a list of the groups below.

``core`` — knowledge read/write:
  - query_knowledge: Search the local knowledge base
  - list_knowledge: Browse all knowledge cards, optionally filtered by topic
  - save_research: Persist structured research results as a knowledge card
  - capture_answer: Capture a Q&A answer as a draft knowledge card
  - review_card: Adjust a card's trust state on the user's explicit instruction
  - ingest_source: Ingest a URL or raw text into the knowledge base
  - fetch_url: Fetch a web URL → main content as markdown + local snapshot (G5/G2)

``paper`` — paper notes and graph:
  - build_graph: Build an interactive knowledge graph visualization
  - import_paperpulse_note: Import a distilled PaperPulse note into the knowledge base
  - Academic tools, registered only with SCHOLAR_ACADEMIC=1: search_papers,
    search_conf_papers, analyze_paper, download_paper, extract_paper_images,
    paper_to_card, daily_recommend, link_paper_keywords

``maintenance`` — read-only governance:
  - validate_knowledge: Validate local knowledge cards without writing files
  - lint_knowledge: Report content-level knowledge graph issues without writing files
  - scan_stale_knowledge: Report stale cards without writing files
  - scan_dead_links: Diagnose dead source URLs across knowledge cards

Usage:
  scholar-agent serve-mcp
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

from scholar_agent.adapters.http_server import start_local_server
from scholar_agent.engine.close_knowledge_loop import (
    QUALITY_THRESHOLD_CAPTURE_ANSWER,
    QUALITY_THRESHOLD_SAVE_RESEARCH,
    build_knowledge_card,
    confidence_from_quality,
    quality_score_answer_data,
    validate_answer_schema,
)
from scholar_agent.engine.common import (
    parse_frontmatter,
    resolve_link_target,
    sanitize_title,
)
from scholar_agent.engine.index_lifecycle import async_reindex as _async_reindex
from scholar_agent.engine.index_lifecycle import ensure_ready as _ensure_index_ready
from scholar_agent.engine.local_retrieve import retrieve
from scholar_agent.engine.scholar_config import (
    _configured_index_path,
    get_daily_notes_dir,
    get_index_path,
    get_knowledge_dir,
    get_paper_notes_dir,
    get_research_interests,
    load_config,
)

logger = logging.getLogger(__name__)

# Academic tools module toggle (set SCHOLAR_ACADEMIC=1 to enable)
SCHOLAR_ACADEMIC = os.environ.get("SCHOLAR_ACADEMIC", "").strip() in ("1", "true", "yes")

try:
    from fastmcp import Context, FastMCP

    mcp = FastMCP("scholar-agent")
    tool = mcp.tool
except ImportError:
    # Allow running without fastmcp — decorators become no-ops
    mcp = None  # type: ignore[assignment]
    Context = None  # type: ignore[assignment,misc]

    def tool(fn):  # type: ignore[misc]
        return fn


# ── Toolset selection (SCHOLAR_TOOLSET) ────────────────────────────
# Every tool registers at import time through @tool, so the selection can only
# happen at startup (main()) — never at module level, which would strip tools
# from every test that imports this module.

# Registered by adapters.mcp_academic.register_academic_tools (only when
# SCHOLAR_ACADEMIC=1); members of the ``paper`` group.
ACADEMIC_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "search_papers",
        "search_conf_papers",
        "analyze_paper",
        "download_paper",
        "extract_paper_images",
        "paper_to_card",
        "daily_recommend",
        "link_paper_keywords",
    }
)

TOOLSET_GROUPS: dict[str, frozenset[str]] = {
    "core": frozenset(
        {
            "query_knowledge",
            "list_knowledge",
            "save_research",
            "capture_answer",
            "review_card",
            "ingest_source",
            "fetch_url",
        }
    ),
    "paper": frozenset({"build_graph", "import_paperpulse_note"}) | ACADEMIC_TOOL_NAMES,
    "maintenance": frozenset({"validate_knowledge", "lint_knowledge", "scan_stale_knowledge", "scan_dead_links"}),
}

# Reserved values that expose every registered tool.
TOOLSET_ALL: tuple[str, ...] = ("default", "all")


class ToolsetError(ValueError):
    """Invalid ``SCHOLAR_TOOLSET`` value (unknown group name)."""


def resolve_toolset(toolset: str | None, registered: Collection[str]) -> set[str]:
    """Return the subset of *registered* tool names that *toolset* exposes.

    Pure function and single source of truth for the ``SCHOLAR_TOOLSET``
    syntax: unset, empty, ``default`` or ``all`` expose every registered tool;
    anything else is a list of group names (:data:`TOOLSET_GROUPS` keys)
    separated by commas, spaces or ``+``, case-insensitive. An unknown group
    raises :class:`ToolsetError` naming the legal values — never skipped silently.
    """
    names = set(registered)
    tokens = [token for token in re.split(r"[,\s+]+", (toolset or "").strip().lower()) if token]
    if not tokens:
        return names
    requested: set[str] = set()
    for token in tokens:
        if token in TOOLSET_ALL:
            return names
        if token not in TOOLSET_GROUPS:
            legal = ", ".join((*TOOLSET_ALL, *TOOLSET_GROUPS))
            raise ToolsetError(f"unknown group {token!r}; expected a list of: {legal}")
        requested.add(token)
    keep: set[str] = set()
    for group in requested:
        keep |= TOOLSET_GROUPS[group]
    return names & keep


def _remove_tool(mcp: FastMCP, name: str) -> None:
    """Unregister *name* on *mcp*.

    fastmcp >= 3 deprecates ``FastMCP.remove_tool`` in favour of the local
    provider's; fastmcp 2.x only has the former.
    """
    provider = getattr(mcp, "local_provider", None)
    if provider is not None and hasattr(provider, "remove_tool"):
        provider.remove_tool(name)
    else:
        mcp.remove_tool(name)


async def _registered_tool_names(mcp: FastMCP) -> list[str]:
    return [tool.name for tool in await mcp.list_tools()]


def apply_toolset(mcp: FastMCP, toolset: str | None, registered: Collection[str]) -> set[str]:
    """Unregister every tool that *toolset* excludes, in place on *mcp*.

    Call once at startup, after every ``@tool`` registration. Returns the names
    kept. An unknown group raises :class:`ToolsetError` before *mcp* is touched.
    """
    keep = resolve_toolset(toolset, registered)
    for name in sorted(set(registered) - keep):
        _remove_tool(mcp, name)
    return keep


# ── Long-running tool execution (non-blocking + timeout + progress) ──
#
# Heavy tools (PDF download, LLM fill, tarball extraction, daily workflow) run
# in a worker thread so they never block the asyncio event loop, are bounded by
# a configurable timeout, and can report coarse progress + honor MCP-native
# cancellation. NOTE: a worker thread cannot be force-killed; on timeout or
# client cancellation the awaiting request returns immediately and the loop is
# freed, but the orphaned thread runs to completion and its result is discarded.

# Default per-tool timeouts in seconds. 0 / negative env value disables timeout.
_DEFAULT_TOOL_TIMEOUTS: dict[str, float] = {
    "analyze_paper": 600.0,
    "extract_paper_images": 300.0,
    "download_paper": 300.0,
    "daily_recommend": 1800.0,
    "fetch_url": 60.0,
    "ingest_source": 60.0,
    "import_paperpulse_note": 120.0,
}


def _tool_timeout(tool_name: str) -> float | None:
    """Resolve the timeout (seconds) for a tool.

    Precedence: SCHOLAR_<TOOL>_TIMEOUT env > SCHOLAR_TOOL_TIMEOUT env > default.
    A value <= 0 disables the timeout (returns None).
    """
    for env_key in (f"SCHOLAR_{tool_name.upper()}_TIMEOUT", "SCHOLAR_TOOL_TIMEOUT"):
        raw = os.environ.get(env_key, "").strip()
        if raw:
            try:
                value = float(raw)
            except ValueError:
                logger.warning("Invalid %s=%r — ignoring", env_key, raw)
                continue
            return value if value > 0 else None
    return _DEFAULT_TOOL_TIMEOUTS.get(tool_name)


async def _run_blocking(fn: Callable[[], str], *, tool_name: str, ctx: Any = None) -> str:
    """Run a blocking, JSON-string-returning callable off the event loop.

    Provides a bounded timeout, coarse start/finish progress (when a FastMCP
    Context is supplied), and propagates cancellation so MCP request
    cancellation works.
    """
    timeout = _tool_timeout(tool_name)
    if ctx is not None:
        with contextlib.suppress(Exception):
            await ctx.report_progress(0.0, 1.0, f"{tool_name} started")
    try:
        if timeout is not None:
            result = await asyncio.wait_for(asyncio.to_thread(fn), timeout)
        else:
            result = await asyncio.to_thread(fn)
    except asyncio.TimeoutError:
        logger.warning("%s timed out after %ss", tool_name, timeout)
        return json.dumps(
            {"status": "timeout", "error": f"{tool_name} timed out after {timeout}s"},
            ensure_ascii=False,
        )
    if ctx is not None:
        with contextlib.suppress(Exception):
            await ctx.report_progress(1.0, 1.0, f"{tool_name} completed")
    return result


def _validate_path_within(path: str | Path, boundary: Path) -> Path | None:
    """Resolve *path* and ensure it stays within *boundary*.

    Returns the resolved path if safe, or None if it escapes the boundary.
    """
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(boundary.resolve())
    except ValueError:
        return None
    return resolved


def _embedding_index_path(index_path: Path) -> Path | None:
    """Return the embedding index path if one exists next to the BM25 index.

    Governs the "build once, auto-enable" policy (decision D1): when a user
    has built an embedding index via ``scholar-agent index
    --build-embedding-index``, query_knowledge transparently switches to
    hybrid retrieval. Absent the file, retrieval stays BM25-only.
    """
    emb = index_path.parent / "embeddings.json"
    return emb if emb.exists() else None


# ── Metrics/usage persistence debounce ─────────────────────────────
# query_knowledge records metrics + usage on every call; each used to trigger
# a full atomic file write (metrics.json + usage.json) per query. In-memory
# counters stay exact per call — only the on-disk snapshots (read by
# `scholar-agent status` and other processes) are debounced to at most one
# flush per _PERSIST_INTERVAL seconds, with a final best-effort flush on exit.
_PERSIST_INTERVAL = 30.0
_persist_lock = threading.Lock()
_last_persist_flush = 0.0


def _persist_query_state(doc_ids: list[str]) -> None:
    """Record usage for *doc_ids*; flush metrics/usage snapshots, debounced.

    Best-effort: persistence failures must never affect the query result.
    """
    global _last_persist_flush
    from scholar_agent.engine import metrics as _metrics
    from scholar_agent.engine import usage as _usage

    with _persist_lock:
        now = time.monotonic()
        flush = now - _last_persist_flush >= _PERSIST_INTERVAL
        if flush:
            _last_persist_flush = now

    with contextlib.suppress(Exception):
        _usage.record_usage(doc_ids, persist=flush)
    if flush:
        with contextlib.suppress(Exception):
            _metrics.persist()


def _flush_query_state() -> None:
    """Best-effort final flush of the debounced metrics/usage snapshots."""
    try:
        from scholar_agent.engine import metrics as _metrics

        _metrics.persist()
    except Exception:
        pass
    try:
        from scholar_agent.engine import usage as _usage

        _usage.persist_usage()
    except Exception:
        pass


@tool
def query_knowledge(query: str, limit: int = 5, rerank: bool = False) -> str:
    """Search the local knowledge base for relevant information.

    Call this FIRST — before answering a technical or research question, writing
    a new knowledge card, or starting web research: the knowledge base may already
    hold a sourced answer. The response carries `knowledge_status` with
    `total_cards` and `draft_backlog` (cards still awaiting review).

    Returns top-k knowledge cards matching the query, with scores and content.

    Args:
        query: The search query in natural language.
        limit: Maximum number of results to return (default 5).
        rerank: When true, fetches limit*3 candidates and uses an LLM
            cross-encoder to score each (query, candidate) pair on 0-10
            relevance. Improves top-1 precision for ambiguous queries at
            the cost of one LLM call per candidate (~2s each). Default false.
    """
    if not isinstance(limit, int) or limit < 1 or limit > 50:
        return json.dumps({"error": "limit must be an integer between 1 and 50", "results": []})

    if not query or not query.strip():
        return json.dumps({"error": "query must not be empty", "results": []})

    index_path, refreshed, refresh_error = _ensure_index_ready()

    if not index_path.exists():
        return json.dumps(
            {
                "error": refresh_error or "Knowledge index not found. Run local_index.py first.",
                "results": [],
            }
        )

    result = retrieve(
        query,
        index_path,
        limit,
        rerank=rerank,
        embedding_index_path=_embedding_index_path(index_path),
    )
    if refresh_error:
        result["warning"] = refresh_error
    if refreshed:
        result["index_refreshed"] = True
    # Record which cards were surfaced (popularity signal for retrieve()) and
    # persist metrics/usage snapshots so `scholar-agent status` (a separate
    # process) can see this long-running server's accumulated counters.
    # In-memory accounting is exact per call; disk writes are debounced.
    _persist_query_state([r.get("doc_id", "") for r in result.get("results", []) if r.get("doc_id")])
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def save_research(query: str, answer_json: str, domain: str = "", language: str = "zh", card_type: str = "") -> str:
    """Save structured research results as a knowledge card in the local knowledge base.

    The answer_json must conform to schemas/answer.schema.json:
    {
      "answer": "detailed answer text",
      "supporting_claims": [{"claim": "...", "evidence_ids": ["..."], "confidence": "high|medium|low"}],
      "inferences": ["..."],
      "uncertainty": ["..."],
      "missing_evidence": ["..."],
      "suggested_next_steps": ["..."],
      "sources": ["https://example.com/source1", "https://example.com/source2"],
      "visual_aids": [{"type": "mermaid|image_url|image_path", "content": "...", "caption": "...", "alt_text": "..."}]
    }

    IMPORTANT quality requirements:
    - The "answer" field MUST be at least 200 characters of substantive content.
    - You MUST include at least 1 supporting_claim with evidence_ids and confidence.
    - Each claim text MUST be at least 20 characters — vague one-word claims are rejected.
    - DO NOT create cards with empty supporting_claims — every card needs evidence-backed claims.
    - Aim for 3+ supporting claims, inferences, uncertainty, and suggested_next_steps for high-quality cards.
    - DO NOT use this tool for trivial facts or one-sentence answers — those are not worth persisting.
    - ALWAYS include a "sources" array with the URLs you referenced during research.
      These are written to the card's frontmatter source_refs for provenance tracking.
    - evidence_ids in supporting_claims SHOULD cite the source URL (from "sources") —
      the card renders them as clickable `[host](url)` source links. Opaque ids like
      "s1" stay as bare text and lose the link.
    - For first-hand depth: call `fetch_url` on key sources BEFORE writing the answer,
      so it cites concrete numbers/mechanisms from the actual page (not memory).
      fetch_url also archives a local snapshot (knowledge/_snapshots/) so dead links
      stay traceable. save_research best-effort snapshots any listed sources in the
      background even without an explicit fetch_url.
    - When language="zh" (default), the entire answer field MUST be written in Chinese (中文).
      When language="en", write in English.

    When to include visual_aids (auto-judge by topic):
    - Processes / workflows / data flow → mermaid flowchart or sequence diagram
    - Architecture / system design → mermaid graph or class diagram
    - Comparisons or hierarchies → mermaid diagram or table
    - Spatial / geometric concepts → image_url or mermaid
    - Pure definitions or simple facts → omit visual_aids

    When sources contain useful images (charts, diagrams, figures):
    - If a source page has a relevant diagram/chart with clear explanatory value, include it
      as visual_aids with type "image_url" and the image's absolute URL
    - Judge relevance: prefer diagrams explaining mechanisms, architecture overviews,
      comparison charts, result plots — skip decorative screenshots or generic stock photos
    - Always provide a descriptive caption explaining what the image shows

    For method/procedural content (how-to, implementation, deployment, etc.), also include:
    - expected_output: Description of what a successful result looks like — output format,
      shape, key metrics, or acceptance criteria. Synthesize from the answer if sources
      don't explicitly provide this.
    - example: A minimal worked example (sample input → processing steps → expected output).
      Construct synthetically based on the answer if sources lack one. Write
      '[insufficient data — needs supplementation]' only if impossible to construct.

    Visual aids placement (optional after_section field):
    - "answer" — insert after the main answer paragraph (default for architecture/pipeline diagrams)
    - "supporting_claims" — insert after claims (default for evidence figures/charts)
    - "inferences", "uncertainty", "missing_evidence", "suggested_next_steps" — after respective sections
    - Omit after_section to place at the end of the card (backward compatible)

    Args:
        query: The original research question.
        answer_json: JSON string with the structured answer.
        domain: Optional domain/folder name for the card (e.g. "quant-backtest").
            When provided, the card is placed directly under knowledge/<domain>/
            and all auto-routing (AI, folder matching, heuristic) is skipped.
        language: Language for the card content — "zh" (Chinese, default) or "en" (English).
            When "zh", the answer, claims, inferences, and all other text fields MUST be in Chinese.
        card_type: Optional explicit card type — "engineering" (a step-by-step implementation
            playbook with prerequisites/implementation_steps/verification/pitfalls/rollback),
            "method", or "knowledge". If omitted, inferred from query + content. Use
            "engineering" for how-to / landing / deployment knowledge so it renders as
            actionable steps instead of an abstract research summary.
    """
    # Validate query — reject path traversal sequences only
    if not query or not query.strip():
        return json.dumps({"error": "query must not be empty"})

    try:
        answer_data = json.loads(answer_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {e}"})

    # Explicit card_type override (engineering/method/knowledge); otherwise inferred.
    if card_type and card_type.strip().lower() in ("engineering", "method", "knowledge"):
        answer_data["card_type"] = card_type.strip().lower()

    # Validate against schema
    warnings = validate_answer_schema(answer_data)

    # Quality gate
    quality = quality_score_answer_data(answer_data, source="save_research")
    if not quality["passed"]:
        return json.dumps(
            {
                "error": (
                    f"Quality gate failed (score: {quality['score']:.2f}, "
                    f"minimum: {QUALITY_THRESHOLD_SAVE_RESEARCH:.2f}). "
                    "Your answer is too thin to create a useful knowledge card."
                ),
                "quality_score": quality["score"],
                "quality_threshold": QUALITY_THRESHOLD_SAVE_RESEARCH,
                "violations": quality["violations"],
                "guidance": (
                    "Provide a detailed answer (200+ characters) with at least 1 supporting claim "
                    "referencing evidence. Include inferences, uncertainty, and suggested_next_steps "
                    "for higher quality."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    provenance_errors = _validate_research_provenance(answer_data)
    if provenance_errors:
        return json.dumps(
            {
                "error": "Provenance gate failed. save_research requires traceable sources and evidence-backed claims.",
                "violations": provenance_errors,
                "guidance": (
                    "Add a non-empty sources array and cite those sources from each supporting_claim.evidence_ids. "
                    "If this is an unsourced conversation capture, use capture_answer instead."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    # Build knowledge card
    try:
        # Pass language to answer_data so build_knowledge_card can write it to frontmatter
        answer_data["language"] = language
        sanitized_domain = domain.strip() if domain and domain.strip() else ""
        if sanitized_domain:
            knowledge_dir = get_knowledge_dir()
            target = (knowledge_dir / sanitized_domain).resolve()
            if not target.is_relative_to(knowledge_dir.resolve()):
                return json.dumps({"error": "domain must not contain path separators or parent references"})
        domain_kw = {"domain_override": sanitized_domain} if sanitized_domain else {}
        card_path = build_knowledge_card(
            query,
            answer_data,
            None,
            get_knowledge_dir(),
            index_path=get_index_path(),
            confidence=confidence_from_quality(quality),
            **domain_kw,
        )
    except Exception as e:
        return json.dumps({"error": f"Failed to write card: {e}"})

    index_path = get_index_path()
    _async_reindex(index_path)

    # G2: best-effort snapshot cited sources so dead links stay traceable even
    # when the caller didn't explicitly fetch_url each one. Background daemon
    # thread — never delays the tool response (network fetches can be slow).
    try:
        _src_list = answer_data.get("sources") or []
        if isinstance(_src_list, list) and _src_list:
            threading.Thread(
                target=_snapshot_sources,
                args=([str(s) for s in _src_list if s],),
                daemon=True,
            ).start()
    except Exception:
        pass

    # F2: self-check the card we just wrote (frontmatter schema + body density).
    card_quality: dict[str, Any] = {"errors": [], "warnings": []}
    try:
        from scholar_agent.engine.knowledge_lifecycle import validate_card_quality

        card_quality = validate_card_quality(str(card_path))
    except Exception:
        logger.warning("card quality check failed", exc_info=True)

    return json.dumps(
        {
            "status": "ok",
            "card_path": str(card_path),
            "reindexed": False,
            "index_pending_refresh": True,
            "schema_warnings": warnings,
            "card_quality": card_quality,
        },
        ensure_ascii=False,
        indent=2,
    )


def _persist_snapshot(url: str, content_md: str, title: str = "") -> tuple[str, str]:
    """G2: archive fetched content to knowledge/_snapshots/<sha1(url)>.md.

    Returns (snapshot_path, captured_at) — empty strings on failure. Shared by
    fetch_url and save_research (auto-snapshot of sources) so dead links stay
    traceable whether or not the caller used fetch_url explicitly.
    """
    from scholar_agent.engine.knowledge_lifecycle import persist_snapshot

    return persist_snapshot(get_knowledge_dir(), url, content_md, title)


def _snapshot_sources(urls: list[str]) -> None:
    """G2 background helper: best-effort fetch + snapshot each source URL.

    Used by save_research to archive cited sources even when the caller didn't
    explicitly fetch_url each one. Runs in a daemon thread so it never delays
    the tool response.
    """
    try:
        from scholar_agent.engine.research_harness import fetch_content

        for url in urls:
            url = (url or "").strip()
            if not url or not url.startswith(("http://", "https://")):
                continue
            result = fetch_content(url)
            content_md = result.get("content_md", "") or ""
            if content_md:
                _persist_snapshot(url, content_md, result.get("title", "") or "")
    except Exception:
        logger.warning("background source snapshot failed", exc_info=True)


def _validate_research_provenance(answer_data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    sources = answer_data.get("sources") or answer_data.get("source_refs") or []
    if not isinstance(sources, list) or not [str(source).strip() for source in sources if str(source).strip()]:
        errors.append("sources must contain at least one source reference")

    claims = answer_data.get("supporting_claims", [])
    if isinstance(claims, list):
        for index, claim in enumerate(claims):
            if not isinstance(claim, dict):
                continue
            evidence_ids = claim.get("evidence_ids", [])
            if not isinstance(evidence_ids, list) or not [str(eid).strip() for eid in evidence_ids if str(eid).strip()]:
                errors.append(f"supporting_claims[{index}].evidence_ids must contain at least one evidence id")
    return errors


def _fetch_url_impl(url: str, max_chars: int = 6000) -> dict:
    """G5: fetch a web URL → main content as markdown + persist a local snapshot (G2).

    Core logic (kept separate from the @tool wrapper so it is unit-testable).
    Reuses research_harness.fetch_content (HTML→text extraction + cache + blocklist).
    The snapshot under knowledge/_snapshots/ archives the full text with a
    captured_at date so dead links (job postings, pages that get taken down)
    stay traceable.
    """
    if not url or not url.strip():
        return {"error": "url must not be empty"}
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"error": "url must start with http:// or https://"}

    from scholar_agent.engine.research_harness import fetch_content

    result = fetch_content(url)
    content_md = result.get("content_md", "") or ""
    title = result.get("title", "") or ""

    snapshot_path, captured_at = _persist_snapshot(url, content_md, title)

    return {
        "url": url,
        "title": title,
        "content_md": content_md[:max_chars],
        "retrieval_status": result.get("retrieval_status", ""),
        "failure_reason": result.get("failure_reason", ""),
        "snapshot_path": snapshot_path,
        "captured_at": captured_at,
        "content_chars": len(content_md),
        "snapshot_truncated": len(content_md) > max_chars,
    }


@tool
async def fetch_url(url: str, max_chars: int = 6000, ctx: Context | None = None) -> str:
    """Fetch a web URL and return its main content as markdown — first-hand retrieval (G5).

    抓取网页正文(已做 HTML→正文提取)返回给调用方,用于在 save_research 之前把
    knowledge card 建立在**一手出处**之上,而非凭记忆或摘要。同时把完整正文存本地
    快照 `knowledge/_snapshots/<sha1(url)>.md`(含 captured_at),防止原链接失效
    (招聘 JD、网页易下架)后无法回溯(G2)。

    典型用法:fetch_url 抓一手 → 基于正文写带具体数字/机制的深度 answer → save_research 存卡。

    Args:
        url: 要抓取的 http(s) URL。
        max_chars: 返回 content_md 的最大字符数(默认 6000;完整正文在快照里)。
    """

    def _impl() -> str:
        return json.dumps(_fetch_url_impl(url, max_chars), ensure_ascii=False, indent=2)

    return await _run_blocking(_impl, tool_name="fetch_url", ctx=ctx)


@tool
def list_knowledge(topic: str | None = None) -> str:
    """List all knowledge cards in the local knowledge base.

    Returns card metadata (id, title, topic, type) for browsing and discovery.

    Args:
        topic: Optional topic filter (e.g. 'qpe', 'markov_chain'). Returns all if omitted.
    """
    if topic is not None and any(c in topic for c in ("/", "\\", "\0")):
        return json.dumps(
            {"error": "topic must not contain path separators or traversal sequences", "cards": [], "total": 0}
        )
    index_path, refreshed, refresh_error = _ensure_index_ready()
    if not index_path.exists():
        return json.dumps(
            {"cards": [], "total": 0, "error": refresh_error or "Index not found. Run local_index.py first."}
        )

    try:
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return json.dumps({"cards": [], "total": 0, "error": "Failed to read index."})

    cards = []
    for doc in index_data.get("documents", []):
        if topic:
            doc_topic = doc.get("topic", "")
            if doc_topic != topic and not doc_topic.endswith("/" + topic) and not doc_topic.startswith(topic + "/"):
                continue
        cards.append(
            {
                "id": doc.get("doc_id", ""),
                "title": doc.get("title", ""),
                "domain": doc.get("domain", ""),
                "topic": doc.get("topic", ""),
                "type": doc.get("type", ""),
                "path": doc.get("path", ""),
                "links": doc.get("links", []),
                "backlinks": doc.get("backlinks", []),
            }
        )

    payload = {"cards": cards, "total": len(cards)}
    if refresh_error:
        payload["warning"] = refresh_error
    if refreshed:
        payload["index_refreshed"] = True
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def capture_answer(query: str, answer: str, tags: str = "", language: str = "zh") -> str:
    """Capture a useful Q&A answer as a draft knowledge card.

    Use this ONLY when a conversation produces a SUBSTANTIVE answer that is worth
    persisting — meaning it provides genuine technical insight, a non-obvious
    explanation, or actionable knowledge that cannot be found in standard references.

    DO NOT use this tool for:
    - Single-sentence answers or brief definitions
    - Answers that could be found in any standard reference (Wikipedia, docs)
    - Trivial facts, simple yes/no responses, or content shorter than 150 characters
    - Paper or topic-level knowledge that requires source verification

    If you have structured evidence and claims, prefer save_research instead —
    it produces higher-quality cards with proper source attribution.

    The answer text MUST be at least 150 characters. Write a thorough explanation
    covering the key insight, context, and practical implications.

    Args:
        query: The question that was answered.
        answer: The answer text (plain text or markdown). Minimum 150 characters.
        tags: Comma-separated tags for the card (optional).
        language: Language for the card content — "zh" (Chinese, default) or "en" (English).
    """
    if not query or not query.strip():
        return json.dumps({"error": "query must not be empty"})
    if not answer or not answer.strip():
        return json.dumps({"error": "answer must not be empty"})

    # Build a minimal structured answer for the card builder
    answer_data = {
        "answer": answer,
        "supporting_claims": [],
        "inferences": [],
        "uncertainty": ["Captured from conversation — not yet verified against sources"],
        "missing_evidence": ["Source references needed"],
        "suggested_next_steps": ["Verify against authoritative sources", "Add supporting evidence"],
        "language": language,
    }

    if tags and tags.strip():
        answer_data["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

    # Quality gate
    quality = quality_score_answer_data(answer_data, source="capture_answer")
    if not quality["passed"]:
        return json.dumps(
            {
                "error": (
                    f"Quality gate failed (score: {quality['score']:.2f}, "
                    f"minimum: {QUALITY_THRESHOLD_CAPTURE_ANSWER:.2f}). "
                    "Your answer is too brief to create a useful knowledge card."
                ),
                "quality_score": quality["score"],
                "quality_threshold": QUALITY_THRESHOLD_CAPTURE_ANSWER,
                "violations": quality["violations"],
                "guidance": (
                    "capture_answer is for substantive Q&A captures. Write at least 150 characters "
                    "explaining the answer with context and practical implications. "
                    "For a one-liner, this information is better left uncaptured."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    # Build the card
    try:
        card_path = build_knowledge_card(
            query,
            answer_data,
            None,
            get_knowledge_dir(),
            index_path=get_index_path(),
            confidence=confidence_from_quality(quality),
        )
    except Exception as e:
        return json.dumps({"error": f"Failed to write card: {e}"})

    index_path = get_index_path()
    _async_reindex(index_path)

    return json.dumps(
        {
            "status": "ok",
            "card_path": str(card_path),
            "reindexed": False,
            "index_pending_refresh": True,
            "note": "Card created as draft. Verify and promote when confidence is confirmed.",
        },
        ensure_ascii=False,
        indent=2,
    )


@tool
def review_card(card_id: str, target_status: str, reason: str, superseded_by: str = "") -> str:
    """Adjust a knowledge card's trust state per the user's EXPLICIT instruction.

    This is the authority-management interface. You (the AI) MUST only call it
    when the user explicitly tells you to change a card's trust — e.g. "this is
    wrong", "this is outdated", "this turned out solid", "this is superseded by
    <X>". Never decide trust on your own and never call this speculatively.

    Args:
        card_id: The card's frontmatter `id` (the `doc_id` shown in
            query_knowledge results).
        target_status: One of `reviewed` | `trusted` | `stale` | `deprecated`.
            - `stale`: "wrong / outdated but may be fixed" — the DEFAULT for
              "错了/过时": reversible (a later update lifts it back to reviewed).
            - `deprecated`: "retire permanently" — TERMINAL and IRREVERSIBLE.
              Use only when the user clearly means permanent retirement.
            - `reviewed` / `trusted`: lift a card's trust.
        reason: REQUIRED. Restate why the user wants this (their words /
            context). Written to the card and the changelog for auditability.
        superseded_by: Optional card_id of the replacement (use with
            stale/deprecated when the user points to a newer card).

    The transition is validated against the lifecycle state machine; an illegal
    one (e.g. promoting from deprecated, which is terminal) returns an error
    instead of forcing the file.
    """
    from scholar_agent.engine.close_knowledge_loop import append_changelog
    from scholar_agent.engine.common import now_iso
    from scholar_agent.engine.knowledge_lifecycle import (
        LifecycleState,
        parse_frontmatter,
        set_frontmatter_key,
        transition_card,
    )
    from scholar_agent.engine.local_index import iter_cards
    from scholar_agent.engine.scholar_config import get_knowledge_dir

    valid = {"reviewed", "trusted", "stale", "deprecated"}
    if target_status not in valid:
        return json.dumps({"error": f"target_status must be one of {sorted(valid)}"})
    if not reason or not reason.strip():
        return json.dumps({"error": "reason is required — restate why the user wants this change"})

    root = get_knowledge_dir()
    card_path = None
    try:
        for candidate in iter_cards(root):
            try:
                # frontmatter lives at the file head — read 4KB, not the whole note
                with candidate.open("rb") as fh:
                    meta, _ = parse_frontmatter(fh.read(4096).decode("utf-8", errors="replace"))
            except OSError:
                continue
            if str(meta.get("id", candidate.stem)) == card_id:
                card_path = candidate
                break
    except Exception:
        logger.debug("card lookup failed for %s", card_id, exc_info=True)
    if card_path is None:
        return json.dumps({"error": f"no card with id '{card_id}' found under {root}"})

    meta, _ = parse_frontmatter(card_path.read_text(encoding="utf-8", errors="replace"))
    current = str(meta.get("review_status") or "draft")

    _new_meta, err = transition_card(dict(meta), LifecycleState(target_status))
    if err:
        return json.dumps({"error": err, "current_status": current, "target_status": target_status})

    reason_text = reason.strip()
    set_frontmatter_key(card_path, "review_status", target_status)
    set_frontmatter_key(card_path, "status_reason", json.dumps(reason_text, ensure_ascii=False))
    set_frontmatter_key(card_path, "status_changed_at", now_iso())
    if superseded_by and superseded_by.strip():
        set_frontmatter_key(card_path, "superseded_by", superseded_by.strip())

    try:
        append_changelog(root, "transitioned", card_id, f"{current}->{target_status}: {reason_text}")
    except Exception:
        logger.warning("changelog append failed for %s", card_id, exc_info=True)

    _async_reindex(get_index_path())

    return json.dumps(
        {"status": "ok", "card_id": card_id, "from": current, "to": target_status, "reason": reason_text},
        ensure_ascii=False,
    )


@tool
async def ingest_source(
    source: str, title: str = "", tags: str = "", language: str = "zh", ctx: Context | None = None
) -> str:
    """Ingest a URL or raw text into the knowledge base as a draft card.

    For URLs: fetches the page content, extracts text, and saves as a card.
    For text: saves the provided text directly as a card.

    Use this when you want to add external documents, articles, or notes
    to the knowledge base without requiring structured JSON.

    Args:
        source: A URL (starting with http:// or https://) or raw text/markdown.
            When providing raw text and language="zh", the text MUST be in Chinese (中文).
        title: Optional title for the card. Auto-detected from URL pages.
        tags: Comma-separated tags for the card (optional).
        language: Language for the card content — "zh" (Chinese, default) or "en" (English).
            When "zh" and providing raw text, ensure the content is in Chinese.
            For URL sources, the content language is determined by the original page.
    """

    def _impl() -> str:
        if not source or not source.strip():
            return json.dumps({"error": "source must not be empty"})

        source_value = source.strip()
        is_url = source_value.startswith(("http://", "https://"))
        snapshot_path = ""
        captured_at = ""

        if is_url:
            from scholar_agent.engine.research_harness import fetch_content

            result = fetch_content(source_value)
            if result["retrieval_status"] == "failed":
                return json.dumps({"error": f"Failed to fetch URL: {result.get('failure_reason', 'unknown')}"})
            content = result["content_md"]
            auto_title = result.get("title", "") or title or source_value[:80]
            snapshot_path, captured_at = _persist_snapshot(source_value, content, auto_title)
        else:
            content = source_value
            auto_title = title or content.split("\n")[0][:80]

        if not auto_title or not auto_title.strip():
            auto_title = f"untitled-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        if not content:
            return json.dumps({"error": "No content extracted from source"})

        answer_data = {
            "answer": content,
            "supporting_claims": [],
            "inferences": [],
            "uncertainty": ["Ingested source — not yet verified or synthesized"],
            "missing_evidence": ["Cross-reference with other sources needed"],
            "suggested_next_steps": ["Verify key claims", "Link to related cards"],
            "language": language,
        }

        if tags and tags.strip():
            answer_data["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        if is_url:
            answer_data["tags"] = [*answer_data.get("tags", []), "ingested-url"]
            answer_data["sources"] = [source_value]

        try:
            card_path = build_knowledge_card(
                auto_title, answer_data, None, get_knowledge_dir(), index_path=get_index_path()
            )
        except Exception as e:
            return json.dumps({"error": f"Failed to write card: {e}"})

        index_path = get_index_path()
        _async_reindex(index_path)

        return json.dumps(
            {
                "status": "ok",
                "card_path": str(card_path),
                "reindexed": False,
                "index_pending_refresh": True,
                "source_type": "url" if is_url else "text",
                "title": auto_title,
                "snapshot_path": snapshot_path,
                "captured_at": captured_at,
            },
            ensure_ascii=False,
            indent=2,
        )

    return await _run_blocking(_impl, tool_name="ingest_source", ctx=ctx)


def _knowledge_cards_for_report() -> list[dict[str, Any]]:
    from scholar_agent.engine.knowledge_lifecycle import scan_knowledge_dir

    root = get_knowledge_dir()
    if not root.exists():
        return []
    return scan_knowledge_dir(root)


def _scan_domain_stale_cards(knowledge_root: Path, *, now: datetime | None = None) -> list[dict[str, Any]]:
    from scholar_agent.engine.knowledge_lifecycle import scan_stale_cards

    return scan_stale_cards(knowledge_root, now=now)


def _lint_knowledge_payload(stale_days: int = 90) -> dict[str, Any]:
    from scholar_agent.engine.local_index import lifecycle_state

    cards = _knowledge_cards_for_report()
    card_ids = {str(card.get("id", "")) for card in cards if card.get("id")}
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)

    outgoing: dict[str, set[str]] = {}
    incoming: dict[str, set[str]] = {}
    broken_links: list[dict[str, Any]] = []
    stale_cards: list[dict[str, Any]] = []

    for card in cards:
        cid = str(card.get("id", ""))
        path = str(card.get("_path", ""))
        body = ""
        if path:
            try:
                raw = Path(path).read_text(encoding="utf-8", errors="replace")
                _meta, body = parse_frontmatter(raw) if raw.startswith("---\n") else ({}, raw)
            except OSError:
                body = ""

        targets = set(re.findall(r"\[\[([^\]]+)\]\]", body))
        outgoing[cid] = targets
        for target in targets:
            resolved = resolve_link_target(target, card_ids)
            if resolved is None:
                broken_links.append({"source_id": cid, "target": target, "path": path})
            else:
                incoming.setdefault(resolved, set()).add(cid)

        updated_at = str(card.get("updated_at", "") or "")
        if not updated_at:
            if card.get("confidence") != "draft" and card.get("review_status") != "draft":
                stale_cards.append({"id": cid, "title": card.get("title", ""), "path": path, "updated_at": ""})
            continue
        try:
            updated_dt = datetime.strptime(updated_at[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if updated_dt < stale_cutoff:
            stale_cards.append({"id": cid, "title": card.get("title", ""), "path": path, "updated_at": updated_at})

    orphans = [
        {
            "id": card.get("id", ""),
            "title": card.get("title", ""),
            "path": card.get("_path", ""),
        }
        for card in cards
        if card.get("id") and not outgoing.get(str(card.get("id", ""))) and str(card.get("id", "")) not in incoming
    ]

    title_overlaps: list[dict[str, Any]] = []
    titled = [
        (str(card.get("id", "")), set(str(card.get("title", "")).lower().split()))
        for card in cards
        if card.get("title")
    ]
    for index, (id_a, left) in enumerate(titled):
        for id_b, right in titled[index + 1 :]:
            if not left or not right:
                continue
            score = len(left & right) / len(left | right)
            if score > 0.6:
                title_overlaps.append({"id_a": id_a, "id_b": id_b, "jaccard": round(score, 3)})

    issue_count = len(orphans) + len(broken_links) + len(stale_cards) + len(title_overlaps)
    return {
        "status": "ok" if issue_count == 0 else "issues",
        "knowledge_dir": str(get_knowledge_dir()),
        "total": len(cards),
        # Informational, like query_knowledge's knowledge_status: cards still
        # awaiting review. Not an issue — a draft is unverified, not defective.
        "draft_backlog": sum(1 for card in cards if lifecycle_state(card) == "draft"),
        "issue_count": issue_count,
        "issues": {
            "orphans": orphans,
            "broken_links": broken_links,
            "stale": stale_cards,
            "title_overlaps": title_overlaps,
        },
    }


@tool
def validate_knowledge(verbose: bool = False) -> str:
    """Validate local knowledge cards without modifying files.

    Runs card frontmatter validation plus body-density/source-freshness checks.
    Use this before relying on a knowledge base or after bulk imports.

    Args:
        verbose: When true, include warning-only cards in the per-card report.
    """
    from scholar_agent.engine.knowledge_lifecycle import validate_card_quality

    cards = _knowledge_cards_for_report()
    total_errors = 0
    total_warnings = 0
    reports: list[dict[str, Any]] = []
    for card in cards:
        path = str(card.get("_path", ""))
        quality = validate_card_quality(path) if path else {"errors": [], "warnings": []}
        errors = quality.get("errors", [])
        warnings = quality.get("warnings", [])
        total_errors += len(errors)
        total_warnings += len(warnings)
        if errors or (verbose and warnings):
            reports.append(
                {
                    "id": card.get("id", ""),
                    "title": card.get("title", ""),
                    "path": path,
                    "errors": errors,
                    "warnings": warnings,
                }
            )

    return json.dumps(
        {
            "status": "ok" if total_errors == 0 else "error",
            "knowledge_dir": str(get_knowledge_dir()),
            "total": len(cards),
            "errors": total_errors,
            "warnings": total_warnings,
            "cards": reports,
        },
        ensure_ascii=False,
        indent=2,
    )


@tool
def lint_knowledge(stale_days: int = 90) -> str:
    """Run read-only content health checks over the local knowledge base.

    Reports orphan cards, broken wiki-links, cards not updated within
    stale_days, and highly overlapping titles, plus `draft_backlog` (cards
    still awaiting review — the same count query_knowledge returns in
    `knowledge_status`). This tool never edits files.

    Args:
        stale_days: Age threshold in days for the updated_at lint check.
    """
    if not isinstance(stale_days, int) or stale_days < 1:
        return json.dumps({"error": "stale_days must be a positive integer"})
    return json.dumps(_lint_knowledge_payload(stale_days=stale_days), ensure_ascii=False, indent=2)


@tool
def scan_stale_knowledge() -> str:
    """Report knowledge cards whose source freshness exceeds domain thresholds.

    Unlike lint_knowledge's updated_at check, this uses source_date/captured
    year with the domain-specific freshness policy used by card validation.
    This tool is read-only.
    """
    root = get_knowledge_dir()
    stale = _scan_domain_stale_cards(root)
    return json.dumps(
        {
            "status": "ok",
            "knowledge_dir": str(root),
            "stale_count": len(stale),
            "stale": stale,
        },
        ensure_ascii=False,
        indent=2,
    )


@tool
def scan_dead_links(concurrency: int = 8, timeout: float = 10.0, offline: bool = False) -> str:
    """Diagnose dead source URLs (404/410/connection failure) across knowledge cards.

    Probes each unique source_refs URL once (HEAD first, GET fallback) and fans
    the result out to every card that cites it. Paywalled domains are reported
    as ``blocked``; offline=True marks every URL ``skipped``. Read-only — never
    edits cards or snapshots.

    Args:
        concurrency: Maximum concurrent URL probes.
        timeout: Per-request timeout in seconds.
        offline: Skip all network probes.
    """
    if not isinstance(concurrency, int) or concurrency < 1:
        return json.dumps({"error": "concurrency must be a positive integer"})
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        return json.dumps({"error": "timeout must be positive"})
    root = get_knowledge_dir()
    from scholar_agent.engine.dead_link_check import check_dead_links

    report = check_dead_links(root, concurrency=concurrency, timeout=timeout, offline=offline)
    return json.dumps(report, ensure_ascii=False, indent=2)


@tool
def build_graph() -> str:
    """Build an interactive knowledge graph visualization.

    Generates a self-contained HTML file showing all knowledge cards as nodes
    and their wiki-links as edges. Open the output file in a browser to
    explore the knowledge graph visually. Compatible with Obsidian vaults.

    Returns the path to the generated graph.html file.
    """
    from scholar_agent.engine.build_graph import build_graph_data, generate_html

    index_path, _refreshed, refresh_error = _ensure_index_ready()
    if not index_path.exists():
        return json.dumps({"error": refresh_error or "Index not found. Run local_index.py first."})

    graph_data = build_graph_data(index_path)
    output_path = get_knowledge_dir().parent / "graph.html"
    generate_html(graph_data, output_path)

    return json.dumps(
        {
            "status": "ok",
            "path": str(output_path),
            "nodes": len(graph_data["nodes"]),
            "edges": len(graph_data["edges"]),
        },
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# Academic tools (controlled by SCHOLAR_ACADEMIC env var)
# ---------------------------------------------------------------------------

import re as _re


def _parse_arxiv_id(paper_id: str) -> str | None:
    """Extract arXiv ID from various formats. Returns None if not an arXiv ID."""
    text = paper_id.strip()
    match = _re.search(r"(\d{4}\.\d+)", text)
    if match:
        return match.group(1)
    match = _re.search(r"([a-z-]+\.\w+/\d+)", text)
    if match:
        return match.group(1)
    return None


# Slugification consolidated into common.sanitize_title
_sanitize_title = sanitize_title


def _find_local_pdf(arxiv_id: str, title: str = "") -> str | None:
    """Search paper-notes/ for an existing local PDF by title or arXiv ID."""
    paper_notes_dir = get_paper_notes_dir()
    if not paper_notes_dir.exists():
        return None
    # Single directory traversal; the three matching strategies then run
    # against the candidate list in the original priority order.
    candidates = list(paper_notes_dir.rglob("*.pdf"))
    # Search by sanitized title first
    if title:
        safe = _sanitize_title(title)
        # Exact match: <safe>/<safe>.pdf at any depth
        for match in candidates:
            if match.parent.name == safe and match.name == f"{safe}.pdf":
                return str(match)
        # Broader search: any PDF under a directory matching the title
        title_words = set(_re.findall(r"[a-z0-9]+", title.lower()[:60]))
        for match in candidates:
            # Match if parent dir or filename contains the title (fuzzy)
            parent_words = set(_re.findall(r"[a-z0-9]+", match.parent.name.lower()))
            if title_words and title_words.issubset(parent_words):
                return str(match)
            stem_words = set(_re.findall(r"[a-z0-9]+", match.stem.lower()))
            if title_words and len(title_words & stem_words) >= min(len(title_words), 3):
                return str(match)
    # Fallback: search by arXiv ID
    if arxiv_id:
        for match in candidates:
            if match.name == f"{arxiv_id}.pdf":
                return str(match)
    return None


def _resolve_analysis_pdf(paper: dict, pdf_path: str) -> str | None:
    """Resolve a PDF for analysis: explicit path > local detection > arXiv auto-download.

    Returns the resolved PDF path, or None if no PDF can be found/downloaded.
    Raises ValueError if pdf_path is outside the scholar knowledge directory tree.
    """
    arxiv_id = paper.get("arxiv_id", "") or ""
    paper_title = paper.get("title", "")

    if pdf_path and pdf_path.strip():
        validated = _validate_path_within(pdf_path.strip(), get_knowledge_dir().parent)
        if validated is None:
            raise ValueError("pdf_path must be within the scholar knowledge directory tree")
        return str(validated)

    detected = _find_local_pdf(arxiv_id, title=paper_title)

    # Auto-download from arXiv when no local PDF exists
    if not detected and arxiv_id:
        try:
            from scholar_agent.engine.academic.image_extractor import download_arxiv_pdf

            dl_dir = get_paper_notes_dir() / arxiv_id
            dl_dir.mkdir(parents=True, exist_ok=True)
            downloaded = download_arxiv_pdf(arxiv_id, str(dl_dir))
            if downloaded and os.path.isfile(downloaded):
                logger.info("Auto-downloaded PDF for %s -> %s", arxiv_id, downloaded)
                return downloaded
        except Exception as exc:
            logger.warning("Auto-download failed for %s: %s", arxiv_id, exc)

    return detected


if SCHOLAR_ACADEMIC:
    from scholar_agent.adapters.mcp_academic import register_academic_tools

    register_academic_tools(
        tool=tool,
        context=Context,
        run_blocking=_run_blocking,
        validate_path_within=_validate_path_within,
        resolve_analysis_pdf=_resolve_analysis_pdf,
        find_local_pdf=_find_local_pdf,
        parse_arxiv_id=_parse_arxiv_id,
        sanitize_title=_sanitize_title,
        async_reindex=_async_reindex,
        build_knowledge_card=build_knowledge_card,
        get_knowledge_dir=get_knowledge_dir,
        get_index_path=get_index_path,
        get_paper_notes_dir=get_paper_notes_dir,
        get_daily_notes_dir=get_daily_notes_dir,
        get_research_interests=get_research_interests,
        load_config=load_config,
    )
    logger.info("Academic tools enabled (SCHOLAR_ACADEMIC=%s)", SCHOLAR_ACADEMIC)


@tool
async def import_paperpulse_note(paper_id: str, api_token: str | None = None, ctx: Context | None = None) -> str:
    """Import a distilled paper note from PaperPulse SaaS directly into the local Scholar Agent knowledge base.

    Args:
        paper_id: The UUID of the paper to import.
        api_token: Optional API token. If not provided, reads 'paperpulse_token' from config.json.
    """

    def _impl() -> str:
        from scholar_agent.engine.import_service import import_from_url

        config = load_config()
        token = api_token or config.get("paperpulse_token", "")
        base_url = config.get("paperpulse_url", "https://mindpulse.top").rstrip("/")

        msg, saved = import_from_url(paper_id, token, base_url)

        if saved is not None:
            index_path = _configured_index_path(config)
            _async_reindex(index_path)

        return msg

    return await _run_blocking(_impl, tool_name="import_paperpulse_note", ctx=ctx)


def main() -> int:
    """Entry point for the MCP server."""
    if mcp is None:
        print("Error: fastmcp not installed. Run: pip install fastmcp", file=sys.stderr)
        return 1

    # Narrow the tool surface before serving. An unknown SCHOLAR_TOOLSET group is
    # a configuration error: fail fast with the legal values rather than serve a
    # silently reduced (or full) tool set.
    raw_toolset = os.environ.get("SCHOLAR_TOOLSET")
    try:
        registered = asyncio.run(_registered_tool_names(mcp))
        kept = apply_toolset(mcp, raw_toolset, registered)
    except ToolsetError as exc:
        print(f"Error: invalid SCHOLAR_TOOLSET={raw_toolset!r}: {exc}", file=sys.stderr)
        return 2
    if len(kept) < len(registered):
        logger.info("SCHOLAR_TOOLSET=%s: exposing %d of %d tools", raw_toolset, len(kept), len(registered))

    # Flush debounced metrics/usage snapshots on clean shutdown
    atexit.register(_flush_query_state)

    # Start the background local sync server
    t = threading.Thread(target=start_local_server, daemon=True)
    t.start()

    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
