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
  # Direct run (for testing):
  python mcp_server.py

  # Via FastMCP CLI:
  fastmcp run mcp_server.py

  # Via uv (zero install):
  uv run --with fastmcp fastmcp run mcp_server.py

Configuration — add to .mcp.json in the project root:
  {
    "mcpServers": {
      "scholar-agent": {
        "command": "uv",
        "args": ["run", "--with", "fastmcp", "fastmcp", "run", "mcp_server.py"]
      }
    }
  }
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

# Ensure scripts/ is importable
ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from close_knowledge_loop import (
    build_knowledge_card,
    infer_domain,
    validate_answer_schema,
)
from close_knowledge_loop import reindex as _reindex
from scholar_config import get_knowledge_dir, get_index_path, get_research_interests
from local_retrieve import retrieve

logger = logging.getLogger(__name__)

# Academic tools module toggle (set SCHOLAR_ACADEMIC=1 to enable)
SCHOLAR_ACADEMIC = os.environ.get("SCHOLAR_ACADEMIC", "").strip() in ("1", "true", "yes")

try:
    from fastmcp import FastMCP
    mcp = FastMCP("scholar-agent")
    tool = mcp.tool
except ImportError:
    # Allow running without fastmcp — decorators become no-ops
    mcp = None  # type: ignore[assignment]
    def tool(fn):  # type: ignore[misc]
        return fn


def _stale_marker_path(index_path: Path) -> Path:
    return index_path.with_suffix(index_path.suffix + ".stale")


def _refresh_lock_path(index_path: Path) -> Path:
    return index_path.with_suffix(index_path.suffix + ".lock")


