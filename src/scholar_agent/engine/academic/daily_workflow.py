"""Daily paper recommendation workflow — dual-track edition.

Provides:
  - get_analyzed_paper_ids: scan paper-notes/ for already-analyzed papers
  - filter_already_analyzed: remove already-analyzed papers from a list
  - generate_daily_recommendations: dual-track (conference + arXiv) pipeline
  - generate_paper_notes_for_daily: create per-paper notes for recommended papers
  - build_daily_note: generate a daily recommendation markdown note with wiki-links
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


from scholar_agent.engine.common import parse_frontmatter

# ---------------------------------------------------------------------------
# Already-read dedup
# ---------------------------------------------------------------------------


def get_analyzed_paper_ids(paper_notes_dir: str) -> set[str]:
    """Return arxiv IDs of already-analyzed papers.

    Prefers SQLite paper store when available, falls back to scanning
    paper-notes/ markdown files.
    """
    ids: set[str] = set()

    # Try SQLite first
    try:
        from scholar_agent.engine.paper_store import PaperStore
        from scholar_agent.engine.scholar_config import get_paper_db_path

        db_path = get_paper_db_path()
        if db_path.exists():
            store = PaperStore(db_path)
            store.initialize()
            try:
                recommended = store.get_papers_by_status("recommended")
                for p in recommended:
                    arxiv_id = p.get("arxiv_id", "")
                    if arxiv_id:
                        ids.add(arxiv_id)
            finally:
                store.close()
    except Exception:
        logger.debug("SQLite dedup unavailable, falling back to file scan")

    # Fallback: scan paper-notes/ markdown files
    notes_path = Path(paper_notes_dir)
    if not notes_path.exists():
        return set()

    for md_file in notes_path.rglob("*.md"):
        try:
            raw = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta, _ = parse_frontmatter(raw)
        paper_id = meta.get("paper_id", "")
        if paper_id:
            normalized = re.sub(r"^arXiv:\s*", "", str(paper_id)).strip()
            if normalized:
                ids.add(normalized)
    return ids


def filter_already_analyzed(
    papers: list[dict[str, Any]],
    existing_ids: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """Filter out already-analyzed papers. Returns (remaining, filtered_count)."""
    remaining = []
    for p in papers:
        arxiv_id = p.get("arxiv_id") or p.get("paper_id") or ""
        normalized = re.sub(r"^arXiv:\s*", "", str(arxiv_id)).strip()
        if normalized and normalized in existing_ids:
            continue
        remaining.append(p)
    return remaining, len(papers) - len(remaining)


# ---------------------------------------------------------------------------
# Diversity helpers
# ---------------------------------------------------------------------------


def _title_word_overlap(title_a: str, title_b: str) -> float:
    """Jaccard overlap of normalized title words."""

    def _words(s: str) -> set[str]:
        return set(re.sub(r"[^a-z0-9\s]", "", s.lower()).split())

    wa = _words(title_a)
    wb = _words(title_b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _diversity_filter(papers: list[dict[str, Any]], top_n: int = 2, threshold: float = 0.6) -> list[dict[str, Any]]:
    """Pick *top_n* papers with pairwise title overlap below *threshold*."""
    if len(papers) <= top_n:
        return papers

    selected = [papers[0]]
    for p in papers[1:]:
        if len(selected) >= top_n:
            break
        if all(_title_word_overlap(p.get("title", ""), s.get("title", "")) < threshold for s in selected):
            selected.append(p)
    return selected


# ---------------------------------------------------------------------------
# Dual-track recommendation
# ---------------------------------------------------------------------------


def _generate_track_conference(
    config: dict[str, Any],
    paper_notes_dir: str,
    top_n: int = 2,
    skip_existing: bool = True,
    years: list[int] | None = None,
    venues: list[str] | None = None,
    max_enrich: int = 100,
) -> dict[str, Any]:
    """Track 1: top conference papers ranked by citation impact."""
    from scholar_agent.engine.academic.conf_search import search_conferences_multi_year

    candidates = search_conferences_multi_year(
        config=config,
        years=years,
        venues=venues,
        max_enrich=max_enrich,
    )

    skipped = 0
    if skip_existing and paper_notes_dir:
        existing_ids = get_analyzed_paper_ids(paper_notes_dir)
        if existing_ids:
            candidates, skipped = filter_already_analyzed(candidates, existing_ids)

    # Diversity filter to ensure top_n cover different topics
    selected = _diversity_filter(candidates, top_n=top_n)

    for p in selected:
        p["track"] = "conference"

    return {"papers": selected, "total_found": len(candidates), "skipped": skipped}


def _generate_track_arxiv_innovation(
    config: dict[str, Any],
    paper_notes_dir: str,
    categories: list[str] | None = None,
    top_n: int = 2,
    skip_existing: bool = True,
    days_window: int = 7,
    max_candidates: int = 15,
    target_date: datetime | None = None,
) -> dict[str, Any]:
    """Track 2: arXiv innovation papers — heuristic + LLM batch scoring."""
    from scholar_agent.engine.academic.arxiv_search import query_arxiv
    from scholar_agent.engine.academic.innovation_scorer import innovation_llm_batch_score, innovation_pre_filter

    cats = categories or ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]
    now = target_date or datetime.now()
    start = now - timedelta(days=days_window)
    end = now

    raw_papers = query_arxiv(cats, start, end, limit=200)

    # Heuristic pre-filter
    candidates = innovation_pre_filter(raw_papers, config, max_candidates=max_candidates)

    # LLM batch scoring
    candidates = innovation_llm_batch_score(candidates)

    skipped = 0
    if skip_existing and paper_notes_dir:
        existing_ids = get_analyzed_paper_ids(paper_notes_dir)
        if existing_ids:
            candidates, skipped = filter_already_analyzed(candidates, existing_ids)

    selected = candidates[:top_n]

    for p in selected:
        p["track"] = "arxiv_innovation"

    return {"papers": selected, "total_found": len(raw_papers), "skipped": skipped}


def generate_daily_recommendations(
    config: dict[str, Any],
    paper_notes_dir: str,
    categories: list[str] | None = None,
    top_n: int = 10,
    skip_existing: bool = True,
    target_date: datetime | None = None,
    dual_track: bool = True,
    daily_config: dict[str, Any] | None = None,
    precision_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate daily paper recommendations.

    Routing priority:
      1. Unified pipeline (default when enabled)
      2. Precision funnel (when precision_config.enabled=true)
      3. Dual-track / single-track (legacy fallback)
    """
    date_str = (target_date or datetime.now()).strftime("%Y-%m-%d")

    # Unified pipeline (default path)
    dc = daily_config or {}
    uc = dc.get("unified_pipeline", {})
    if uc.get("enabled", True):
        return _generate_unified(
            config=config,
            paper_notes_dir=paper_notes_dir,
            target_date=target_date,
            date_str=date_str,
            unified_config=uc,
        )

    # Precision funnel path
    pc = precision_config or {}
    if pc.get("enabled"):
        return _generate_precision(
            config=config,
            paper_notes_dir=paper_notes_dir,
            target_date=target_date,
            date_str=date_str,
            precision_config=pc,
        )

    if not dual_track:
        return _generate_single_track(
            config,
            paper_notes_dir,
            categories,
            top_n,
            skip_existing,
            target_date,
            date_str,
        )

    dc = daily_config or {}
    conf_cfg = dc.get("conference", {})
    arxiv_cfg = dc.get("arxiv_innovation", {})

    # Track 1: conference
    conf_result = _generate_track_conference(
        config=config,
        paper_notes_dir=paper_notes_dir,
        top_n=2,
        skip_existing=skip_existing,
        years=conf_cfg.get("years"),
        venues=conf_cfg.get("venues"),
        max_enrich=conf_cfg.get("max_enrich", 100),
    )

    # Track 2: arXiv innovation
    arxiv_result = _generate_track_arxiv_innovation(
        config=config,
        paper_notes_dir=paper_notes_dir,
        categories=categories,
        top_n=2,
        skip_existing=skip_existing,
        days_window=arxiv_cfg.get("days_window", 7),
        max_candidates=arxiv_cfg.get("max_candidates", 15),
        target_date=target_date,
    )

    conf_papers = conf_result["papers"]
    arxiv_papers = arxiv_result["papers"]
    all_papers = conf_papers + arxiv_papers

    return {
        "date": date_str,
        "papers": all_papers,
        "tracks": {
            "conference": {"count": len(conf_papers), "papers": conf_papers},
            "arxiv_innovation": {"count": len(arxiv_papers), "papers": arxiv_papers},
        },
        "skipped": conf_result["skipped"] + arxiv_result["skipped"],
        "total_found": conf_result["total_found"] + arxiv_result["total_found"],
        "dual_track": True,
    }


