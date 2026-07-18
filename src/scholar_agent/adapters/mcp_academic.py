"""Academic MCP tools for Scholar Agent (enabled via SCHOLAR_ACADEMIC=1).

Split out of :mod:`scholar_agent.server` (pure move, no behavior change). The
tools are registered onto the server's FastMCP instance when server.py calls
:func:`register_academic_tools`; all server-owned helpers (the ``tool``
decorator, the blocking runner, path validation, config getters) are injected
as parameters so this module never imports scholar_agent.server and the
dependency direction stays server → adapters.

Tools:
  - search_papers: Search arXiv + Semantic Scholar with scoring
  - search_conf_papers: Search conference papers via DBLP + S2 enrichment
  - analyze_paper: Generate structured markdown notes for a paper
  - download_paper: Download a paper PDF to local storage
  - extract_paper_images: Extract figures from arXiv source/PDF
  - paper_to_card: Convert paper analysis into a knowledge card
  - daily_recommend: Full daily recommendation workflow
  - link_paper_keywords: Auto-link keywords as [[wikilinks]]
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# Rebound by register_academic_tools() to the real fastmcp.Context class (or
# None when fastmcp is unavailable) before any tool is defined, so the tools'
# ``ctx: Context | None`` annotations resolve exactly as they did in server.py.
Context: Any = None


def _optional_dep_warnings() -> list[str]:
    warnings: list[str] = []
    if importlib.util.find_spec("fitz") is None:
        warnings.append("PyMuPDF not installed — PDF image extraction will not work. Install with: pip install PyMuPDF")
    return warnings


def register_academic_tools(
    *,
    tool: Callable[[Callable[..., Any]], Callable[..., Any]],
    context: Any,
    run_blocking: Callable[..., Awaitable[str]],
    validate_path_within: Callable[[str | Path, Path], Path | None],
    resolve_analysis_pdf: Callable[[dict, str], str | None],
    find_local_pdf: Callable[..., str | None],
    parse_arxiv_id: Callable[[str], str | None],
    sanitize_title: Callable[[str], str],
    async_reindex: Callable[..., Any],
    build_knowledge_card: Callable[..., Any],
    get_knowledge_dir: Callable[[], Path],
    get_index_path: Callable[[], Path],
    get_paper_notes_dir: Callable[[], Path],
    get_daily_notes_dir: Callable[[], Path],
    get_research_interests: Callable[[], dict[str, Any]],
    load_config: Callable[[], dict[str, Any]],
) -> None:
    """Register the SCHOLAR_ACADEMIC tool set on the server's FastMCP instance.

    Called once from server.py when the academic module is enabled. Parameters
    are the server-owned helpers the tools rely on; passing them in keeps the
    monkeypatch surface (``server._find_local_pdf`` etc.) anchored in server.py.
    """
    global Context
    Context = context

    _run_blocking = run_blocking
    _validate_path_within = validate_path_within
    _resolve_analysis_pdf = resolve_analysis_pdf
    _find_local_pdf = find_local_pdf
    _parse_arxiv_id = parse_arxiv_id
    _sanitize_title = sanitize_title
    _async_reindex = async_reindex

    def _resolve_research_config(
        config_path: str,
        default: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        """Resolve the research config ladder for the academic MCP tools.

        Path validation is the MCP boundary concern (``config_path`` comes from
        an untrusted tool argument, so it must stay within the scholar knowledge
        directory tree); the resolution ladder itself is shared via
        :func:`scholar_agent.engine.academic.recommender.resolve_research_interests`.
        Returns ``(config, error_json)``; ``error_json`` is None on success.
        """
        from scholar_agent.engine.academic.recommender import resolve_research_interests

        validated = config_path
        if config_path:
            validated_cp = _validate_path_within(config_path, get_knowledge_dir().parent)
            if validated_cp is None:
                return {}, json.dumps({"error": "config_path must be within the scholar knowledge directory tree"})
            validated = str(validated_cp)
        config = resolve_research_interests(
            config_path=validated,
            interests=get_research_interests(),
            default=default,
        )
        return config, None

    @tool
    def search_papers(
        query: str = "",
        categories: str = "cs.AI,cs.LG,cs.CL,cs.CV",
        max_results: int = 200,
        top_n: int = 10,
        skip_hot: bool = False,
        config_path: str = "",
    ) -> str:
        """Search academic papers across the full historical corpus.

        Performs a combined search across arXiv (recent submissions) and
        Semantic Scholar (full history, no publication-date filter), and scores
        results time-agnostically — by topic fit, citation impact, and rigor
        rather than recency — so classic foundational papers surface on equal
        footing with recent work. Use this for systematic, domain-level
        knowledge retrieval where a paper's age does not matter. For a
        recency-weighted daily feed, use ``daily_recommend`` instead.

        Args:
            query: Natural language search query for Semantic Scholar.
                If empty, uses default category-based keywords.
            categories: Comma-separated arXiv categories (default: cs.AI,cs.LG,cs.CL,cs.CV).
            max_results: Maximum arXiv results to fetch (default 200).
            top_n: Number of top-scored papers to return (default 10).
            skip_hot: If true, skip the Semantic Scholar hot-papers pass.
            config_path: Optional path to a YAML config file for research interests
                and scoring weights.
        """
        from scholar_agent.engine.academic.arxiv_search import search_and_score

        # Clamp parameters to safe ranges
        max_results = max(1, min(max_results, 500))
        top_n = max(1, min(top_n, 50))

        cats = [c.strip() for c in categories.split(",") if c.strip()]
        if not cats:
            cats = ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]

        config, config_error = _resolve_research_config(
            config_path,
            default={
                "research_domains": {
                    "deep-learning": {
                        "keywords": ["deep learning", "neural network", "representation learning"],
                        "arxiv_categories": ["cs.LG", "cs.AI"],
                        "priority": 3,
                    },
                },
                "excluded_keywords": ["tutorial", "bibliography"],
            },
        )
        if config_error:
            return config_error

        try:
            result = search_and_score(
                config=config,
                categories=cats,
                max_results=max_results,
                top_n=top_n,
                skip_hot=skip_hot,
                query=query,
                time_agnostic=True,
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

        config, config_error = _resolve_research_config(config_path)
        if config_error:
            return config_error

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
            pdf_path: Optional local PDF file path. If omitted, a PDF is resolved by
                (1) detecting an existing local PDF under paper-notes/, then
                (2) auto-downloading from arXiv when paper_json.arxiv_id is set.
                If no PDF can be resolved, returns status="error" rather than an
                empty skeleton. Result status is "ok" (fully filled) or "incomplete"
                (some <!-- LLM: --> placeholders remain).
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

            # Resolve a PDF: explicit path > local detection > arXiv auto-download.
            # Fail loud (no empty skeleton) if none can be resolved.
            try:
                detected_pdf = _resolve_analysis_pdf(paper, pdf_path)
            except ValueError as exc:
                return json.dumps({"error": str(exc)})
            if not detected_pdf:
                return json.dumps(
                    {
                        "status": "error",
                        "error": "No PDF available for analysis — a PDF is required to fill the note.",
                        "hint": "Provide pdf_path, set paper_json.arxiv_id for auto-download, or call download_paper first.",
                    }
                )

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
                return json.dumps({"error": f"Failed to generate note: {e}"})

            # Extract full text from local PDF and gate on quality (A5):
            # scanned/image-only PDFs yield empty or garbled text layers, and
            # feeding garbled text to the LLM fill/repair loop manufactures
            # nonsense. Low-quality extraction is treated as "no usable text".
            pdf_text = ""
            pdf_text_quality: dict[str, Any] = {}
            if detected_pdf and os.path.isfile(detected_pdf):
                try:
                    from scholar_agent.engine.academic.image_extractor import (
                        assess_pdf_text_quality,
                        extract_pdf_text,
                    )

                    raw_text = extract_pdf_text(detected_pdf)
                    usable, pdf_text_quality = assess_pdf_text_quality(raw_text)
                    pdf_text = raw_text if usable else ""
                except Exception:
                    pdf_text = ""
                    pdf_text_quality = {"reason": "extraction_error"}

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

            # C loop: validate against the strict validator, auto-repair until ok or cap.
            # Repair (fill/expand) needs PDF text; without it we skip the loop and rely
            # on the placeholder_count check below for status.
            validation: dict[str, Any] = {"ok": True, "errors": [], "warnings": []}
            repair_rounds = 0
            if pdf_text:
                from scholar_agent.engine.academic.paper_analyzer import auto_repair_note
                from scholar_agent.validation import validate_note

                # Read inferred paper_type from the note frontmatter (paper_analyzer
                # writes it during generation) so type_specific checks engage.
                from scholar_agent.validation.validate_note import split_frontmatter as _split_fm

                _meta, _body, _ = _split_fm(Path(note_path).read_text(encoding="utf-8"))
                note_paper_type = (_meta.get("paper_type") or "generic").strip().lower()

                validation = validate_note(note_path, paper_type=note_paper_type)
                while not validation.get("ok") and repair_rounds < 2:
                    repair = auto_repair_note(note_path, validation.get("errors", []), pdf_text, paper)
                    if not repair.get("repaired"):
                        break  # no auto-repairable errors remain
                    repair_rounds += 1
                    validation = validate_note(note_path, paper_type=note_paper_type)

            # E2: auto wiki-link the new note into the paper-notes graph so it is
            # not an island. Reuses the daily_recommend linking pattern.
            wiki_linked = False
            try:
                from scholar_agent.engine.academic.note_linker import (
                    apply_wiki_links,
                    arxiv_urls_to_wikilinks,
                    build_keyword_index,
                )
                from scholar_agent.engine.common import atomic_write_text

                pn_path = get_paper_notes_dir()
                if pn_path.exists():
                    keyword_index = build_keyword_index(str(pn_path), str(get_knowledge_dir()))
                    if keyword_index:
                        apply_wiki_links(note_path, keyword_index)
                        wiki_linked = True
                    # E1: convert arxiv URLs (External Resources) to [[wikilink]]
                    # where a matching paper-note exists (E4: only existing stems).
                    content = Path(note_path).read_text(encoding="utf-8")
                    new_content, _url_links = arxiv_urls_to_wikilinks(content, str(pn_path))
                    if new_content != content:
                        atomic_write_text(Path(note_path), new_content)
                        wiki_linked = True
            except Exception:
                logger.warning("Auto wiki-linking failed", exc_info=True)

            # A1.3: cross-check note numbers against the PDF text to catch
            # LLM-fabricated figures. Advisory only; needs usable full text.
            number_verification: dict[str, Any] = {}
            if pdf_text:
                try:
                    from scholar_agent.engine.academic.paper_analyzer import verify_note_numbers

                    number_verification = verify_note_numbers(note_path, pdf_text)
                except Exception:
                    logger.warning("Number verification failed", exc_info=True)

            # Build instructions for the caller about remaining issues
            placeholder_count = quality_check.get("placeholder_count", 0)
            unresolved_errors = validation.get("errors", [])
            instruction_parts: list[str] = []
            if pdf_text and (placeholder_count > 0 or not validation.get("ok")):
                instruction_parts.append(
                    f"Note still has {placeholder_count} unfilled <!-- LLM: --> placeholders "
                    f"and/or {len(unresolved_errors)} validation issue(s): {unresolved_errors}. "
                    "(status=incomplete). Review and supplement any gaps, or re-run analyze_paper."
                )
            elif detected_pdf and not pdf_text:
                # A5: PDF present but no usable text (scanned/image-only).
                reason = pdf_text_quality.get("reason", "unknown")
                instruction_parts.append(
                    "PDF full text was unusable "
                    f"(reason={reason}); placeholders were not auto-filled and validation was skipped. "
                    "If this is a scanned PDF, convert it to a text-based PDF (or run OCR) and re-run "
                    "analyze_paper so the closed loop can fill and verify the note."
                )
            unverified_nums = number_verification.get("unverified", [])
            if unverified_nums:
                shown = unverified_nums[:10]
                instruction_parts.append(
                    f"{len(unverified_nums)} number(s) in the note were not found in the PDF text "
                    f"and may be fabricated: {shown}. Verify them against the source before trusting."
                )
            instructions = " ".join(instruction_parts) if instruction_parts else None

            result_payload: dict[str, object] = {
                "status": "ok" if (placeholder_count == 0 and validation.get("ok")) else "incomplete",
                "note_path": note_path,
                "title": paper.get("title", ""),
                "language": lang,
                "has_related_links": bool(paper.get("related_papers")),
                "pdf_path": detected_pdf,
                "has_full_text": bool(pdf_text),
                "pdf_text_chars": len(pdf_text),
                "pdf_text_quality": pdf_text_quality,
                "number_verification": number_verification,
                "quality_check": quality_check,
                "validation": validation,
                "repair_rounds": repair_rounds,
                "wiki_linked": wiki_linked,
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
                return json.dumps({"error": str(e), "images": [], "count": 0})

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
            # Preserve individual scoring dimensions
            for dim in ("fit", "freshness", "impact", "rigor"):
                val = scores.get(dim)
                if val is not None:
                    claims.append(
                        {
                            "claim": f"{dim.capitalize()} score: {val:.2f}",
                            "evidence_ids": [],
                            "confidence": "medium",
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
            return json.dumps({"error": f"Failed to write card: {e}"})

        _async_reindex(get_index_path())

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
            from scholar_agent.engine.academic.daily_workflow import (
                build_daily_note,
                generate_paper_notes_for_daily,
            )
            from scholar_agent.engine.academic.recommender import generate_recommendations

            top_n_val = max(1, min(top_n, 50))
            lang_val = language if language in ("zh", "en") else "zh"

            # Validate config_path stays within the scholar tree (path
            # traversal guard); the engine resolves the research-config
            # ladder and merges daily/unified/precision configs itself.
            validated_cp = ""
            if config_path:
                validated = _validate_path_within(config_path, get_knowledge_dir().parent)
                if validated is None:
                    return json.dumps({"error": "config_path must be within the scholar knowledge directory tree"})
                validated_cp = str(validated)

            paper_notes_dir = str(get_paper_notes_dir())

            try:
                result = generate_recommendations(
                    config=load_config(),
                    config_path=validated_cp,
                    paper_notes_dir=paper_notes_dir,
                    top_n=top_n_val,
                    skip_existing=skip_existing,
                    dual_track=dual_track,
                )
            except Exception as e:
                logger.exception("daily_recommend search failed")
                return json.dumps({"error": str(e), "papers": []})

            papers = result.get("papers", [])
            # papers_raw is the legitimate exit channel for pipeline-internal
            # scoring fields (_impact_score, _innovation_final_score,
            # best_domain, domain_keywords, …). It is parallel to `papers`
            # (same order, same length). The clean public view is `papers`;
            # never reach into _-prefixed or internal fields on `papers` itself
            # — a pipeline rename would silently zero the summary otherwise.
            papers_raw = result.get("papers_raw", [])
            date_str = result.get("date", "")
            skipped = result.get("skipped", 0)
            tracks = result.get("tracks")
            pipeline_stats = result.get("stats") if result.get("unified_pipeline") else None

            # Note-builders read internal fields (best_domain, _impact_score,
            # domain_keywords, …) — feed them the raw view, not the clean
            # public `papers` view which deliberately omits those fields.
            note_source = papers_raw if papers_raw else papers

            # Generate per-paper skeleton notes in paper-notes/
            paper_note_stems: dict[str, str] = {}
            try:
                paper_note_stems = generate_paper_notes_for_daily(note_source, paper_notes_dir, language=lang_val)
            except Exception:
                logger.warning("Per-paper note generation partially failed", exc_info=True)

            # Build daily note with wiki-links to per-paper notes
            output_dir = str(get_daily_notes_dir())
            try:
                note_path = build_daily_note(
                    date_str,
                    note_source,
                    output_dir,
                    language=lang_val,
                    tracks=tracks,
                    paper_note_stems=paper_note_stems or None,
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
                    keyword_index = build_keyword_index(str(pn_path), str(get_knowledge_dir()))
                    if keyword_index:
                        for md_file in pn_path.rglob("*.md"):
                            apply_wiki_links(str(md_file), keyword_index)
                        # Also linkify the daily note
                        apply_wiki_links(note_path, keyword_index)
                        wiki_linked = True
            except Exception:
                logger.warning("Auto wiki-linking failed", exc_info=True)

            # Identify papers for deep analysis. Public fields come from the
            # clean `papers` view; internal scoring signals (_impact_score,
            # _innovation_final_score) come from the parallel `papers_raw`
            # exit channel — never from `papers` itself.
            top_for_analysis = []
            for idx, p in enumerate(papers[:4]):
                raw = papers_raw[idx] if idx < len(papers_raw) else {}
                top_for_analysis.append(
                    {
                        "title": p.get("title", ""),
                        "arxiv_id": p.get("arxiv_id", ""),
                        "track": p.get("track", ""),
                        "impact_score": round(raw.get("_impact_score", 0) or 0, 2),
                        "innovation_score": round(raw.get("_innovation_final_score", 0) or 0, 3),
                        "recommendation_score": p.get("scores", {}).get("recommendation", 0),
                    }
                )

            paper_summaries = []
            for idx, p in enumerate(papers):
                raw = papers_raw[idx] if idx < len(papers_raw) else {}
                entry = {
                    "title": p.get("title", ""),
                    "arxiv_id": p.get("arxiv_id", ""),
                    "track": p.get("track", ""),
                    "domain": p.get("domain", ""),
                }
                if raw.get("_impact_score") is not None:
                    entry["impact_score"] = round(raw["_impact_score"], 2)
                if raw.get("_innovation_final_score") is not None:
                    entry["innovation_score"] = round(raw["_innovation_final_score"], 3)
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
                "warnings": result.get("warnings", []),
            }

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
            keyword_index = build_keyword_index(str(notes_path), str(get_knowledge_dir()))
        except Exception as e:
            return json.dumps({"error": f"Failed to scan keywords: {e}"})

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

            # E3: also linkify knowledge cards so they link to/from paper-notes
            # (previously only paper-notes/daily-notes were linkified, leaving
            # knowledge cards unable to reach paper-notes via wiki-links).
            knowledge_path = get_knowledge_dir()
            if knowledge_path.exists() and knowledge_path != notes_path:
                for md_file in knowledge_path.rglob("*.md"):
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