def _mark_index_stale(index_path: Path) -> None:
    marker = _stale_marker_path(index_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("stale\n", encoding="utf-8")


def _clear_index_stale(index_path: Path) -> None:
    marker = _stale_marker_path(index_path)
    try:
        marker.unlink()
    except FileNotFoundError:
        pass


def _acquire_refresh_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    else:
        os.close(fd)
        return True


def _release_refresh_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def _ensure_index_ready() -> tuple[Path, bool, str | None]:
    index_path = get_index_path()
    marker = _stale_marker_path(index_path)
    needs_refresh = marker.exists() or not index_path.exists()
    if not needs_refresh:
        return index_path, False, None

    lock_path = _refresh_lock_path(index_path)
    if not _acquire_refresh_lock(lock_path):
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if not lock_path.exists():
                if not marker.exists() or index_path.exists():
                    return index_path, True, None
                break
            time.sleep(0.05)
        return index_path, True, "Index refresh is already in progress; retry the request in a moment."

    try:
        reindex_ok = _reindex(get_knowledge_dir(), index_path)
        if reindex_ok:
            _clear_index_stale(index_path)
            return index_path, True, None

        logger.warning("lazy reindex failed for %s", index_path)
        if not index_path.exists():
            return index_path, True, "Knowledge index not found and automatic refresh failed."
        return index_path, True, "Automatic refresh failed; serving the last available index."
    finally:
        _release_refresh_lock(lock_path)


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

    index_path, refreshed, refresh_error = _ensure_index_ready()

    if not index_path.exists():
        return json.dumps({
            "error": refresh_error or "Knowledge index not found. Run local_index.py first.",
            "results": [],
        })

    result = retrieve(query, index_path, limit)
    if refresh_error:
        result["warning"] = refresh_error
    if refreshed:
        result["index_refreshed"] = True
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def save_research(query: str, answer_json: str) -> str:
    """Save structured research results as a knowledge card in the local knowledge base.

    The answer_json must conform to schemas/answer.schema.json:
    {
      "answer": "detailed answer text",
      "supporting_claims": [{"claim": "...", "evidence_ids": ["..."], "confidence": "high|medium|low"}],
      "inferences": ["..."],
      "uncertainty": ["..."],
      "missing_evidence": ["..."],
      "suggested_next_steps": ["..."],
      "visual_aids": [{"type": "mermaid|image_url|image_path", "content": "...", "caption": "...", "alt_text": "..."}]
    }

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
    """
    # Validate query — reject path traversal characters
    if not query or not query.strip():
        return json.dumps({"error": "query must not be empty"})
    for char in ("..", "/", "\\"):
        if char in query:
            return json.dumps({"error": f"query must not contain path separators or traversal sequences"})

    try:
        answer_data = json.loads(answer_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {e}"})

    # Validate against schema
    warnings = validate_answer_schema(answer_data)

    # Build knowledge card
    try:
        card_path = build_knowledge_card(query, answer_data, None, get_knowledge_dir(), index_path=get_index_path())
    except Exception as e:
        return json.dumps({"error": f"Failed to write card: {e}"})

    index_path = get_index_path()
    _mark_index_stale(index_path)

    return json.dumps({
        "status": "ok",
        "card_path": str(card_path),
        "reindexed": False,
        "index_pending_refresh": True,
        "schema_warnings": warnings,
    }, ensure_ascii=False, indent=2)


@tool
def list_knowledge(topic: str | None = None) -> str:
    """List all knowledge cards in the local knowledge base.

    Returns card metadata (id, title, topic, type) for browsing and discovery.

    Args:
        topic: Optional topic filter (e.g. 'qpe', 'markov_chain'). Returns all if omitted.
    """
    if topic is not None:
        for char in ("..", "/", "\\"):
            if char in topic:
                return json.dumps({"error": "topic must not contain path separators or traversal sequences", "cards": [], "total": 0})
    index_path, refreshed, refresh_error = _ensure_index_ready()
    if not index_path.exists():
        return json.dumps({"cards": [], "total": 0, "error": refresh_error or "Index not found. Run local_index.py first."})

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
        cards.append({
            "id": doc.get("doc_id", ""),
            "title": doc.get("title", ""),
            "domain": doc.get("domain", ""),
            "topic": doc.get("topic", ""),
            "type": doc.get("type", ""),
            "path": doc.get("path", ""),
            "links": doc.get("links", []),
            "backlinks": doc.get("backlinks", []),
        })

    payload = {"cards": cards, "total": len(cards)}
    if refresh_error:
        payload["warning"] = refresh_error
    if refreshed:
        payload["index_refreshed"] = True
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def capture_answer(query: str, answer: str, tags: str = "") -> str:
    """Capture a useful Q&A answer as a draft knowledge card.

    Use this when a conversation produces a substantive answer that isn't
    already in the knowledge base and is worth persisting. The card is
    created as a draft with low verification level.

    Unlike save_research, this tool does not require structured JSON or
    evidence — just the question and the answer text.

    Args:
        query: The question that was answered.
        answer: The answer text (plain text or markdown).
        tags: Comma-separated tags for the card (optional).
    """
    if not query or not query.strip():
        return json.dumps({"error": "query must not be empty"})
    if not answer or not answer.strip():
        return json.dumps({"error": "answer must not be empty"})
    for char in ("..", "/", "\\"):
        if char in query:
            return json.dumps({"error": "query must not contain path separators or traversal sequences"})

    # Build a minimal structured answer for the card builder
    answer_data = {
        "answer": answer,
        "supporting_claims": [],
        "inferences": [],
        "uncertainty": ["Captured from conversation — not yet verified against sources"],
        "missing_evidence": ["Source references needed"],
        "suggested_next_steps": ["Verify against authoritative sources", "Add supporting evidence"],
    }

    if tags and tags.strip():
        answer_data["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

    # Build the card
    try:
        card_path = build_knowledge_card(query, answer_data, None, get_knowledge_dir(), index_path=get_index_path())
    except Exception as e:
        return json.dumps({"error": f"Failed to write card: {e}"})

    index_path = get_index_path()
    _mark_index_stale(index_path)

    return json.dumps({
        "status": "ok",
        "card_path": str(card_path),
        "reindexed": False,
        "index_pending_refresh": True,
        "note": "Card created as draft. Verify and promote when confidence is confirmed.",
    }, ensure_ascii=False, indent=2)


@tool
def ingest_source(source: str, title: str = "", tags: str = "") -> str:
    """Ingest a URL or raw text into the knowledge base as a draft card.

    For URLs: fetches the page content, extracts text, and saves as a card.
    For text: saves the provided text directly as a card.

    Use this when you want to add external documents, articles, or notes
    to the knowledge base without requiring structured JSON.

    Args:
        source: A URL (starting with http:// or https://) or raw text/markdown.
        title: Optional title for the card. Auto-detected from URL pages.
        tags: Comma-separated tags for the card (optional).
    """
    if not source or not source.strip():
        return json.dumps({"error": "source must not be empty"})

    is_url = source.strip().startswith(("http://", "https://"))

    if is_url:
        from research_harness import fetch_content
        result = fetch_content(source.strip())
        if result["retrieval_status"] == "failed":
            return json.dumps({"error": f"Failed to fetch URL: {result.get('failure_reason', 'unknown')}"})
        content = result["content_md"]
        auto_title = result.get("title", "") or title or source.strip()[:80]
    else:
        content = source.strip()
        auto_title = title or content.split("\n")[0][:80]

    if not auto_title or not auto_title.strip():
        auto_title = f"untitled-{__import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    if not content:
        return json.dumps({"error": "No content extracted from source"})

    answer_data = {
        "answer": content,
        "supporting_claims": [],
        "inferences": [],
        "uncertainty": ["Ingested source — not yet verified or synthesized"],
        "missing_evidence": ["Cross-reference with other sources needed"],
        "suggested_next_steps": ["Verify key claims", "Link to related cards"],
    }

    if tags and tags.strip():
        answer_data["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    if is_url:
        answer_data["tags"] = answer_data.get("tags", []) + ["ingested-url"]

    try:
        card_path = build_knowledge_card(auto_title, answer_data, None, get_knowledge_dir(), index_path=get_index_path())
    except Exception as e:
        return json.dumps({"error": f"Failed to write card: {e}"})

    index_path = get_index_path()
    _mark_index_stale(index_path)

    return json.dumps({
        "status": "ok",
        "card_path": str(card_path),
        "reindexed": False,
        "index_pending_refresh": True,
        "source_type": "url" if is_url else "text",
        "title": auto_title,
    }, ensure_ascii=False, indent=2)


@tool
def build_graph() -> str:
    """Build an interactive knowledge graph visualization.

    Generates a self-contained HTML file showing all knowledge cards as nodes
    and their wiki-links as edges. Open the output file in a browser to
    explore the knowledge graph visually. Compatible with Obsidian vaults.

    Returns the path to the generated graph.html file.
    """
    from build_graph import build_graph_data, generate_html

    index_path, _refreshed, refresh_error = _ensure_index_ready()
    if not index_path.exists():
        return json.dumps({"error": refresh_error or "Index not found. Run local_index.py first."})

    graph_data = build_graph_data(index_path)
    output_path = ROOT / "graph.html"
    generate_html(graph_data, output_path)

    return json.dumps({
        "status": "ok",
        "path": str(output_path),
        "nodes": len(graph_data["nodes"]),
        "edges": len(graph_data["edges"]),
    }, ensure_ascii=False, indent=2)


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


def _sanitize_title(title: str) -> str:
    """Convert a paper title to a filesystem-safe directory/filename."""
    import unicodedata
    # Normalize unicode, replace common separators
    s = unicodedata.normalize("NFKC", title.strip())
    # Replace colons, slashes, and other problematic chars
    s = _re.sub(r"[:/\\?*|\"<>,;&%#@!()]", " ", s)
    # Collapse whitespace and strip
    s = _re.sub(r"\s+", " ", s).strip()
    # Replace spaces with underscores
    s = s.replace(" ", "_")
    # Truncate to reasonable length
    if len(s) > 120:
        s = s[:120].rstrip("_")
    return s or "untitled"


def _find_local_pdf(arxiv_id: str, title: str = "") -> str | None:
    """Search paper-notes/ for an existing local PDF by title or arXiv ID."""
    paper_notes_dir = get_knowledge_dir().parent / "paper-notes"
    if not paper_notes_dir.exists():
        return None
    # Search by sanitized title first
    if title:
        safe = _sanitize_title(title)
        candidate = paper_notes_dir.rglob(f"{safe}/{safe}.pdf")
        for match in candidate:
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
        from academic.arxiv_search import search_and_score, _load_config

        # Clamp parameters to safe ranges
        max_results = max(1, min(max_results, 500))
        top_n = max(1, min(top_n, 50))

        cats = [c.strip() for c in categories.split(",") if c.strip()]
        if not cats:
            cats = ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]

        config = {}
        if config_path:
            config = _load_config(config_path)
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
                    "大模型": {
                        "keywords": ["pre-training", "foundation model", "LLM", "large language model", "transformer", "GPT"],
                        "arxiv_categories": ["cs.AI", "cs.LG", "cs.CL"],
                        "priority": 5,
                    },
                },
                "excluded_keywords": ["survey", "workshop"],
            }

        try:
            result = search_and_score(
                config=config,
                categories=cats,
                max_results=max_results,
                top_n=top_n,
                skip_hot=skip_hot,
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
        from academic.conf_search import search_and_score_conferences, DBLP_VENUES
        from academic.arxiv_search import _load_config

        if year <= 0:
            from datetime import datetime
            year = datetime.now().year

        venue_list = [v.strip().upper() for v in venues.split(",") if v.strip()]
        # Validate venue names
        invalid = [v for v in venue_list if v not in DBLP_VENUES]
        if invalid:
            return json.dumps({
                "error": f"Unknown venues: {invalid}. Supported: {list(DBLP_VENUES.keys())}",
                "papers": [],
                "total_found": 0,
            })

        kws = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else None
        ex_kws = [k.strip() for k in excluded_keywords.split(",") if k.strip()] if excluded_keywords else None

        config = {}
        if config_path:
            config = _load_config(config_path)
        if not config:
            interests = get_research_interests()
            if interests.get("research_domains"):
                config = {
                    "research_domains": interests["research_domains"],
                    "excluded_keywords": interests.get("excluded_keywords", []),
                }
        if not config:
            config = {"research_domains": {}, "excluded_keywords": []}

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
    def analyze_paper(
        paper_json: str,
        output_dir: str = "",
        language: str = "zh",
        all_papers_json: str = "",
        images_json: str = "",
        pdf_path: str = "",
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
        from academic.paper_analyzer import generate_note
        from academic.note_linker import find_related_papers

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
            detected_pdf = pdf_path.strip()

        # Resolve output directory
        if not output_dir or not output_dir.strip():
            output_dir = str(get_knowledge_dir().parent / "paper-notes")
        out_path = Path(output_dir)
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
            related = find_related_papers(paper, other_papers, max_links=5)
            if related:
                paper["related_papers"] = related

        # Validate language
        if language not in ("zh", "en"):
            language = "zh"

        # Parse images
        images = None
        if images_json and images_json.strip():
            try:
                images = json.loads(images_json)
                if not isinstance(images, list):
                    images = None
            except json.JSONDecodeError:
                images = None

        try:
            note_path = generate_note(
                paper, str(out_path), language=language, images=images,
                local_pdf_path=detected_pdf or "",
            )
        except Exception as e:
            logger.exception("analyze_paper failed")
            return json.dumps({"error": f"Failed to generate note: {e}"})

        # Extract full text from local PDF if available
        pdf_text = ""
        if detected_pdf and os.path.isfile(detected_pdf):
            try:
                from academic.image_extractor import extract_pdf_text
                pdf_text = extract_pdf_text(detected_pdf)
            except Exception:
                pdf_text = ""

        # Quality check on the generated note
        quality_check = {"has_issues": False, "issues": [], "placeholder_count": 0}
        try:
            from academic.paper_analyzer import check_note_quality
            quality_check = check_note_quality(note_path)
        except Exception:
            pass

        # Build instructions for the caller about filling placeholders
        placeholder_count = quality_check.get("placeholder_count", 0)
        instructions = None
        if placeholder_count > 0 and pdf_text:
            instructions = (
                "MUST fill all <!-- LLM: --> placeholders using pdf_text before showing to user. "
                f"Note has {placeholder_count} placeholders. "
                "Use Write tool to replace the skeleton note with fully filled content. "
                "See SKILL.md '内容填充规则' section for detailed rules."
            )

        return json.dumps({
            "status": "ok",
            "note_path": note_path,
            "title": paper.get("title", ""),
            "language": language,
            "has_related_links": bool(paper.get("related_papers")),
            "pdf_path": detected_pdf,
            "has_full_text": bool(pdf_text),
            "pdf_text": pdf_text,
            "quality_check": quality_check,
            "instructions": instructions,
        }, ensure_ascii=False, indent=2)

    @tool
    def download_paper(
        paper_id: str,
        title: str = "",
        domain: str = "",
        output_dir: str = "",
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
        arxiv_id = _parse_arxiv_id(paper_id)
        if not arxiv_id:
            return json.dumps({
                "error": f"Could not parse arXiv ID from '{paper_id}'. "
                         "Expected format: '2510.24701', 'https://arxiv.org/abs/2510.24701', etc.",
                "pdf_path": None,
            })

        # Determine folder name: title (sanitized) or arXiv ID
        folder_name = _sanitize_title(title) if title and title.strip() else arxiv_id
        pdf_filename = f"{folder_name}.pdf"

        if output_dir and output_dir.strip():
            paper_dir = Path(output_dir.strip())
        elif domain and domain.strip():
            for char in ("..", "/", "\\"):
                if char in domain:
                    return json.dumps({"error": "domain must not contain path separators", "pdf_path": None})
            paper_dir = get_knowledge_dir().parent / "paper-notes" / domain.strip() / folder_name
        else:
            paper_dir = get_knowledge_dir().parent / "paper-notes" / folder_name

        pdf_path = paper_dir / pdf_filename

        if pdf_path.exists():
            return json.dumps({
                "status": "cached",
                "pdf_path": str(pdf_path),
                "arxiv_id": arxiv_id,
                "title": title,
                "size_bytes": pdf_path.stat().st_size,
                "zotero_note": "PDF already downloaded. Import into Zotero if not done yet.",
            }, ensure_ascii=False, indent=2)

        paper_dir.mkdir(parents=True, exist_ok=True)

        try:
            from academic.image_extractor import download_arxiv_pdf
            # download_arxiv_pdf saves as {arxiv_id}.pdf, rename to title-based name
            local_path = download_arxiv_pdf(arxiv_id, str(paper_dir))
            if local_path and title and title.strip():
                final_path = paper_dir / pdf_filename
                Path(local_path).rename(final_path)
                local_path = str(final_path)
        except Exception as e:
            logger.exception("download_paper failed")
            return json.dumps({"error": str(e), "pdf_path": None, "arxiv_id": arxiv_id})

        return json.dumps({
            "status": "ok",
            "pdf_path": local_path,
            "arxiv_id": arxiv_id,
            "title": title,
            "size_bytes": Path(local_path).stat().st_size,
            "zotero_note": "PDF downloaded. Please import into Zotero: drag the PDF file into your Zotero library.",
        }, ensure_ascii=False, indent=2)

    @tool
    def extract_paper_images(
        paper_id: str,
        title: str = "",
        output_dir: str = "",
        pdf_path: str = "",
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
        from academic.image_extractor import extract_paper_images as _extract

        if not paper_id or not paper_id.strip():
            return json.dumps({"error": "paper_id must not be empty"})

        paper_id = paper_id.strip()

        if not output_dir or not output_dir.strip():
            folder_name = _sanitize_title(title) if title and title.strip() else paper_id
            output_dir = str(get_knowledge_dir().parent / "paper-notes" / folder_name / "images")

        # Auto-detect local PDF if pdf_path not provided
        if not pdf_path or not pdf_path.strip():
            local_pdf = _find_local_pdf(paper_id, title=title)
            if local_pdf:
                pdf_path = local_pdf

        try:
            images = _extract(paper_id, output_dir, pdf_path or None)
        except Exception as e:
            logger.exception("extract_paper_images failed")
            return json.dumps({"error": str(e), "images": [], "count": 0})

        return json.dumps({
            "status": "ok",
            "images": images,
            "count": len(images),
            "output_dir": output_dir,
        }, ensure_ascii=False, indent=2)

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
            np = Path(note_path.strip())
            if np.exists():
                try:
                    answer_text = np.read_text(encoding="utf-8")
                except OSError:
                    pass

        if not answer_text:
            abstract = paper.get("summary") or paper.get("abstract") or ""
            answer_text = f"# {title}\n\n{abstract}" if abstract else f"# {title}"

        # Build supporting claims from scores
        claims = []
        scores = paper.get("scores", {})
        domain = paper.get("matched_domain", "")
        keywords = paper.get("matched_keywords", [])

        if scores:
            rec = scores.get("recommendation", 0)
            claims.append({
                "claim": f"Recommendation score: {rec:.1f}",
                "evidence_ids": [],
                "confidence": "high" if rec >= 7 else "medium",
            })
        if domain:
            claims.append({
                "claim": f"Matched research domain: {domain}",
                "evidence_ids": [],
                "confidence": "high",
            })

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
                title, answer_data, None,
                get_knowledge_dir(), index_path=get_index_path(),
            )
        except Exception as e:
            return json.dumps({"error": f"Failed to write card: {e}"})

        _mark_index_stale(get_index_path())

        return json.dumps({
            "status": "ok",
            "card_path": str(card_path),
            "paper_title": title,
            "index_pending_refresh": True,
        }, ensure_ascii=False, indent=2)

    @tool
    def daily_recommend(
        top_n: int = 10,
        language: str = "zh",
        skip_existing: bool = True,
        config_path: str = "",
    ) -> str:
        """Generate daily paper recommendations: search, score, dedup, build note.

        Runs the full daily workflow: searches arXiv + Semantic Scholar,
        scores papers against research interests, deduplicates against
        existing notes, and generates a daily recommendation markdown file.

        Args:
            top_n: Number of top papers to recommend (default 10).
            language: Note language — "zh" (Chinese) or "en" (English).
            skip_existing: Whether to skip already-analyzed papers (default true).
            config_path: Optional YAML config path for research interests.
        """
        from academic.daily_workflow import generate_daily_recommendations, build_daily_note
        from academic.arxiv_search import _load_config

        top_n = max(1, min(top_n, 50))
        if language not in ("zh", "en"):
            language = "zh"

        # Load config
        config = {}
        if config_path:
            config = _load_config(config_path)
        if not config:
            interests = get_research_interests()
            if interests.get("research_domains"):
                config = {
                    "research_domains": interests["research_domains"],
                    "excluded_keywords": interests.get("excluded_keywords", []),
                }
        if not config:
            config = {"research_domains": {}, "excluded_keywords": []}

        paper_notes_dir = str(get_knowledge_dir().parent / "paper-notes")

        try:
            result = generate_daily_recommendations(
                config=config,
                paper_notes_dir=paper_notes_dir,
                top_n=top_n,
                skip_existing=skip_existing,
            )
        except Exception as e:
            logger.exception("daily_recommend search failed")
            return json.dumps({"error": str(e), "papers": []})

        papers = result.get("papers", [])
        date_str = result.get("date", "")
        skipped = result.get("skipped", 0)

        # Build daily note
        output_dir = str(get_knowledge_dir().parent / "daily-notes")
        try:
            note_path = build_daily_note(date_str, papers, output_dir, language=language)
        except Exception as e:
            logger.exception("daily_recommend note generation failed")
            return json.dumps({"error": f"Note generation failed: {e}", "papers": papers})

        # Identify top 3 for deep analysis
        top3 = []
        for p in papers[:3]:
            top3.append({
                "title": p.get("title", ""),
                "arxiv_id": p.get("arxiv_id", ""),
                "score": p.get("scores", {}).get("recommendation", 0),
            })

        return json.dumps({
            "status": "ok",
            "daily_note_path": note_path,
            "date": date_str,
            "total_found": result.get("total_found", 0),
            "recommended": len(papers),
            "skipped": skipped,
            "top3_for_analysis": top3,
            "papers": [
                {
                    "title": p.get("title", ""),
                    "arxiv_id": p.get("arxiv_id", ""),
                    "score": p.get("scores", {}).get("recommendation", 0),
                    "domain": p.get("matched_domain", ""),
                }
                for p in papers
            ],
        }, ensure_ascii=False, indent=2)

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
        from academic.note_linker import scan_notes_for_keywords, linkify_keywords

        if not notes_dir or not notes_dir.strip():
            notes_dir = str(get_knowledge_dir().parent / "paper-notes")

        notes_path = Path(notes_dir)
        if not notes_path.exists():
            return json.dumps({"error": f"Notes directory not found: {notes_dir}"})

        # Build keyword index
        try:
            keyword_index = scan_notes_for_keywords(notes_dir)
        except Exception as e:
            return json.dumps({"error": f"Failed to scan keywords: {e}"})

        if not keyword_index:
            return json.dumps({
                "status": "ok",
                "notes_processed": 0,
                "links_added": 0,
                "message": "No linkable keywords found in existing notes.",
            })

        total_processed = 0
        total_links = 0

        if note_path and note_path.strip():
            # Linkify a single note
            np = Path(note_path.strip())
            if not np.exists():
                return json.dumps({"error": f"Note not found: {note_path}"})
            modified, links = linkify_keywords(str(np), keyword_index)
            total_processed = 1
            total_links = links
        else:
            # Linkify all notes
            for md_file in notes_path.rglob("*.md"):
                modified, links = linkify_keywords(str(md_file), keyword_index)
                if modified:
                    total_processed += 1
                    total_links += links

        return json.dumps({
            "status": "ok",
            "notes_processed": total_processed,
            "links_added": total_links,
            "keywords_indexed": len(keyword_index),
        }, ensure_ascii=False, indent=2)

    logger.info("Academic tools enabled (SCHOLAR_ACADEMIC=%s)", SCHOLAR_ACADEMIC)


def main():
    """Entry point for the MCP server."""
    if mcp is None:
        print("Error: fastmcp not installed. Run: pip install fastmcp", file=sys.stderr)
        sys.exit(1)
    mcp.run()


if __name__ == "__main__":
    main()