def _generate_unified(
    config: dict[str, Any],
    paper_notes_dir: str,
    target_date: datetime | None,
    date_str: str,
    unified_config: dict[str, Any],
) -> dict[str, Any]:
    """Unified lightweight pipeline: concurrent fetch -> CPU filter -> 1 LLM call."""
    from scholar_agent.engine.academic.unified_pipeline import run_unified_pipeline

    result = run_unified_pipeline(
        config=config,
        paper_notes_dir=paper_notes_dir,
        target_date=target_date,
        unified_config=unified_config,
    )

    result["date"] = date_str
    return result


def _generate_precision(
    config: dict[str, Any],
    paper_notes_dir: str,
    target_date: datetime | None,
    date_str: str,
    precision_config: dict[str, Any],
) -> dict[str, Any]:
    """Precision funnel path: fetch recent papers, run 4-stage quality funnel."""
    from scholar_agent.engine.academic.arxiv_search import query_arxiv
    from scholar_agent.engine.academic.quality_funnel import QualityFunnel
    from scholar_agent.engine.paper_store import PaperStore
    from scholar_agent.engine.scholar_config import get_paper_db_path

    # Build merged funnel config: research_interests + precision_funnel settings
    funnel_config = {
        "research_domains": config.get("research_domains", {}),
        "excluded_keywords": config.get("excluded_keywords", []),
        "precision_funnel": precision_config,
    }

    # Fetch recent arXiv papers (7-day window) — collect categories from ALL domains
    all_cats: list[str] = []
    for dcfg in config.get("research_domains", {}).values():
        for c in dcfg.get("arxiv_categories", []):
            if c not in all_cats:
                all_cats.append(c)
    cats = all_cats or ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]

    now = target_date or datetime.now()
    start = now - timedelta(days=7)
    raw_papers = query_arxiv(cats, start, now, limit=200)

    # Filter already-analyzed papers before funnel
    skipped = 0
    if paper_notes_dir:
        existing_ids = get_analyzed_paper_ids(paper_notes_dir)
        if existing_ids:
            raw_papers, skipped = filter_already_analyzed(raw_papers, existing_ids)

    # Store papers in SQLite
    db_path = get_paper_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = PaperStore(db_path)
    store.initialize()
    try:
        for p in raw_papers:
            store.upsert_paper(p)

        # Run quality funnel — pass list directly (not None) to avoid loading stale papers
        funnel = QualityFunnel(store, funnel_config)
        result = funnel.run_daily(raw_papers)
    finally:
        store.close()

    papers = result.recommended
    for p in papers:
        p["track"] = "precision_funnel"

    return {
        "date": date_str,
        "papers": papers,
        "skipped": skipped,
        "total_found": result.stage_counts.get("input", 0),
        "dual_track": False,
        "precision_funnel": True,
        "funnel_stats": {
            "stage_counts": result.stage_counts,
            "llm_calls": result.llm_calls,
            "llm_tokens": result.llm_tokens,
            "duration_seconds": result.duration_seconds,
        },
    }


