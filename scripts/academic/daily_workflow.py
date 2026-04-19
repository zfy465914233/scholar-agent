"""Daily paper recommendation workflow.

Provides:
  - get_analyzed_paper_ids: scan paper-notes/ for already-analyzed papers
  - filter_already_analyzed: remove already-analyzed papers from a list
  - generate_daily_recommendations: search + dedup + score pipeline
  - build_daily_note: generate a daily recommendation markdown note
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Allow importing common from parent scripts/ directory
import sys
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from common import parse_frontmatter


# ---------------------------------------------------------------------------
# Gap 6: Already-read dedup
# ---------------------------------------------------------------------------

def get_analyzed_paper_ids(paper_notes_dir: str) -> set[str]:
    """Scan paper-notes/ for already-analyzed arxiv IDs.

    Reads frontmatter ``paper_id`` field from all .md files.
    Returns a set of normalized arxiv IDs (e.g. '2401.12345').
    """
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
            # Normalize: strip 'arXiv:' prefix if present
            normalized = re.sub(r"^arXiv:\s*", "", str(paper_id)).strip()
            if normalized:
                ids.add(normalized)
    return ids


def filter_already_analyzed(
    papers: list[dict[str, Any]],
    existing_ids: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """Filter out already-analyzed papers.

    Returns (remaining_papers, filtered_count).
    """
    remaining = []
    for p in papers:
        arxiv_id = p.get("arxiv_id") or p.get("paper_id") or ""
        normalized = re.sub(r"^arXiv:\s*", "", str(arxiv_id)).strip()
        if normalized and normalized in existing_ids:
            continue
        remaining.append(p)
    return remaining, len(papers) - len(remaining)


# ---------------------------------------------------------------------------
# Gap 2: Daily recommendation workflow
# ---------------------------------------------------------------------------

def generate_daily_recommendations(
    config: dict[str, Any],
    paper_notes_dir: str,
    categories: list[str] | None = None,
    top_n: int = 10,
    skip_existing: bool = True,
    target_date: datetime | None = None,
) -> dict[str, Any]:
    """Search + dedup + score -> return recommended papers.

    Args:
        config: Research interests config with 'research_domains' and
            'excluded_keywords'.
        paper_notes_dir: Directory of existing paper notes for dedup.
        categories: arXiv categories to search.
        top_n: Number of top papers to return.
        skip_existing: Whether to filter out already-analyzed papers.
        target_date: Target date for the search window.

    Returns:
        Dict with 'date', 'papers', 'skipped', 'total_found'.
    """
    from academic.arxiv_search import search_and_score

    cats = categories or ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]

    # Search and score
    result = search_and_score(
        config=config,
        categories=cats,
        target_date=target_date,
        max_results=200,
        top_n=top_n + 20,  # fetch extra to compensate for dedup filtering
        skip_hot=False,
    )

    papers = result.get("papers", [])
    total_found = result.get("total_found", len(papers))
    skipped = 0

    # Dedup against existing notes
    if skip_existing and paper_notes_dir:
        existing_ids = get_analyzed_paper_ids(paper_notes_dir)
        if existing_ids:
            papers, skipped = filter_already_analyzed(papers, existing_ids)

    # Trim to top_n
    papers = papers[:top_n]

    date_str = (target_date or datetime.now()).strftime("%Y-%m-%d")

    return {
        "date": date_str,
        "papers": papers,
        "skipped": skipped,
        "total_found": total_found,
    }


def build_daily_note(
    date_str: str,
    papers: list[dict[str, Any]],
    output_dir: str,
    language: str = "zh",
) -> str:
    """Generate a daily recommendation note (skeleton).

    Returns the path to the generated note file.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if language == "en":
        filename = f"{date_str}-paper-recommendations.md"
    else:
        filename = f"{date_str}论文推荐.md"

    note_path = out / filename

    # Build note content
    lines: list[str] = []

    # Frontmatter
    keywords = set()
    for p in papers:
        for kw in p.get("matched_keywords", []):
            keywords.add(kw)
    kw_yaml = ", ".join(sorted(keywords)[:20]) if keywords else ""

    lines.append("---")
    lines.append(f'keywords: [{kw_yaml}]')
    lines.append('tags: ["llm-generated", "daily-paper-recommend"]')
    lines.append(f'date: "{date_str}"')
    lines.append("---")
    lines.append("")

    # Title
    if language == "en":
        lines.append(f"# Paper Recommendations — {date_str}")
    else:
        lines.append(f"# 论文推荐 — {date_str}")
    lines.append("")

    # Overview placeholder
    if language == "en":
        lines.append("## Today's Overview")
        lines.append("")
        lines.append(f"<!-- LLM: Summarize the {len(papers)} recommended papers: main research directions, overall trends, quality distribution, reading suggestions -->")
    else:
        lines.append("## 今日概览")
        lines.append("")
        lines.append(f"<!-- LLM: 总结今日推荐的 {len(papers)} 篇论文：主要研究方向、总体趋势、质量分布、阅读建议 -->")
    lines.append("")

    # Paper list
    for i, p in enumerate(papers):
        title = p.get("title", "Untitled")
        authors = p.get("authors", "")
        if isinstance(authors, list):
            authors = ", ".join(str(a) for a in authors[:5])
        arxiv_id = p.get("arxiv_id", "")
        score = p.get("scores", {}).get("recommendation", 0)
        domain = p.get("matched_domain", "")

        lines.append(f"### {title}")
        lines.append("")

        if language == "en":
            lines.append(f"- **Authors**: {authors}")
            lines.append(f"- **Domain**: {domain}")
            lines.append(f"- **Score**: {score:.1f}")
            if arxiv_id:
                lines.append(f"- **Links**: [arXiv](https://arxiv.org/abs/{arxiv_id}) | [PDF](https://arxiv.org/pdf/{arxiv_id})")
        else:
            lines.append(f"- **作者**：{authors}")
            lines.append(f"- **领域**：{domain}")
            lines.append(f"- **评分**：{score:.1f}")
            if arxiv_id:
                lines.append(f"- **链接**：[arXiv](https://arxiv.org/abs/{arxiv_id}) | [PDF](https://arxiv.org/pdf/{arxiv_id})")

        lines.append("")

        # Top 3 marker
        if i < 3:
            if language == "en":
                lines.append(f"<!-- TOP3: Call extract_paper_images and analyze_paper for '{arxiv_id or title}' -->")
                lines.append("")
                lines.append("<!-- LLM: Write a one-line summary and 3 core contributions based on the abstract -->")
            else:
                lines.append(f"<!-- TOP3: 请对 '{arxiv_id or title}' 调用 extract_paper_images 和 analyze_paper -->")
                lines.append("")
                lines.append("<!-- LLM: 写一句话总结和3个核心贡献（基于摘要） -->")
        else:
            if language == "en":
                lines.append("<!-- LLM: Write a one-line summary based on the abstract -->")
            else:
                lines.append("<!-- LLM: 写一句话总结（基于摘要） -->")

        lines.append("")
        lines.append("---")
        lines.append("")

    content = "\n".join(lines)
    note_path.write_text(content, encoding="utf-8")
    return str(note_path)
