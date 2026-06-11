"""Scholar Agent — MCP server exposing knowledge tools to Claude Code and Copilot.

Tools:
  - query_knowledge: Search the local knowledge base
  - save_research: Persist structured research results as a knowledge card
  - list_knowledge: Browse all knowledge cards, optionally filtered by topic
  - capture_answer: Capture a Q&A answer as a draft knowledge card
  - ingest_source: Ingest a URL or raw text into the knowledge base
  - build_graph: Build an interactive knowledge graph visualization

Academic tools (set SCHOLAR_ACADEMIC=1 to enable):
  - search_papers: Search arXiv + Semantic Scholar with scoring
  - search_conf_papers: Search conference papers via DBLP + S2 enrichment
  - analyze_paper: Generate structured markdown notes for a paper
  - extract_paper_images: Extract figures from arXiv source/PDF
  - paper_to_card: Convert paper analysis into a knowledge card
  - daily_recommend: Full daily recommendation workflow
  - link_paper_keywords: Auto-link keywords as [[wikilinks]]

Usage:
  scholar-agent serve-mcp
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import ipaddress
import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from scholar_agent.engine.close_knowledge_loop import (
    QUALITY_THRESHOLD_CAPTURE_ANSWER,
    QUALITY_THRESHOLD_SAVE_RESEARCH,
    build_knowledge_card,
    quality_score_answer_data,
    validate_answer_schema,
)
from scholar_agent.engine.common import sanitize_title
from scholar_agent.engine.index_lifecycle import async_reindex as _async_reindex
from scholar_agent.engine.index_lifecycle import ensure_ready as _ensure_index_ready
from scholar_agent.engine.index_lifecycle import mark_stale as _mark_index_stale
from scholar_agent.engine.local_retrieve import retrieve
from scholar_agent.engine.scholar_config import (
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


def _optional_dep_warnings() -> list[str]:
    warnings: list[str] = []
    if importlib.util.find_spec("fitz") is None:
        warnings.append("PyMuPDF not installed — PDF image extraction will not work. Install with: pip install PyMuPDF")
    return warnings


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


def _configured_index_path(config: dict[str, Any]) -> Path:
    """Return configured index path, falling back when config is empty."""
    configured = str(config.get("index_path", "")).strip()
    return Path(configured) if configured else get_index_path()


@tool
def query_knowledge(query: str, limit: int = 5) -> str:
    """Search the local knowledge base for relevant information.

    Returns top-k knowledge cards matching the query, with scores and content.
    Use this to find existing knowledge before doing web research.

    Args:
        query: The search query in natural language.
        limit: Maximum number of results to return (default 5).
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

    result = retrieve(query, index_path, limit)
    if refresh_error:
        result["warning"] = refresh_error
    if refreshed:
        result["index_refreshed"] = True
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def save_research(query: str, answer_json: str, domain: str = "", language: str = "zh") -> str:
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
    """
    # Validate query — reject path traversal sequences only
    if not query or not query.strip():
        return json.dumps({"error": "query must not be empty"})

    try:
        answer_data = json.loads(answer_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {e}"})

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
            **domain_kw,
        )
    except Exception as e:
        return json.dumps({"error": f"Failed to write card: {type(e).__name__}"})

    index_path = get_index_path()
    _mark_index_stale(index_path)

    return json.dumps(
        {
            "status": "ok",
            "card_path": str(card_path),
            "reindexed": False,
            "index_pending_refresh": True,
            "schema_warnings": warnings,
        },
        ensure_ascii=False,
        indent=2,
    )


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
        card_path = build_knowledge_card(query, answer_data, None, get_knowledge_dir(), index_path=get_index_path())
    except Exception as e:
        return json.dumps({"error": f"Failed to write card: {type(e).__name__}"})

    index_path = get_index_path()
    _mark_index_stale(index_path)

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
def ingest_source(source: str, title: str = "", tags: str = "", language: str = "zh") -> str:
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
    if not source or not source.strip():
        return json.dumps({"error": "source must not be empty"})

    is_url = source.strip().startswith(("http://", "https://"))

    if is_url:
        from scholar_agent.engine.research_harness import fetch_content

        result = fetch_content(source.strip())
        if result["retrieval_status"] == "failed":
            return json.dumps({"error": f"Failed to fetch URL: {result.get('failure_reason', 'unknown')}"})
        content = result["content_md"]
        auto_title = result.get("title", "") or title or source.strip()[:80]
    else:
        content = source.strip()
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

    try:
        card_path = build_knowledge_card(
            auto_title, answer_data, None, get_knowledge_dir(), index_path=get_index_path()
        )
    except Exception as e:
        return json.dumps({"error": f"Failed to write card: {type(e).__name__}"})

    index_path = get_index_path()
    _mark_index_stale(index_path)

    return json.dumps(
        {
            "status": "ok",
            "card_path": str(card_path),
            "reindexed": False,
            "index_pending_refresh": True,
            "source_type": "url" if is_url else "text",
            "title": auto_title,
        },
        ensure_ascii=False,
        indent=2,
    )


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
    # Search by sanitized title first
    if title:
        safe = _sanitize_title(title)
        candidate = paper_notes_dir.rglob(f"{safe}/{safe}.pdf")
        for match in candidate:
            return str(match)
        # Broader search: any PDF under a directory matching the title
        for match in paper_notes_dir.rglob("*.pdf"):
            # Match if parent dir or filename contains the title (fuzzy)
            parent_name = match.parent.name.lower()
            stem_name = match.stem.lower()
            title_lower = title.lower()[:60]
            title_words = set(_re.findall(r"[a-z0-9]+", title_lower))
            parent_words = set(_re.findall(r"[a-z0-9]+", parent_name))
            if title_words and title_words.issubset(parent_words):
                return str(match)
            stem_words = set(_re.findall(r"[a-z0-9]+", stem_name))
            if title_words and len(title_words & stem_words) >= min(len(title_words), 3):
                return str(match)
    # Fallback: search by arXiv ID
    if arxiv_id:
        for match in paper_notes_dir.rglob(f"{arxiv_id}.pdf"):
            return str(match)
    return None


if SCHOLAR_ACADEMIC:

    @tool
    def search_papers(
        query: str = "",
        categories: str = "cs.AI,cs.LG,cs.CL,cs.CV",
        max_results: int = 200,
        top_n: int = 10,
        skip_hot: bool = False,
        config_path: str = "",
    ) -> str:
        """Search academic papers via arXiv + Semantic Scholar with scoring.

        Performs a combined search across arXiv (recent 30 days) and
        Semantic Scholar (high-influence papers from the past year), scores
        and deduplicates results using a four-dimensional scoring engine
        (relevance, recency, popularity, quality).

        Args:
            query: Natural language search query for Semantic Scholar hot-papers.
                If empty, uses default category-based keywords.
            categories: Comma-separated arXiv categories (default: cs.AI,cs.LG,cs.CL,cs.CV).
            max_results: Maximum arXiv results to fetch (default 200).
            top_n: Number of top-scored papers to return (default 10).
            skip_hot: If true, skip the Semantic Scholar hot-papers pass.
            config_path: Optional path to a YAML config file for research interests
                and scoring weights.
        """
        from scholar_agent.engine.academic.arxiv_search import _load_config, search_and_score

        # Clamp parameters to safe ranges
        max_results = max(1, min(max_results, 500))
        top_n = max(1, min(top_n, 50))

        cats = [c.strip() for c in categories.split(",") if c.strip()]
        if not cats:
            cats = ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]

        config = {}
        if config_path:
            validated_cp = _validate_path_within(config_path, get_knowledge_dir().parent)
            if validated_cp is None:
                return json.dumps({"error": "config_path must be within the scholar knowledge directory tree"})
            config = _load_config(str(validated_cp))
        if not config:
            # Try research interests from .scholar.json
            interests = get_research_interests()
            if interests.get("research_domains"):
                config = {
                    "research_domains": interests["research_domains"],
                    "excluded_keywords": interests.get("excluded_keywords", []),
                }
        if not config:
            # Reasonable default research domains
            config = {
                "research_domains": {
                    "deep-learning": {
                        "keywords": ["deep learning", "neural network", "representation learning"],
                        "arxiv_categories": ["cs.LG", "cs.AI"],
                        "priority": 3,
                    },
                },
                "excluded_keywords": ["tutorial", "bibliography"],
            }

        try:
            result = search_and_score(
                config=config,
                categories=cats,
                max_results=max_results,
                top_n=top_n,
                skip_hot=skip_hot,
                query=query,
            )
        except Exception as e:
            logger.exception("search_papers failed")
            return json.dumps({"error": str(e), "papers": [], "total_found": 0})

        # Trim large fields for readability
        for p in result.get("papers", []):
            summary = p.get("summary") or p.get("abstract") or ""
            if len(summary) > 500:
                p["_summary_truncated"] = True
                p["summary"] = summary[:500] + "…"

        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    @tool
    def search_conf_papers(
        venues: str = "CVPR,ICLR,NeurIPS,ICML",
        year: int = 0,
        keywords: str = "",
        excluded_keywords: str = "",
        top_n: int = 10,
        config_path: str = "",
    ) -> str:
        """Search conference papers via DBLP + Semantic Scholar enrichment.

        Searches DBLP for papers from specified conferences, enriches with
        Semantic Scholar data (abstracts, citations, arXiv IDs), scores
        and ranks them.

        Supported venues: CVPR, ICCV, ECCV, ICLR, AAAI, NeurIPS, ICML,
        MICCAI, ACL, EMNLP.

        Args:
            venues: Comma-separated venue names (default: CVPR,ICLR,NeurIPS,ICML).
            year: Conference year. 0 means current year.
            keywords: Comma-separated keywords to filter papers (optional).
            excluded_keywords: Comma-separated keywords to exclude (optional).
            top_n: Number of top-scored papers to return (default 10).
            config_path: Optional path to a YAML config file for scoring weights.
        """
        from scholar_agent.engine.academic.arxiv_search import _load_config
        from scholar_agent.engine.academic.conf_search import _CONF_CATALOG, search_and_score_conferences

        if year <= 0:
            year = datetime.now().year

        venue_list = [v.strip() for v in venues.split(",") if v.strip()]
        # Validate venue names (case-insensitive, then normalize to _CONF_CATALOG keys)
        _upper_map = {k.upper(): k for k in _CONF_CATALOG}
        normalized = []
        invalid = []
        for v in venue_list:
            mapped = _upper_map.get(v.upper())
            if mapped:
                normalized.append(mapped)
            else:
                invalid.append(v)
        venue_list = normalized
        if invalid:
            return json.dumps(
                {
                    "error": f"Unknown venues: {invalid}. Supported: {list(_CONF_CATALOG.keys())}",
                    "papers": [],
                    "total_found": 0,
                }
            )

        kws = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else None
        ex_kws = [k.strip() for k in excluded_keywords.split(",") if k.strip()] if excluded_keywords else None

        config = {}
        if config_path:
            validated_cp = _validate_path_within(config_path, get_knowledge_dir().parent)
            if validated_cp is None:
                return json.dumps({"error": "config_path must be within the scholar knowledge directory tree"})
            config = _load_config(str(validated_cp))
        if not config:
            interests = get_research_interests()
            if interests.get("research_domains"):
                config = {
                    "research_domains": interests["research_domains"],
                    "excluded_keywords": interests.get("excluded_keywords", []),
                }
        if not config:
            config = {"research_domains": {}, "excluded_keywords": []}

        if not isinstance(top_n, int) or top_n < 1:
            top_n = 10
        top_n = min(top_n, 50)

        try:
            result = search_and_score_conferences(
                config=config,
                year=year,
                venues=venue_list,
                keywords=kws,
                excluded_keywords=ex_kws,
                top_n=top_n,
            )
        except Exception as e:
            logger.exception("search_conf_papers failed")
            return json.dumps({"error": str(e), "papers": [], "total_found": 0, "year": year})

        # Trim abstracts for readability
        for p in result.get("papers", []):
            abstract = p.get("abstract") or ""
            if abstract and len(abstract) > 500:
                p["_abstract_truncated"] = True
                p["abstract"] = abstract[:500] + "…"

        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    @tool
    async def analyze_paper(
        paper_json: str,
        output_dir: str = "",
        language: str = "zh",
        all_papers_json: str = "",
        images_json: str = "",
        pdf_path: str = "",
        ctx: Context | None = None,
    ) -> str:
        """Analyze a paper and generate a structured deep-analysis markdown note.

        Creates an Obsidian-compatible markdown note with frontmatter metadata,
        20+ structured sections (core info, abstract translation, background,
        research questions, methods, experiments, deep analysis, comparisons,
        roadmap, future work, comprehensive evaluation), and optional wiki-links
        to related papers.

        The paper_json should contain at minimum: title, authors, arxiv_id.
        Optional fields: summary/abstract, scores, affiliations, conference,
        pdf_url, related_papers, matched_domain.

        Args:
            paper_json: JSON string with paper metadata.
            output_dir: Directory for output notes. Defaults to
                knowledge_dir/paper-notes under the configured scholar root.
            language: Note language — \"zh\" (Chinese, default) or \"en\" (English).
            all_papers_json: Optional JSON array of other paper dicts for
                finding related papers via wiki-links.
            images_json: Optional JSON array of image dicts (from extract_paper_images)
                with 'filename', 'section' keys. Section values: 'framework', 'results'.
            pdf_path: Optional local PDF file path. If omitted and paper_json contains
                an arxiv_id, auto-detects the local PDF in paper-notes/.
        """

        def _impl() -> str:
            from scholar_agent.engine.academic.note_linker import discover_related_notes
            from scholar_agent.engine.academic.paper_analyzer import generate_note

            try:
                paper = json.loads(paper_json)
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"Invalid paper_json: {e}"})

            if not paper.get("title"):
                return json.dumps({"error": "paper_json must contain at least a 'title' field"})

            # Auto-detect local PDF if pdf_path not provided
            detected_pdf = None
            if not pdf_path or not pdf_path.strip():
                arxiv_id = paper.get("arxiv_id", "")
                paper_title = paper.get("title", "")
                detected_pdf = _find_local_pdf(arxiv_id, title=paper_title)
            else:
                validated_pdf = _validate_path_within(pdf_path.strip(), get_knowledge_dir().parent)
                if validated_pdf is None:
                    return json.dumps({"error": "pdf_path must be within the scholar knowledge directory tree"})
                detected_pdf = str(validated_pdf)

            # Resolve output directory
            out_dir = output_dir
            if not out_dir or not out_dir.strip():
                out_dir = str(get_paper_notes_dir())
            out_path = _validate_path_within(out_dir, get_knowledge_dir().parent)
            if out_path is None:
                return json.dumps({"error": "output_dir must be within the scholar knowledge directory tree"})
            out_path.mkdir(parents=True, exist_ok=True)

            # Find related papers if provided
            other_papers = []
            if all_papers_json:
                try:
                    other_papers = json.loads(all_papers_json)
                    if not isinstance(other_papers, list):
                        other_papers = []
                except json.JSONDecodeError:
                    other_papers = []

            if other_papers and not paper.get("related_papers"):
                related = discover_related_notes(paper, other_papers, max_links=5)
                if related:
                    paper["related_papers"] = related

            # Validate language
            lang = language if language in ("zh", "en") else "zh"

            # Parse images — auto-extract when caller didn't provide them
            images = None
            auto_extracted_images: list[dict] = []
            if images_json and images_json.strip():
                try:
                    images = json.loads(images_json)
                    if not isinstance(images, list):
                        images = None
                except json.JSONDecodeError:
                    images = None
            elif detected_pdf or paper.get("arxiv_id"):
                # Auto-extract images when no explicit images_json provided
                try:
                    from scholar_agent.engine.academic.image_extractor import extract_paper_images as _extract_imgs

                    arxiv_id = paper.get("arxiv_id", "")
                    img_dir = str(out_path / "images")
                    auto_extracted_images = _extract_imgs(
                        arxiv_id,
                        img_dir,
                        pdf_path=detected_pdf,
                    )
                    if auto_extracted_images:
                        images = auto_extracted_images
                        logger.info(
                            "Auto-extracted %d images for %s",
                            len(auto_extracted_images),
                            paper.get("title", ""),
                        )
                except Exception as exc:
                    logger.warning("Auto image extraction failed: %s", exc)

            try:
                note_path = generate_note(
                    paper,
                    str(out_path),
                    language=lang,
                    images=images,
                    local_pdf_path=detected_pdf or "",
                )
            except Exception as e:
                logger.exception("analyze_paper failed")
                return json.dumps({"error": f"Failed to generate note: {type(e).__name__}"})

            # Extract full text from local PDF if available
            pdf_text = ""
            if detected_pdf and os.path.isfile(detected_pdf):
                try:
                    from scholar_agent.engine.academic.image_extractor import extract_pdf_text

                    pdf_text = extract_pdf_text(detected_pdf)
                except Exception:
                    pdf_text = ""

            # Auto-fill placeholders from PDF text via LLM
            fill_result = None
            if pdf_text:
                try:
                    from scholar_agent.engine.academic.paper_analyzer import fill_note_from_pdf

                    fill_result = fill_note_from_pdf(note_path, pdf_text)
                    logger.info("Auto-fill result: %s", fill_result)
                except Exception as exc:
                    logger.warning("Auto-fill failed: %s", exc)
                    fill_result = {"status": "error", "reason": str(exc)}

            # Quality check on the generated note
            quality_check: dict[str, Any] = {"has_issues": False, "issues": [], "placeholder_count": 0}
            try:
                from scholar_agent.engine.academic.paper_analyzer import check_note_quality

                quality_check = check_note_quality(note_path)
            except Exception:
                pass

            # Build instructions for the caller about remaining placeholders
            placeholder_count = quality_check.get("placeholder_count", 0)
            instructions = None
            if placeholder_count > 0 and pdf_text:
                instructions = (
                    "MUST fill all <!-- LLM: --> placeholders using pdf_text before showing to user. "
                    f"Note has {placeholder_count} placeholders. "
                    "Use Write tool to replace the skeleton note with fully filled content. "
                    "See SKILL.md '内容填充规则' section for detailed rules."
                )

            result_payload: dict[str, object] = {
                "status": "ok",
                "note_path": note_path,
                "title": paper.get("title", ""),
                "language": lang,
                "has_related_links": bool(paper.get("related_papers")),
                "pdf_path": detected_pdf,
                "has_full_text": bool(pdf_text),
                "pdf_text": pdf_text,
                "quality_check": quality_check,
                "instructions": instructions,
                "images": [
                    {"filename": img.get("filename", ""), "section": img.get("section", "")} for img in (images or [])
                ],
            }
            if fill_result:
                result_payload["fill_result"] = fill_result
            dep_warnings = _optional_dep_warnings()
            if dep_warnings:
                result_payload["warnings"] = dep_warnings
            return json.dumps(result_payload, ensure_ascii=False, indent=2)

        return await _run_blocking(_impl, tool_name="analyze_paper", ctx=ctx)

    @tool
    async def download_paper(
        paper_id: str,
        title: str = "",
        domain: str = "",
        output_dir: str = "",
        ctx: Context | None = None,
    ) -> str:
        """Download a paper PDF to local storage.

        Downloads the arXiv PDF and saves it to paper-notes/{domain}/{title}/
        alongside analysis notes and extracted figures. After downloading, import
        the PDF into Zotero manually for reference management.

        Args:
            paper_id: arXiv ID (e.g. "2510.24701") or arXiv URL
                (e.g. "https://arxiv.org/abs/2510.24701").
            title: Paper title, used as the folder/filename. If omitted, falls back
                to the arXiv ID as the folder name.
            domain: Optional research domain subfolder (e.g. "Bayesian-Optimization").
                If omitted, the PDF is stored directly under paper-notes/{title}/.
            output_dir: Override the output directory. If provided, domain and title are ignored.
        """

        def _impl():
            arxiv_id = _parse_arxiv_id(paper_id)
            if not arxiv_id:
                return json.dumps(
                    {
                        "error": f"Could not parse arXiv ID from '{paper_id}'. "
                        "Expected format: '2510.24701', 'https://arxiv.org/abs/2510.24701', etc.",
                        "pdf_path": None,
                    }
                )

            # Determine folder name: title (sanitized) or arXiv ID
            folder_name = _sanitize_title(title) if title and title.strip() else arxiv_id
            pdf_filename = f"{folder_name}.pdf"

            if output_dir and output_dir.strip():
                paper_dir = _validate_path_within(output_dir.strip(), get_knowledge_dir().parent)
                if paper_dir is None:
                    return json.dumps(
                        {"error": "output_dir must be within the scholar knowledge directory tree", "pdf_path": None}
                    )
            elif domain and domain.strip():
                pn_dir = get_paper_notes_dir()
                paper_dir = pn_dir / domain.strip() / folder_name
                if not paper_dir.resolve().is_relative_to(pn_dir.resolve()):
                    return json.dumps({"error": "domain must not contain path separators", "pdf_path": None})
            else:
                paper_dir = get_paper_notes_dir() / folder_name

            pdf_path = paper_dir / pdf_filename

            if pdf_path.exists():
                return json.dumps(
                    {
                        "status": "cached",
                        "pdf_path": str(pdf_path),
                        "arxiv_id": arxiv_id,
                        "title": title,
                        "size_bytes": pdf_path.stat().st_size,
                        "zotero_note": "PDF already downloaded. Import into Zotero if not done yet.",
                    },
                    ensure_ascii=False,
                    indent=2,
                )

            paper_dir.mkdir(parents=True, exist_ok=True)

            try:
                from scholar_agent.engine.academic.image_extractor import download_arxiv_pdf

                # download_arxiv_pdf saves as {arxiv_id}.pdf, rename to title-based name
                local_path = download_arxiv_pdf(arxiv_id, str(paper_dir))
                if not local_path:
                    return json.dumps({"error": "Download returned no path", "pdf_path": None, "arxiv_id": arxiv_id})
                if title and title.strip():
                    final_path = paper_dir / pdf_filename
                    Path(local_path).rename(final_path)
                    local_path = str(final_path)
            except Exception as e:
                logger.exception("download_paper failed")
                return json.dumps({"error": str(e), "pdf_path": None, "arxiv_id": arxiv_id})

            return json.dumps(
                {
                    "status": "ok",
                    "pdf_path": local_path,
                    "arxiv_id": arxiv_id,
                    "title": title,
                    "size_bytes": Path(local_path).stat().st_size,
                    "zotero_note": "PDF downloaded. Please import into Zotero: drag the PDF file into your Zotero library.",
                },
                ensure_ascii=False,
                indent=2,
            )

        return await _run_blocking(_impl, tool_name="download_paper", ctx=ctx)

    @tool
    async def extract_paper_images(
        paper_id: str,
        title: str = "",
        output_dir: str = "",
        pdf_path: str = "",
        ctx: Context | None = None,
    ) -> str:
        """Extract figures from an arXiv paper (source archive + PDF fallback).

        Downloads the arXiv source package, looks for figures in standard
        directories (pics/, figures/, fig/, images/), and falls back to
        PyMuPDF PDF image extraction if needed.

        Args:
            paper_id: arXiv ID (e.g. "2401.12345").
            title: Paper title. If provided, used to locate the local paper folder.
            output_dir: Directory for extracted images. Defaults to
                paper-notes/{title_or_id}/images/ under the knowledge root.
            pdf_path: Optional local PDF file path for extraction fallback.
        """

        def _impl() -> str:
            from scholar_agent.engine.academic.image_extractor import extract_paper_images as _extract

            if not paper_id or not paper_id.strip():
                return json.dumps({"error": "paper_id must not be empty"})

            pid = paper_id.strip()

            if not output_dir or not output_dir.strip():
                folder_name = _sanitize_title(title) if title and title.strip() else pid
                out_dir = str(get_paper_notes_dir() / folder_name / "images")
            else:
                validated = _validate_path_within(output_dir, get_knowledge_dir().parent)
                if validated is None:
                    return json.dumps({"error": "output_dir must be within the scholar knowledge directory tree"})
                out_dir = str(validated)

            # Auto-detect local PDF if pdf_path not provided
            pdf = pdf_path
            if not pdf or not pdf.strip():
                local_pdf = _find_local_pdf(pid, title=title)
                if local_pdf:
                    pdf = local_pdf
            elif pdf.strip():
                validated_pdf = _validate_path_within(pdf.strip(), get_knowledge_dir().parent)
                if validated_pdf is None:
                    return json.dumps({"error": "pdf_path must be within the scholar knowledge directory tree"})
                pdf = str(validated_pdf)

            try:
                images = _extract(pid, out_dir, pdf or None)
            except Exception as e:
                logger.exception("extract_paper_images failed")
                return json.dumps({"error": str(type(e).__name__), "images": [], "count": 0})

            result: dict[str, object] = {
                "status": "ok",
                "images": images,
                "count": len(images),
                "output_dir": out_dir,
            }
            dep_warnings = _optional_dep_warnings()
            if dep_warnings:
                result["warnings"] = dep_warnings
            return json.dumps(result, ensure_ascii=False, indent=2)

        return await _run_blocking(_impl, tool_name="extract_paper_images", ctx=ctx)

    @tool
    def paper_to_card(
        paper_json: str,
        note_path: str = "",
    ) -> str:
        """Convert a paper analysis into a knowledge card in the knowledge base.

        Takes paper metadata (and optionally a completed note) and creates a
        structured knowledge card that participates in the knowledge graph.

        Args:
            paper_json: JSON string with paper metadata (title, abstract/summary,
                scores, matched_keywords, matched_domain, arxiv_id).
            note_path: Optional path to an existing paper note file. If provided
                and the file exists, its content is used as the card answer
                for richer context.
        """
        try:
            paper = json.loads(paper_json)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid paper_json: {e}"})

        title = paper.get("title", "")
        if not title:
            return json.dumps({"error": "paper_json must contain a 'title' field"})

        # Build answer content
        answer_text = ""
        if note_path and note_path.strip():
            np = _validate_path_within(note_path.strip(), get_knowledge_dir().parent)
            if np is None:
                return json.dumps({"error": "note_path must be within the scholar knowledge directory tree"})
            if np.exists():
                with contextlib.suppress(OSError):
                    answer_text = np.read_text(encoding="utf-8")

        if not answer_text:
            abstract = paper.get("summary") or paper.get("abstract") or ""
            answer_text = f"# {title}\n\n{abstract}" if abstract else f"# {title}"

        # Build supporting claims from scores
        claims = []
        scores = paper.get("scores", {})
        domain = paper.get("best_domain", "")
        keywords = paper.get("domain_keywords", [])

        if scores:
            rec = scores.get("recommendation", 0)
            claims.append(
                {
                    "claim": f"Recommendation score: {rec:.1f}",
                    "evidence_ids": [],
                    "confidence": "high" if rec >= 7 else "medium",
                }
            )
        if domain:
            claims.append(
                {
                    "claim": f"Matched research domain: {domain}",
                    "evidence_ids": [],
                    "confidence": "high",
                }
            )

        answer_data = {
            "answer": answer_text,
            "supporting_claims": claims,
            "inferences": [f"Keywords: {', '.join(keywords[:10])}"] if keywords else [],
            "uncertainty": ["Auto-generated from paper metadata"],
            "missing_evidence": [],
            "suggested_next_steps": ["Read full paper for deeper analysis"],
        }

        arxiv_id = paper.get("arxiv_id", "")
        if arxiv_id:
            answer_data["tags"] = ["paper", f"arxiv:{arxiv_id}"]
        else:
            answer_data["tags"] = ["paper"]

        try:
            card_path = build_knowledge_card(
                title,
                answer_data,
                None,
                get_knowledge_dir(),
                index_path=get_index_path(),
            )
        except Exception as e:
            return json.dumps({"error": f"Failed to write card: {type(e).__name__}"})

        _mark_index_stale(get_index_path())

        return json.dumps(
            {
                "status": "ok",
                "card_path": str(card_path),
                "paper_title": title,
                "index_pending_refresh": True,
            },
            ensure_ascii=False,
            indent=2,
        )

    @tool
    async def daily_recommend(
        top_n: int = 10,
        language: str = "zh",
        skip_existing: bool = True,
        config_path: str = "",
        dual_track: bool = True,
        ctx: Context | None = None,
    ) -> str:
        """Generate daily paper recommendations: search, score, dedup, build note.

        When dual_track=True (default): recommends 2 top-conference papers
        (impact-ranked) + 2 arXiv innovation papers (heuristic + LLM scored).
        When dual_track=False: uses the original single-track pipeline.

        Args:
            top_n: Number of top papers (single-track mode only, default 10).
            language: Note language — "zh" (Chinese) or "en" (English).
            skip_existing: Whether to skip already-analyzed papers (default true).
            config_path: Optional YAML config path for research interests.
            dual_track: Use dual-track mode: 2 conference + 2 arXiv (default true).
        """

        def _impl():
            from scholar_agent.engine.academic.arxiv_search import _load_config
            from scholar_agent.engine.academic.daily_workflow import (
                build_daily_note,
                generate_daily_recommendations,
                generate_paper_notes_for_daily,
            )

            top_n_val = max(1, min(top_n, 50))
            lang_val = language if language in ("zh", "en") else "zh"

            # Load config
            config = {}
            if config_path:
                validated_cp = _validate_path_within(config_path, get_knowledge_dir().parent)
                if validated_cp is None:
                    return json.dumps({"error": "config_path must be within the scholar knowledge directory tree"})
                config = _load_config(str(validated_cp))
            if not config:
                interests = get_research_interests()
                if interests.get("research_domains"):
                    config = {
                        "research_domains": interests["research_domains"],
                        "excluded_keywords": interests.get("excluded_keywords", []),
                    }
            if not config:
                config = {"research_domains": {}, "excluded_keywords": []}

            # Load dual-track settings from .scholar.json
            full_config = load_config()
            daily_config = dict(full_config.get("academic", {}).get("daily_recommend", {}))
            precision_config = full_config.get("academic", {}).get("precision_funnel", {})
            # Merge unified_pipeline config from academic.unified_pipeline
            if "unified_pipeline" not in daily_config:
                uc = full_config.get("academic", {}).get("unified_pipeline", {})
                if uc:
                    daily_config["unified_pipeline"] = uc

            paper_notes_dir = str(get_paper_notes_dir())

            try:
                result = generate_daily_recommendations(
                    config=config,
                    paper_notes_dir=paper_notes_dir,
                    top_n=top_n_val,
                    skip_existing=skip_existing,
                    dual_track=dual_track,
                    daily_config=daily_config,
                    precision_config=precision_config,
                )
            except Exception as e:
                logger.exception("daily_recommend search failed")
                return json.dumps({"error": str(e), "papers": []})

            papers = result.get("papers", [])
            date_str = result.get("date", "")
            skipped = result.get("skipped", 0)
            tracks = result.get("tracks")
            funnel_stats = result.get("funnel_stats")
            pipeline_stats = result.get("stats") if result.get("unified_pipeline") else None

            # Generate per-paper skeleton notes in paper-notes/
            paper_note_stems: dict[str, str] = {}
            try:
                paper_note_stems = generate_paper_notes_for_daily(papers, paper_notes_dir, language=lang_val)
            except Exception:
                logger.warning("Per-paper note generation partially failed", exc_info=True)

            # Build daily note with wiki-links to per-paper notes
            output_dir = str(get_daily_notes_dir())
            try:
                note_path = build_daily_note(
                    date_str,
                    papers,
                    output_dir,
                    language=lang_val,
                    tracks=tracks,
                    paper_note_stems=paper_note_stems or None,
                    funnel_stats=funnel_stats,
                    pipeline_stats=pipeline_stats,
                )
            except Exception as e:
                logger.exception("daily_recommend note generation failed")
                return json.dumps({"error": f"Note generation failed: {e}", "papers": papers})

            # Auto wiki-link: cross-link paper-notes/ and the daily note
            wiki_linked = False
            try:
                from scholar_agent.engine.academic.note_linker import apply_wiki_links, build_keyword_index

                pn_path = get_paper_notes_dir()
                if pn_path.exists():
                    keyword_index = build_keyword_index(str(pn_path))
                    if keyword_index:
                        for md_file in pn_path.rglob("*.md"):
                            apply_wiki_links(str(md_file), keyword_index)
                        # Also linkify the daily note
                        apply_wiki_links(note_path, keyword_index)
                        wiki_linked = True
            except Exception:
                logger.warning("Auto wiki-linking failed", exc_info=True)

            # Identify papers for deep analysis
            top_for_analysis = []
            for p in papers[:4]:
                top_for_analysis.append(
                    {
                        "title": p.get("title", ""),
                        "arxiv_id": p.get("arxiv_id", ""),
                        "track": p.get("track", ""),
                        "impact_score": round(p.get("_impact_score", 0), 2),
                        "innovation_score": round(p.get("_innovation_final_score", 0), 3),
                        "recommendation_score": p.get("scores", {}).get("recommendation", 0),
                    }
                )

            paper_summaries = []
            for p in papers:
                entry = {
                    "title": p.get("title", ""),
                    "arxiv_id": p.get("arxiv_id", ""),
                    "track": p.get("track", ""),
                    "domain": p.get("best_domain", ""),
                }
                if p.get("_impact_score") is not None:
                    entry["impact_score"] = round(p["_impact_score"], 2)
                if p.get("_innovation_final_score") is not None:
                    entry["innovation_score"] = round(p["_innovation_final_score"], 3)
                if p.get("scores", {}).get("recommendation"):
                    entry["recommendation_score"] = p["scores"]["recommendation"]
                paper_summaries.append(entry)

            response_data = {
                "status": "ok",
                "daily_note_path": note_path,
                "date": date_str,
                "total_found": result.get("total_found", 0),
                "recommended": len(papers),
                "skipped": skipped,
                "dual_track": result.get("dual_track", False),
                "tracks": {k: {"count": v.get("count", 0)} for k, v in (tracks or {}).items()},
                "paper_notes_created": list(paper_note_stems.values()),
                "wiki_linked": wiki_linked,
                "top_for_analysis": top_for_analysis,
                "papers": paper_summaries,
            }
            if funnel_stats:
                response_data["precision_funnel"] = True
                response_data["funnel_stats"] = funnel_stats

            if result.get("unified_pipeline"):
                response_data["unified_pipeline"] = True
                response_data["pipeline_stats"] = result.get("stats", {})

            return json.dumps(
                response_data,
                ensure_ascii=False,
                indent=2,
            )

        return await _run_blocking(_impl, tool_name="daily_recommend", ctx=ctx)

    @tool
    def link_paper_keywords(
        note_path: str = "",
        notes_dir: str = "",
    ) -> str:
        """Scan notes and add [[wikilinks]] for known keywords.

        Builds a keyword index from existing notes (extracting acronyms,
        technical terms from titles and tags), then replaces keyword
        occurrences in note text with [[wikilinks]].

        Args:
            note_path: Path to a specific note to linkify. If empty,
                processes all notes in notes_dir.
            notes_dir: Directory of paper notes. Defaults to paper-notes/
                under the knowledge root.
        """
        from scholar_agent.engine.academic.note_linker import apply_wiki_links, build_keyword_index

        if not notes_dir or not notes_dir.strip():
            notes_dir = str(get_paper_notes_dir())

        notes_path = _validate_path_within(notes_dir, get_knowledge_dir().parent)
        if notes_path is None:
            return json.dumps({"error": "notes_dir must be within the scholar knowledge directory tree"})
        if not notes_path.exists():
            return json.dumps({"error": f"Notes directory not found: {notes_dir}"})

        # Build keyword index
        try:
            keyword_index = build_keyword_index(str(notes_path))
        except Exception as e:
            return json.dumps({"error": f"Failed to scan keywords: {type(e).__name__}"})

        if not keyword_index:
            return json.dumps(
                {
                    "status": "ok",
                    "notes_processed": 0,
                    "links_added": 0,
                    "message": "No linkable keywords found in existing notes.",
                }
            )

        total_processed = 0
        total_links = 0

        if note_path and note_path.strip():
            # Linkify a single note
            np = _validate_path_within(note_path.strip(), get_knowledge_dir().parent)
            if np is None:
                return json.dumps({"error": "note_path must be within the scholar knowledge directory tree"})
            if not np.exists():
                return json.dumps({"error": f"Note not found: {note_path}"})
            modified, links = apply_wiki_links(str(np), keyword_index)
            total_processed = 1
            total_links = links
        else:
            # Linkify all notes
            for md_file in notes_path.rglob("*.md"):
                modified, links = apply_wiki_links(str(md_file), keyword_index)
                if modified:
                    total_processed += 1
                    total_links += links

            # Also linkify daily-notes/ if it exists
            daily_notes_path = get_daily_notes_dir()
            if daily_notes_path.exists():
                for md_file in daily_notes_path.rglob("*.md"):
                    modified, links = apply_wiki_links(str(md_file), keyword_index)
                    if modified:
                        total_processed += 1
                        total_links += links

        return json.dumps(
            {
                "status": "ok",
                "notes_processed": total_processed,
                "links_added": total_links,
                "keywords_indexed": len(keyword_index),
            },
            ensure_ascii=False,
            indent=2,
        )

    logger.info("Academic tools enabled (SCHOLAR_ACADEMIC=%s)", SCHOLAR_ACADEMIC)


@tool
def import_paperpulse_note(paper_id: str, api_token: str | None = None) -> str:
    """Import a distilled paper note from PaperPulse SaaS directly into the local Scholar Agent knowledge base.

    Args:
        paper_id: The UUID of the paper to import.
        api_token: Optional API token. If not provided, reads 'paperpulse_token' from config.json.
    """
    from scholar_agent.engine.import_service import import_from_url

    config = load_config()
    token = api_token or config.get("paperpulse_token", "")
    base_url = config.get("paperpulse_url", "https://mindpulse.top").rstrip("/")

    msg, saved = import_from_url(paper_id, token, base_url)

    if saved is not None:
        index_path = _configured_index_path(config)
        _async_reindex(index_path)

    return msg


from http.server import BaseHTTPRequestHandler, HTTPServer


def _is_allowed_origin(origin: str | None) -> bool:
    if not origin:
        return False
    from urllib.parse import urlparse

    try:
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        if parsed.scheme == "https" and hostname == "mindpulse.top":
            return True
        if parsed.scheme == "http" and hostname in ("localhost", "127.0.0.1"):
            return True
    except Exception:
        pass
    return False


def _is_loopback_host(value: str) -> bool:
    """Return True when a Host/Origin hostname represents this machine."""
    host = value.strip().strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_loopback_peer(peer: str) -> bool:
    """Return True only for actual loopback peer addresses."""
    try:
        return ipaddress.ip_address(peer).is_loopback
    except ValueError:
        return False


def _host_header_is_loopback(host_header: str) -> bool:
    """Validate Host header hostname without trusting substring matches."""
    if not host_header:
        return False
    if host_header.startswith("["):
        host = host_header[1:].split("]", 1)[0]
    elif host_header.count(":") > 1:
        host = host_header
    else:
        host = host_header.rsplit(":", 1)[0] if ":" in host_header else host_header
    return _is_loopback_host(host)


class ScholarAgentLocalServer(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Prevent printing to stdout to avoid corrupting MCP JSON-RPC protocol
        logger.info(format % args)

    def do_OPTIONS(self):
        origin = self.headers.get("Origin")
        if _is_allowed_origin(origin):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", origin or "")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS, GET")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "86400")
            # Required for Chrome Private Network Access (public HTTPS → localhost HTTP)
            if self.headers.get("Access-Control-Request-Private-Network"):
                self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
        else:
            self.send_response(403)
            self.end_headers()

    def do_GET(self):
        origin = self.headers.get("Origin")
        if not _is_allowed_origin(origin) and origin is not None:
            self.send_response(403)
            self.end_headers()
            return

        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "version": "1.0.0"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        origin = self.headers.get("Origin")
        if not _is_allowed_origin(origin) and origin is not None:
            self.send_response(403)
            self.end_headers()
            return

        if self.path == "/import-markdown":
            # Cap body size at 10 MB to prevent OOM
            _MAX_BODY = 10 * 1024 * 1024
            try:
                content_length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                self.send_error_response(400, "Invalid Content-Length", origin)
                return
            if content_length < 0:
                self.send_error_response(400, "Invalid Content-Length", origin)
                return
            if content_length > _MAX_BODY:
                self.send_error_response(413, "Payload too large (max 10 MB)", origin)
                return
            body = self.rfile.read(content_length) if content_length > 0 else b""
            try:
                data = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as e:
                self.send_error_response(400, f"Invalid JSON body: {e!s}", origin)
                return

            if not isinstance(data, dict):
                self.send_error_response(400, "Invalid JSON payload: expected a dictionary object", origin)
                return

            # Check Authentication Token
            config = load_config()
            configured_token = config.get("paperpulse_token", "").strip()

            # Extract token from header or body
            auth_header = self.headers.get("Authorization", "")
            req_token = ""
            if auth_header.lower().startswith("bearer "):
                req_token = auth_header[7:].strip()
            else:
                req_token = data.get("token") or data.get("api_token") or ""
            req_token = str(req_token).strip()

            # If token is configured, enforce strict match.
            # If token is NOT configured, allow ONLY if request comes from local origin or no origin (direct curl/test).
            is_authenticated = False
            if configured_token:
                is_authenticated = req_token == configured_token
            else:
                host_header = self.headers.get("Host", "")
                is_local_host = _host_header_is_loopback(host_header)
                is_local_origin = False
                if origin is None:
                    is_local_origin = _is_loopback_peer(str(self.client_address[0]))
                else:
                    from urllib.parse import urlparse

                    try:
                        parsed = urlparse(origin)
                        is_local_origin = bool(parsed.hostname and _is_loopback_host(parsed.hostname))
                    except Exception:
                        is_local_origin = False
                is_authenticated = is_local_host and is_local_origin

            if not is_authenticated:
                self.send_error_response(
                    401, "Unauthorized: Invalid or missing token, or write rejected for security reasons.", origin
                )
                return

            filename = data.get("filename")
            markdown_content = data.get("markdown")

            if not filename or not markdown_content:
                self.send_error_response(400, "Missing filename or markdown content", origin)
                return

            try:
                from scholar_agent.engine.import_service import import_markdown

                msg, saved_filename = import_markdown(filename, markdown_content)

                if saved_filename is None:
                    self.send_error_response(400, msg, origin)
                    return

                config = load_config()
                index_path = _configured_index_path(config)
                _async_reindex(index_path)

                self.send_success_response(
                    origin,
                    {
                        "status": "success",
                        "filename": saved_filename,
                        "message": msg,
                    },
                )
            except Exception:
                logger.warning("HTTP /import-markdown failed", exc_info=True)
                self.send_error_response(500, "Internal server error", origin)
        else:
            self.send_error_response(404, "Not Found", origin)

    def send_success_response(self, origin, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def send_error_response(self, code, message, origin=None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode("utf-8"))


def start_local_server() -> int:
    """Start the HTTP sync server. Returns 0 on success, 1 on failure."""
    port = 8374
    try:
        server = HTTPServer(("127.0.0.1", port), ScholarAgentLocalServer)
        logger.info("Scholar Agent Local Sync Server listening on http://127.0.0.1:%d", port)
        server.serve_forever()
    except Exception:
        logger.error("Failed to start Scholar Agent Local Sync Server", exc_info=True)
        return 1
    return 0


def main() -> int:
    """Entry point for the MCP server."""
    if mcp is None:
        print("Error: fastmcp not installed. Run: pip install fastmcp", file=sys.stderr)
        return 1

    # Start the background local sync server
    t = threading.Thread(target=start_local_server, daemon=True)
    t.start()

    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