def _generate_single_track(
    config: dict[str, Any],
    paper_notes_dir: str,
    categories: list[str] | None,
    top_n: int,
    skip_existing: bool,
    target_date: datetime | None,
    date_str: str,
) -> dict[str, Any]:
    """Original single-track behavior (backward compatible)."""
    from scholar_agent.engine.academic.arxiv_search import search_and_score

    cats = categories or ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]

    result = search_and_score(
        config=config,
        categories=cats,
        target_date=target_date,
        max_results=200,
        top_n=top_n + 20,
        skip_hot=False,
    )

    papers = result.get("papers", [])
    total_found = result.get("total_found", len(papers))
    skipped = 0

    if skip_existing and paper_notes_dir:
        existing_ids = get_analyzed_paper_ids(paper_notes_dir)
        if existing_ids:
            papers, skipped = filter_already_analyzed(papers, existing_ids)

    papers = papers[:top_n]

    return {
        "date": date_str,
        "papers": papers,
        "skipped": skipped,
        "total_found": total_found,
        "dual_track": False,
    }


# ---------------------------------------------------------------------------
# Per-paper note generation for daily pipeline
# ---------------------------------------------------------------------------


def generate_paper_notes_for_daily(
    papers: list[dict[str, Any]],
    paper_notes_dir: str,
    language: str = "zh",
) -> dict[str, str]:
    """Generate skeleton paper notes for each recommended paper.

    Creates a full structured note in paper-notes/ for every paper that
    doesn't already have one, reusing the canonical ``generate_note()``
    from ``paper_analyzer``.  Returns a mapping of ``{title: stem}`` that
    callers can use to render ``[[wiki-links]]``.

    Args:
        papers: List of paper dicts (must have ``title``; ``arxiv_id``
            is used for dedup).
        paper_notes_dir: Path to the ``paper-notes/`` directory.
        language: ``"zh"`` or ``"en"``.

    Returns:
        Mapping of ``{paper_title: sanitize_title(title)}`` for all papers
        (including pre-existing ones) so callers always have the stem.
    """
    from scholar_agent.engine.academic.paper_analyzer import generate_note
    from scholar_agent.engine.common import sanitize_title

    existing_ids = get_analyzed_paper_ids(paper_notes_dir)

    stems: dict[str, str] = {}
    for p in papers:
        title = p.get("title", "")
        stem = sanitize_title(title)
        stems[title] = stem

        # Skip if already analyzed
        arxiv_id = p.get("arxiv_id") or p.get("paper_id") or ""
        normalized = re.sub(r"^arXiv:\s*", "", str(arxiv_id)).strip()
        if normalized and normalized in existing_ids:
            logger.debug("Skipping note generation for existing paper %s", arxiv_id)
            continue

        try:
            generate_note(p, paper_notes_dir, language=language)
            logger.info("Generated paper note for: %s", title)
        except Exception:
            logger.warning("Failed to generate note for: %s", title, exc_info=True)

    return stems


