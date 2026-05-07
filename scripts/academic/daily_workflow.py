"""Daily paper recommendation workflow — dual-track edition.

Provides:
  - get_analyzed_paper_ids: scan paper-notes/ for already-analyzed papers
  - filter_already_analyzed: remove already-analyzed papers from a list
  - generate_daily_recommendations: dual-track (conference + arXiv) pipeline
  - build_daily_note: generate a daily recommendation markdown note
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

import sys
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from common import parse_frontmatter


# ---------------------------------------------------------------------------
# Already-read dedup
# ---------------------------------------------------------------------------

def get_analyzed_paper_ids(paper_notes_dir: str) -> set[str]:
    """Scan paper-notes/ for already-analyzed arxiv IDs."""
    notes_path = Path(paper_notes_dir)
    if not notes_path.exists():
        return set()

    ids: set[str] = set()
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
    from academic.conf_search import search_conferences_multi_year

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
    from academic.arxiv_search import query_arxiv
    from academic.innovation_scorer import innovation_pre_filter, innovation_llm_batch_score

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
) -> dict[str, Any]:
    """Dual-track search + dedup + score -> return recommended papers.

    When *dual_track* is True (default):
      - Track 1: 2 conference papers (impact-ranked)
      - Track 2: 2 arXiv innovation papers (heuristic + LLM)

    When False, falls back to the original single-track behavior.
    """
    date_str = (target_date or datetime.now()).strftime("%Y-%m-%d")

    if not dual_track:
        return _generate_single_track(
            config, paper_notes_dir, categories, top_n, skip_existing, target_date, date_str,
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
    from academic.arxiv_search import search_and_score

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
# Daily note builder
# ---------------------------------------------------------------------------

def build_daily_note(
    date_str: str,
    papers: list[dict[str, Any]],
    output_dir: str,
    language: str = "zh",
    tracks: dict[str, Any] | None = None,
) -> str:
    """Generate a daily recommendation note.

    When *tracks* is provided, renders a dual-section layout.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    filename = (
        f"{date_str}-paper-recommendations.md"
        if language == "en"
        else f"{date_str}论文推荐.md"
    )
    note_path = out / filename

    lines: list[str] = []

    # --- Frontmatter ---
    keywords: set[str] = set()
    for p in papers:
        for kw in p.get("domain_keywords", []):
            keywords.add(kw)
    kw_yaml = ", ".join(sorted(keywords)[:20]) if keywords else ""

    track_names = []
    if tracks:
        track_names = list(tracks.keys())

    lines.append("---")
    lines.append(f'keywords: [{kw_yaml}]')
    lines.append('tags: ["llm-generated", "daily-paper-recommend"]')
    lines.append(f'date: "{date_str}"')
    if track_names:
        lines.append(f'tracks: {json.dumps(track_names)}')
    lines.append("---")
    lines.append("")

    # --- Title ---
    if language == "en":
        lines.append(f"# Paper Recommendations — {date_str}")
    else:
        lines.append(f"# 论文推荐 — {date_str}")
    lines.append("")

    # --- Body ---
    if tracks:
        _render_dual_sections(lines, papers, tracks, language)
    else:
        _render_flat_section(lines, papers, language)

    content = "\n".join(lines)
    note_path.write_text(content, encoding="utf-8")
    return str(note_path)


# ---------------------------------------------------------------------------
# Note rendering helpers
# ---------------------------------------------------------------------------

def _render_dual_sections(
    lines: list[str],
    all_papers: list[dict[str, Any]],
    tracks: dict[str, Any],
    language: str,
) -> None:
    """Render two sections: conference picks + arXiv innovation."""
    # Overview
    if language == "en":
        lines.append("## Today's Overview")
        lines.append("")
        lines.append("<!-- LLM: Summarize the 4 recommended papers: identify shared themes across conference and arXiv tracks, highlight complementary insights -->")
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
            _render_paper_block(lines, p, language, is_top=True)
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
            _render_paper_block(lines, p, language, is_top=True)
    else:
        lines.append("<!-- No arXiv innovation recommendations today. -->")

    # Section 3: Cross-track insights
    if language == "en":
        lines.append("## Cross-Track Insights")
        lines.append("")
        lines.append("<!-- LLM: Compare the conference and arXiv papers above. Identify shared themes, complementary insights, and suggest a reading order. -->")
    else:
        lines.append("## 综合建议")
        lines.append("")
        lines.append("<!-- LLM: 对比以上顶会和 arXiv 论文，找出共同主题、互补洞见，给出推荐阅读顺序。 -->")


def _render_flat_section(
    lines: list[str],
    papers: list[dict[str, Any]],
    language: str,
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
        _render_paper_block(lines, p, language, is_top=(i < 3))


def _render_paper_block(
    lines: list[str],
    p: dict[str, Any],
    language: str,
    is_top: bool = True,
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
    track = p.get("track", "")

    lines.append(f"### {title}")
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
            lines.append(f"- **Links**: [arXiv](https://arxiv.org/abs/{arxiv_id}) | [PDF](https://arxiv.org/pdf/{arxiv_id})")
    else:
        lines.append(f"- **作者**：{authors}")
        if domain:
            lines.append(f"- **领域**：{domain}")
        if impact is not None:
            lines.append(f"- **影响力**：{impact:.1f}")
        if innovation is not None:
            lines.append(f"- **创新性**：{innovation:.2f}")
        if arxiv_id:
            lines.append(f"- **链接**：[arXiv](https://arxiv.org/abs/{arxiv_id}) | [PDF](https://arxiv.org/pdf/{arxiv_id})")

    lines.append("")

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