# ---------------------------------------------------------------------------
# Daily note builder
# ---------------------------------------------------------------------------


def build_daily_note(
    date_str: str,
    papers: list[dict[str, Any]],
    output_dir: str,
    language: str = "zh",
    tracks: dict[str, Any] | None = None,
    paper_note_stems: dict[str, str] | None = None,
    funnel_stats: dict[str, Any] | None = None,
    pipeline_stats: dict[str, Any] | None = None,
) -> str:
    """Generate a daily recommendation note.

    When *tracks* is provided, renders a dual-section layout.
    When *funnel_stats* is provided, renders the precision funnel layout.
    When *pipeline_stats* is provided, renders the unified pipeline layout.
    When *paper_note_stems* is provided, renders [[wiki-links]] to per-paper
    notes inside each paper block.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    filename = f"{date_str}-paper-recommendations.md" if language == "en" else f"{date_str}论文推荐.md"
    note_path = out / filename

    lines: list[str] = []

    # --- Frontmatter ---
    keywords: set[str] = set()
    for p in papers:
        for kw in p.get("domain_keywords", []):
            keywords.add(kw)
    kw_list = sorted(keywords)[:20]
    kw_yaml = ", ".join(json.dumps(kw) for kw in kw_list) if kw_list else ""

    track_names = []
    if tracks:
        track_names = list(tracks.keys())

    lines.append("---")
    lines.append(f"keywords: [{kw_yaml}]")
    lines.append('tags: ["llm-generated", "daily-paper-recommend"]')
    lines.append(f'date: "{date_str}"')
    if track_names:
        lines.append(f"tracks: {json.dumps(track_names)}")
    if funnel_stats:
        lines.append("precision_funnel: true")
    if pipeline_stats:
        lines.append("unified_pipeline: true")
    lines.append("---")
    lines.append("")

    # --- Title ---
    if language == "en":
        lines.append(f"# Paper Recommendations — {date_str}")
    else:
        lines.append(f"# 论文推荐 — {date_str}")
    lines.append("")

    # --- Body ---
    if pipeline_stats:
        _render_unified_section(lines, papers, language, paper_note_stems, pipeline_stats)
    elif funnel_stats:
        _render_precision_section(lines, papers, language, paper_note_stems, funnel_stats)
    elif tracks:
        _render_dual_sections(lines, papers, tracks, language, paper_note_stems)
    else:
        _render_flat_section(lines, papers, language, paper_note_stems)

    content = "\n".join(lines)
    note_path.write_text(content, encoding="utf-8")
    return str(note_path)


# ---------------------------------------------------------------------------
# Note rendering helpers
# ---------------------------------------------------------------------------


def _render_unified_section(
    lines: list[str],
    papers: list[dict[str, Any]],
    language: str,
    paper_note_stems: dict[str, str] | None = None,
    pipeline_stats: dict[str, Any] | None = None,
) -> None:
    """Render unified pipeline recommendation section."""
    ps = pipeline_stats or {}
    arxiv_count = ps.get("arxiv_fetched", 0)
    s2_count = ps.get("s2_fetched", 0)
    candidates = ps.get("candidates", 0)
    duration = ps.get("duration_seconds", 0)
    llm_calls = ps.get("llm_calls", 0)

    if language == "en":
        lines.append("## Today's Top Papers")
        lines.append("")
        lines.append(
            f"arXiv: {arxiv_count} + S2: {s2_count} → "
            f"Candidates: {candidates} → "
            f"**Recommended: {len(papers)}** "
            f"({duration:.1f}s, {llm_calls} LLM call{'s' if llm_calls != 1 else ''})"
        )
        lines.append("")
        lines.append(
            "<!-- LLM: Summarize the recommended papers: identify the key theme, highlight why each is worth reading -->"
        )
    else:
        lines.append("## 今日精选")
        lines.append("")
        lines.append(
            f"arXiv: {arxiv_count} + S2: {s2_count} → "
            f"候选: {candidates} 篇 → "
            f"**推荐: {len(papers)} 篇** "
            f"({duration:.1f}秒, {llm_calls} 次 LLM)"
        )
        lines.append("")
        lines.append("<!-- LLM: 总结推荐的论文：识别关键主题，说明每篇为什么值得精读 -->")
    lines.append("")

    if not papers:
        if language == "en":
            lines.append("*No papers met the quality bar today.*")
        else:
            lines.append("*今日没有论文通过质量筛选。*")
        lines.append("")
        return

    for p in papers:
        stem = (paper_note_stems or {}).get(p.get("title", ""), "")
        _render_paper_block(lines, p, language, is_top=True, paper_note_stem=stem)


def _render_precision_section(
    lines: list[str],
    papers: list[dict[str, Any]],
    language: str,
    paper_note_stems: dict[str, str] | None = None,
    funnel_stats: dict[str, Any] | None = None,
) -> None:
    """Render precision funnel recommendation section."""
    sc = (funnel_stats or {}).get("stage_counts", {})

    # Funnel overview
    if language == "en":
        lines.append("## Precision Funnel")
        lines.append("")
        lines.append(
            f"Input: {sc.get('input', 0)} → "
            f"Relevance: {sc.get('stage1_passed', 0)} → "
            f"Hard filter: {sc.get('stage2_passed', 0)} → "
            f"LLM review: {sc.get('stage3_passed', 0)} → "
            f"**Recommended: {len(papers)}**"
        )
        lines.append("")
        lines.append(
            "<!-- LLM: Summarize the recommended papers: identify the key theme, highlight why each is worth reading -->"
        )
    else:
        lines.append("## 精选推荐")
        lines.append("")
        lines.append(
            f"输入: {sc.get('input', 0)} → "
            f"相关性: {sc.get('stage1_passed', 0)} → "
            f"硬过滤: {sc.get('stage2_passed', 0)} → "
            f"LLM 审查: {sc.get('stage3_passed', 0)} → "
            f"**推荐: {len(papers)} 篇**"
        )
        lines.append("")
        lines.append("<!-- LLM: 总结推荐的论文：识别关键主题，说明每篇为什么值得精读 -->")
    lines.append("")

    if not papers:
        if language == "en":
            lines.append("*No papers met the quality bar today.*")
        else:
            lines.append("*今日没有论文通过质量筛选。*")
        lines.append("")
        return

    for p in papers:
        stem = (paper_note_stems or {}).get(p.get("title", ""), "")
        _render_paper_block(lines, p, language, is_top=True, paper_note_stem=stem)



def _render_dual_sections(
    lines: list[str],
    all_papers: list[dict[str, Any]],
    tracks: dict[str, Any],
    language: str,
    paper_note_stems: dict[str, str] | None = None,
) -> None:
    """Render two sections: conference picks + arXiv innovation."""
    # Overview
    if language == "en":
        lines.append("## Today's Overview")
        lines.append("")
        lines.append(
            "<!-- LLM: Summarize the 4 recommended papers: identify shared themes across conference and arXiv tracks, highlight complementary insights -->"
        )
    else:
        lines.append("## 今日概览")
        lines.append("")
        lines.append("<!-- LLM: 总结今日推荐的 4 篇论文：识别顶会和 arXiv 两条线索的共同主题，突出互补洞见 -->")
    lines.append("")

    # Section 1: Conference
    conf_papers = tracks.get("conference", {}).get("papers", [])
    if language == "en":
        lines.append("## Top Conference Picks")
    else:
        lines.append("## 顶会精选")
    lines.append("")
    if conf_papers:
        for p in conf_papers:
            stem = (paper_note_stems or {}).get(p.get("title", ""), "")
            _render_paper_block(lines, p, language, is_top=True, paper_note_stem=stem)
    else:
        lines.append("<!-- No conference recommendations today. -->")

    # Section 2: arXiv Innovation
    arxiv_papers = tracks.get("arxiv_innovation", {}).get("papers", [])
    if language == "en":
        lines.append("## arXiv Innovation")
    else:
        lines.append("## 前沿速递")
    lines.append("")
    if arxiv_papers:
        for p in arxiv_papers:
            stem = (paper_note_stems or {}).get(p.get("title", ""), "")
            _render_paper_block(lines, p, language, is_top=True, paper_note_stem=stem)
    else:
        lines.append("<!-- No arXiv innovation recommendations today. -->")

    # Section 3: Cross-track insights
    if language == "en":
        lines.append("## Cross-Track Insights")
        lines.append("")
        lines.append(
            "<!-- LLM: Compare the conference and arXiv papers above. Identify shared themes, complementary insights, and suggest a reading order. -->"
        )
    else:
        lines.append("## 综合建议")
        lines.append("")
        lines.append("<!-- LLM: 对比以上顶会和 arXiv 论文，找出共同主题、互补洞见，给出推荐阅读顺序。 -->")


def _render_flat_section(
    lines: list[str],
    papers: list[dict[str, Any]],
    language: str,
    paper_note_stems: dict[str, str] | None = None,
) -> None:
    """Render original flat list of papers."""
    if language == "en":
        lines.append("## Today's Overview")
        lines.append("")
        lines.append(f"<!-- LLM: Summarize the {len(papers)} recommended papers -->")
    else:
        lines.append("## 今日概览")
        lines.append("")
        lines.append(f"<!-- LLM: 总结今日推荐的 {len(papers)} 篇论文 -->")
    lines.append("")

    for i, p in enumerate(papers):
        stem = (paper_note_stems or {}).get(p.get("title", ""), "")
        _render_paper_block(lines, p, language, is_top=(i < 3), paper_note_stem=stem)


def _render_paper_block(
    lines: list[str],
    p: dict[str, Any],
    language: str,
    is_top: bool = True,
    paper_note_stem: str = "",
) -> None:
    """Render a single paper entry."""
    title = p.get("title", "Untitled")
    authors = p.get("authors", "")
    if isinstance(authors, list):
        authors = ", ".join(str(a) for a in authors[:5])
    arxiv_id = p.get("arxiv_id", "")
    domain = p.get("best_domain", "")
    impact = p.get("_impact_score")
    innovation = p.get("_innovation_final_score")
    llm_comment = p.get("_llm_comment", "")

    lines.append(f"### {title}")
    lines.append("")

    # Wiki-link to per-paper note in paper-notes/
    if paper_note_stem:
        if language == "en":
            lines.append(f"> Paper note: [[{paper_note_stem}]]")
        else:
            lines.append(f"> 论文笔记：[[{paper_note_stem}]]")
        lines.append("")

    if language == "en":
        lines.append(f"- **Authors**: {authors}")
        if domain:
            lines.append(f"- **Domain**: {domain}")
        if impact is not None:
            lines.append(f"- **Impact Score**: {impact:.1f}")
        if innovation is not None:
            lines.append(f"- **Innovation Score**: {innovation:.2f}")
        if arxiv_id:
            lines.append(
                f"- **Links**: [arXiv](https://arxiv.org/abs/{arxiv_id}) | [PDF](https://arxiv.org/pdf/{arxiv_id})"
            )
    else:
        lines.append(f"- **作者**：{authors}")
        if domain:
            lines.append(f"- **领域**：{domain}")
        if impact is not None:
            lines.append(f"- **影响力**：{impact:.1f}")
        if innovation is not None:
            lines.append(f"- **创新性**：{innovation:.2f}")
        if arxiv_id:
            lines.append(
                f"- **链接**：[arXiv](https://arxiv.org/abs/{arxiv_id}) | [PDF](https://arxiv.org/pdf/{arxiv_id})"
            )

    lines.append("")

    # Precision funnel recommendation reason
    rec_reason = p.get("recommendation_reason", "")
    if rec_reason:
        if language == "en":
            lines.append(f"- **Why recommended**: {rec_reason}")
        else:
            lines.append(f"- **推荐理由**：{rec_reason}")

    # Precision funnel LLM scores
    llm_novelty = p.get("llm_novelty")
    llm_credibility = p.get("llm_credibility")
    llm_depth = p.get("llm_depth")
    llm_rigor = p.get("llm_rigor")
    if any(v is not None for v in (llm_novelty, llm_credibility, llm_depth, llm_rigor)):
        if language == "en":
            parts = []
            if llm_novelty is not None:
                parts.append(f"novelty={llm_novelty}")
            if llm_credibility is not None:
                parts.append(f"credibility={llm_credibility}")
            if llm_depth is not None:
                parts.append(f"depth={llm_depth}")
            if llm_rigor is not None:
                parts.append(f"rigor={llm_rigor}")
            lines.append(f"- **LLM Scores**: {', '.join(parts)}")
        else:
            parts = []
            if llm_novelty is not None:
                parts.append(f"新颖性={llm_novelty}")
            if llm_credibility is not None:
                parts.append(f"可信度={llm_credibility}")
            if llm_depth is not None:
                parts.append(f"深度={llm_depth}")
            if llm_rigor is not None:
                parts.append(f"严谨性={llm_rigor}")
            lines.append(f"- **LLM 评分**：{', '.join(parts)}")

    if is_top:
        if language == "en":
            lines.append(f"<!-- TOP: Call extract_paper_images and analyze_paper for '{arxiv_id or title}' -->")
            lines.append("")
            lines.append("<!-- LLM: Write a one-line summary and 3 core contributions based on the abstract -->")
        else:
            lines.append(f"<!-- TOP: 请对 '{arxiv_id or title}' 调用 extract_paper_images 和 analyze_paper -->")
            lines.append("")
            lines.append("<!-- LLM: 写一句话总结和3个核心贡献（基于摘要） -->")

    if llm_comment:
        tag = "LLM评语" if language == "zh" else "LLM Comment"
        lines.append(f"- **{tag}**：{llm_comment}")

    lines.append("")
    lines.append("---")
    lines.append("")
