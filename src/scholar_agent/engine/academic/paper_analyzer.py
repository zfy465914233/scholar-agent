"""Paper analysis note generator for Obsidian-style knowledge bases.

Generates structured markdown notes with frontmatter for research papers,
supporting both Chinese and English deep-analysis templates with
``<!-- LLM: ... -->`` placeholders for LLM-assisted completion.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from scholar_agent.engine.common import atomic_write_text, sanitize_title
from scholar_agent.engine.llm_client import chat_with_fallback, resolve_providers
from scholar_agent.validation.validate_note import (
    SECTION_ALIASES,
    UNKNOWN_VALUES,
    _has_prose_paragraph,
    extract_sections,
    find_section,
)

logger = logging.getLogger(__name__)

# Backward-compatible alias used by note_linker.py
title_to_filename = sanitize_title

# ---------------------------------------------------------------------------
# Math depth detection
# ---------------------------------------------------------------------------

_MATH_HEAVY_DOMAINS = {
    "运筹优化",
    "运筹优化与库存规划",
    "库存规划",
    "供应链优化",
    "供应链",
    "supply-chain",
    "newsvendor",
    "统计推断",
    "概率论",
    "信息论",
    "控制论",
    "优化理论",
    "计量经济学",
    "数学物理",
    "博弈论",
    "quantitative-finance",
    "量化金融",
    "operations-research",
    "optimization",
    "control-theory",
    "statistics",
    "probability",
    "information-theory",
    "econometrics",
    "mathematical-physics",
    "game-theory",
    "bayesian",
    "reinforcement-learning",
}

_MATH_HEAVY_KEYWORDS = re.compile(
    r"(?:derivation|推导|proof|证明|theorem|定理|lemma|引理|proposition|"
    r"命题|corollary|推论|optimality|最优|convergence|收敛|"
    r"convex|凸|bound|上界|下界|gradient|梯度|"
    r"Lagrangian|拉格朗日|KKT|Bellman|贝尔曼|"
    r"posterior|后验|prior|先验|likelihood|似然|"
    r"expectation|期望|variance|方差|estimator|估计量|"
    r"minimiza|maximiza|minimize|maximize|"
    r"objective function|目标函数|loss function|损失函数|"
    r"closed.form|解析解|analytical solution)",
    re.IGNORECASE,
)

_LATEX_MARKERS = re.compile(
    r"(?:\$\$.*?\$\$|\$[^$]+\$|\\begin\{equation|\\end\{equation|"
    r"\\frac\{|\\sum_|\\int_|\\prod_|\\mathbb\{|\\mathcal\{|\\boldsymbol)",
    re.DOTALL,
)


def detect_math_depth(abstract: str, domain: str, pdf_text: str = "") -> str:
    """Detect whether a paper needs heavy, light, or no math treatment.

    Returns one of: "heavy", "light", "none".
    """
    text = f"{abstract} {pdf_text[:2000]}"

    domain_match = any(kw in domain.lower() for kw in _MATH_HEAVY_DOMAINS)

    keyword_hits = len(_MATH_HEAVY_KEYWORDS.findall(text))
    latex_hits = len(_LATEX_MARKERS.findall(text))

    if domain_match and (keyword_hits >= 3 or latex_hits >= 2):
        return "heavy"
    if keyword_hits >= 2 or latex_hits >= 1:
        return "light"
    if domain_match:
        return "light"
    return "none"


# Paper-type signals for detect_paper_type (pure rules, no LLM).
_PAPER_TYPE_SURVEY_KEYWORDS = re.compile(
    r"(?:survey|综述|taxonomy|分类|a survey of|文献综述|进展与展望)",
    re.IGNORECASE,
)
_PAPER_TYPE_BENCHMARK_KEYWORDS = re.compile(
    r"(?:benchmark|leaderboard|基准|评测基准|evaluation suite)",
    re.IGNORECASE,
)
_PAPER_TYPE_EMPIRICAL_KEYWORDS = re.compile(
    r"(?:dataset|experiment|ablation|baseline|数据集|实验|消融|基线|accuracy|准确率)",
    re.IGNORECASE,
)


def detect_paper_type(abstract: str, title: str, domain: str = "", pdf_text: str = "") -> str:
    """Infer paper type for type_specific validation. Pure rules (no LLM).

    Returns one of: "survey", "benchmark", "theory", "empirical", "generic".
    Priority: survey/benchmark (distinctive keywords) > theory (math-heavy) >
    empirical (dataset/experiments) > generic fallback.
    """
    text = f"{title} {abstract} {pdf_text[:2000]}"
    if _PAPER_TYPE_SURVEY_KEYWORDS.search(text):
        return "survey"
    if _PAPER_TYPE_BENCHMARK_KEYWORDS.search(text):
        return "benchmark"
    if len(_MATH_HEAVY_KEYWORDS.findall(text)) >= 3 or len(_LATEX_MARKERS.findall(text)) >= 2:
        return "theory"
    if _PAPER_TYPE_EMPIRICAL_KEYWORDS.search(text):
        return "empirical"
    return "generic"


def _yaml_escape(s: str) -> str:
    """Escape a string for safe embedding in YAML double-quoted values."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def _format_image_refs(images: list[dict[str, Any]] | None, section: str) -> str:
    """Format image references for a given section.

    Args:
        images: List of dicts with 'filename', 'caption', 'section' keys.
        section: Which section to filter by (e.g. 'framework', 'results').

    Returns:
        Markdown image embed lines, or empty string.
    """
    if not images:
        return ""
    relevant = [img for img in images if img.get("section", "") == section]
    if not relevant:
        return ""
    lines = []
    for img in relevant:
        fname = img.get("filename", "")
        caption = img.get("caption", "")
        if fname:
            lines.append(f"![[images/{fname}|800]]")
            if caption:
                lines.append(f"> {caption}")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Template sections — loaded from external .md files
# ---------------------------------------------------------------------------


def _load_sections():
    from scholar_agent.templates import load_en_sections, load_zh_sections

    return load_zh_sections(), load_en_sections()


_sections_cache: tuple[dict, dict] | None = None


def _get_sections() -> tuple[dict, dict]:
    global _sections_cache
    if _sections_cache is None:
        _sections_cache = _load_sections()
    return _sections_cache


# ---------------------------------------------------------------------------
# Note generators
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Localised strings for note generation
# ---------------------------------------------------------------------------

_STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        "default_tag": "论文笔记",
        "core_heading": "## 核心信息",
        "label_paper_id": "**论文ID**",
        "label_authors": "**作者**",
        "label_affiliation": "**机构**",
        "label_pub_date": "**发布时间**",
        "label_conference": "**会议/期刊**",
        "label_domain": "**领域**",
        "label_score": "**评分**",
        "label_links": "**链接**",
        "affiliation_joiner": "、",
        "label_sep": "：",
        "affiliation_placeholder": "<!-- LLM: 从论文中提取作者机构信息 -->",
        "links_placeholder": "<!-- LLM: 补充论文链接 -->",
        "conference_placeholder": "<!-- LLM: 从 categories 或论文信息推断 -->",
        "abstract_placeholder": "<!-- LLM: 请从论文中提取英文摘要 -->",
        "abstract_template_key": "abstract_translation",
        "notes_heading": "## 我的笔记",
        "notes_comment": "<!-- 在此记录个人想法、灵感、与自己研究的关联 -->",
        "related_heading": "## 相关论文",
        "related_placeholder": "<!-- LLM: 根据研究主题，链接知识库中的相关论文笔记 -->",
        "resources_heading": "## 外部资源",
        "local_pdf_label": "本地PDF",
        "resources_placeholder": "<!-- LLM: 补充代码仓库、数据集、项目主页等链接 -->",
        # Math instructions (3 levels x core/details)
        "math_heavy_core": (
            "<!-- LLM: 用通俗语言（1-2段）概括方法的核心创新。"
            "在通俗解释之后，**必须**给出核心数学公式的直觉解释，"
            "用 $...$ 行内 LaTeX 引用关键符号。不要跳过数学本质。 -->"
        ),
        "math_heavy_details": (
            "<!-- LLM: 对每个核心模块分别描述：\n"
            "#### 模块1：[名称]\n"
            "- **功能**：[该模块的作用]\n"
            "- **输入/输出**：[数据流]\n"
            "- **关键技术**：[使用的技术或算法]\n"
            "- **数学公式（必须）**：用 LaTeX 完整写出该模块涉及的核心公式。"
            " $...$ 行内，$$...$$ 块级。必须包含符号定义和推导思路。\n\n"
            "#### 模块2：[名称]\n"
            "...（以此类推，每个含数学的模块都必须有公式）\n"
            "-->\n\n"
            "### 符号定义\n\n"
            "<!-- LLM: 用表格统一列出所有核心数学符号：\n"
            "| 符号 | 含义 | 定义域/约束 |\n"
            "|:--|:--|:--|\n"
            "| $\\alpha$ | 学习率 | $\\alpha > 0$ |\n"
            "| ... | ... | ... |\n"
            "-->"
        ),
        "math_light_core": (
            "<!-- LLM: 用通俗语言（1-2段）概括方法的核心创新，在关键处用 $...$ 行内 LaTeX 标注核心公式 -->"
        ),
        "math_light_details": (
            "<!-- LLM: 对每个核心模块分别描述：\n"
            "#### 模块1：[名称]\n"
            "- **功能**：[该模块的作用]\n"
            "- **输入/输出**：[数据流]\n"
            "- **关键技术**：[使用的技术或算法]\n"
            "- **数学公式**：如有，用 LaTeX：$...$ 行内，$$...$$ 块级\n\n"
            "#### 模块2：[名称]\n"
            "...（以此类推）\n"
            "-->"
        ),
        "math_none_core": "<!-- LLM: 用通俗语言（1-2段）概括方法的核心创新 -->",
        "math_none_details": (
            "<!-- LLM: 对每个核心模块分别描述：\n"
            "#### 模块1：[名称]\n"
            "- **功能**：[该模块的作用]\n"
            "- **输入/输出**：[数据流]\n"
            "- **关键技术**：[使用的技术或算法]\n\n"
            "#### 模块2：[名称]\n"
            "...（以此类推）\n"
            "-->"
        ),
    },
    "en": {
        "default_tag": "paper-notes",
        "core_heading": "## Core Information",
        "label_paper_id": "**Paper ID**",
        "label_authors": "**Authors**",
        "label_affiliation": "**Affiliation**",
        "label_pub_date": "**Publication Date**",
        "label_conference": "**Conference/Journal**",
        "label_domain": "**Domain**",
        "label_score": "**Score**",
        "label_links": "**Links**",
        "affiliation_joiner": ", ",
        "label_sep": ": ",
        "affiliation_placeholder": "<!-- LLM: Extract author affiliations from the paper -->",
        "links_placeholder": "<!-- LLM: Add paper links -->",
        "conference_placeholder": "<!-- LLM: Infer from categories or paper info -->",
        "abstract_placeholder": "<!-- LLM: Extract the abstract from the paper -->",
        "abstract_template_key": "abstract_analysis",
        "notes_heading": "## My Notes",
        "notes_comment": "<!-- Record personal thoughts, insights, connections to your own research -->",
        "related_heading": "## Related Papers",
        "related_placeholder": "<!-- LLM: Link to related paper notes in the knowledge base -->",
        "resources_heading": "## External Resources",
        "local_pdf_label": "Local PDF",
        "resources_placeholder": "<!-- LLM: Add code repo, dataset, project page links -->",
        "math_heavy_core": (
            "<!-- LLM: Explain the core innovation in plain language (1-2 paragraphs). "
            "After the intuitive explanation, you MUST provide the intuition behind "
            "the core mathematical formulas, using $...$ inline LaTeX for key symbols. "
            "Do not skip the mathematical essence. -->"
        ),
        "math_heavy_details": (
            "<!-- LLM: For each core module:\n"
            "#### Module 1: [Name]\n"
            "- **Function**: [what it does]\n"
            "- **Input/Output**: [data flow]\n"
            "- **Key Techniques**: [algorithms or techniques used]\n"
            "- **Math (REQUIRED)**: Write the core formulas in LaTeX — $...$ inline, "
            "$$...$$ block. Must include symbol definitions and derivation logic.\n\n"
            "#### Module 2: [Name]\n"
            "...(and so on — every math-heavy module must include formulas)\n"
            "-->\n\n"
            "### Symbol Definitions\n\n"
            "<!-- LLM: List all core mathematical symbols in a table:\n"
            "| Symbol | Meaning | Domain/Constraint |\n"
            "|:--|:--|:--|\n"
            "| $\\alpha$ | Learning rate | $\\alpha > 0$ |\n"
            "| ... | ... | ... |\n"
            "-->"
        ),
        "math_light_core": (
            "<!-- LLM: Explain the core innovation in plain language (1-2 paragraphs), "
            "annotating key formulas with $...$ inline LaTeX where appropriate -->"
        ),
        "math_light_details": (
            "<!-- LLM: For each core module:\n"
            "#### Module 1: [Name]\n"
            "- **Function**: [what it does]\n"
            "- **Input/Output**: [data flow]\n"
            "- **Key Techniques**: [algorithms or techniques used]\n"
            "- **Math** (if any): Use LaTeX — $...$ inline, $$...$$ block\n\n"
            "#### Module 2: [Name]\n"
            "...(and so on)\n"
            "-->"
        ),
        "math_none_core": "<!-- LLM: Explain the core innovation in plain language (1-2 paragraphs) -->",
        "math_none_details": (
            "<!-- LLM: For each core module:\n"
            "#### Module 1: [Name]\n"
            "- **Function**: [what it does]\n"
            "- **Input/Output**: [data flow]\n"
            "- **Key Techniques**: [algorithms or techniques used]\n\n"
            "#### Module 2: [Name]\n"
            "...(and so on)\n"
            "-->"
        ),
    },
}

# Unified domain→tags covering both zh and en domain names
_DOMAIN_TAGS: dict[str, list[str]] = {
    "LLM与Agent": ["LLM", "Agent", "大模型"],
    "LLM & Agents": ["LLM", "Autonomous-Agent"],
    "LLM": ["LLM", "Large-Language-Model"],
    "多模态": ["多模态", "Multimodal", "VLM"],
    "Multimodal": ["Multimodal", "VLM"],
    "Agent": ["Agent", "Autonomous-Agent"],
    "运筹优化与库存规划": ["运筹优化", "库存规划", "供应链"],
}


# ---------------------------------------------------------------------------
# Note generator (unified)
# ---------------------------------------------------------------------------


def _generate_note_body(
    paper_id: str,
    title: str,
    authors: str,
    domain: str,
    date: str,
    scores: dict[str, float] | None = None,
    abstract: str = "",
    arxiv_id: str = "",
    affiliations: list[str] | None = None,
    conference: str = "",
    pdf_url: str = "",
    related_papers: list[str] | None = None,
    images: list[dict[str, Any]] | None = None,
    local_pdf_rel: str = "",
    math_depth: str = "none",
    language: str = "zh",
) -> str:
    """Generate a deep-analysis markdown note (Chinese or English)."""
    s = _STRINGS[language]

    # --- Tags ---
    tags = [s["default_tag"], *_DOMAIN_TAGS.get(domain, [domain])]
    tags_yaml = "\n".join(f"  - {tag}" for tag in tags)

    score_str = f"{scores.get('recommendation', 0):.1f}/10" if scores else "[SCORE]/10"
    _rps = related_papers or []
    related_yaml = "\n" + "\n".join(f'  - "{rp}"' for rp in _rps) if _rps else " []"
    affil_str = s["affiliation_joiner"].join(affiliations[:3]) if affiliations else s["affiliation_placeholder"]

    # --- Links ---
    links = f"[arXiv](https://arxiv.org/abs/{arxiv_id})" if arxiv_id else ""
    if local_pdf_rel:
        links += f" | [PDF]({local_pdf_rel})" if links else f"[PDF]({local_pdf_rel})"
    elif pdf_url:
        links += f" | [PDF]({pdf_url})" if links else f"[PDF]({pdf_url})"
    elif arxiv_id:
        links += f" | [PDF](https://arxiv.org/pdf/{arxiv_id})"
    if not links:
        links = s["links_placeholder"]

    # --- Image refs ---
    framework_imgs = _format_image_refs(images, "framework")
    results_imgs = _format_image_refs(images, "results")

    # --- Paper type (written to frontmatter; validate_note reads it to enable
    # type_specific checks). Inferred by pure rules, no LLM cost. ---
    paper_type = detect_paper_type(abstract or "", title, domain)

    # --- Math instructions ---
    math_instruction_core = s[f"math_{math_depth}_core"]
    math_instruction_details = s[f"math_{math_depth}_details"]

    # --- Build note ---
    parts: list[str] = []

    # Frontmatter
    parts.append(f'''---
title: "{_yaml_escape(title)}"
paper_id: "{paper_id}"
authors: "{_yaml_escape(authors)}"
domain: "{domain}"
date: "{date}"
status: skeleton
math_depth: "{math_depth}"
paper_type: "{paper_type}"
tags:
{tags_yaml}
related_papers:{related_yaml}
quality_score: "{score_str}"
created: "{date}"
updated: "{date}"
---''')

    # Title
    parts.append(f"\n# {title}\n")

    # Core info
    parts.append(f"""\
{s["core_heading"]}
- {s["label_paper_id"]}{s["label_sep"]}{paper_id}
- {s["label_authors"]}{s["label_sep"]}{authors}
- {s["label_affiliation"]}{s["label_sep"]}{affil_str}
- {s["label_pub_date"]}{s["label_sep"]}{date}
- {s["label_conference"]}{s["label_sep"]}{conference or s["conference_placeholder"]}
- {s["label_domain"]}{s["label_sep"]}{domain}
- {s["label_score"]}{s["label_sep"]}{score_str}
- {s["label_links"]}{s["label_sep"]}{links}
""")

    # Template sections
    zh_sect, en_sect = _get_sections()
    sections = zh_sect if language == "zh" else en_sect
    abstract_key = s["abstract_template_key"]
    parts.append(
        sections[abstract_key].format(
            abstract=abstract or s["abstract_placeholder"],
        )
    )
    parts.append(sections["background"])
    parts.append(sections["research_questions"])
    parts.append(
        sections["method"].format(
            framework_images=framework_imgs + "\n" if framework_imgs else "",
            math_instruction_core=math_instruction_core,
            math_instruction_details=math_instruction_details,
        )
    )
    parts.append(
        sections["experiments"].format(
            results_images=results_imgs + "\n" if results_imgs else "",
        )
    )
    parts.append(sections["analysis"].format(domain=domain))
    parts.append(sections["comparison"])
    parts.append(sections["roadmap"])
    parts.append(sections["future_work"])
    parts.append(sections["evaluation"])

    # Personal notes
    parts.append(f"""\
{s["notes_heading"]}

{s["notes_comment"]}

""")

    # Related papers (wikilinks)
    related_section = f"{s['related_heading']}\n\n"
    if related_papers:
        for rp in related_papers[:5]:
            related_section += f"- [[{rp}]]\n"
    else:
        related_section += f"{s['related_placeholder']}\n"
    parts.append(related_section)

    # External resources
    ext_lines = f"\n{s['resources_heading']}\n\n"
    if arxiv_id:
        ext_lines += f"- [arXiv](https://arxiv.org/abs/{arxiv_id})\n"
    if local_pdf_rel:
        ext_lines += f"- [{s['local_pdf_label']}]({local_pdf_rel})\n"
    elif arxiv_id:
        ext_lines += f"- [PDF](https://arxiv.org/pdf/{arxiv_id})\n"
    ext_lines += f"{s['resources_placeholder']}\n"
    parts.append(ext_lines)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_note(
    paper: dict[str, Any],
    output_dir: str,
    language: str = "zh",
    images: list[dict[str, Any]] | None = None,
    local_pdf_path: str = "",
) -> str:
    """Generate a deep-analysis markdown note file for a paper.

    Args:
        paper: Paper dict with title, authors, arxiv_id, etc.
        output_dir: Directory to write the note file.
        language: "zh" or "en".
        images: Optional list of extracted images, each dict with
            'filename', 'caption', 'section' keys.
        local_pdf_path: Path to local PDF file. If provided, PDF link
            in the note will point to this local file.

    Returns:
        Path to the generated note file.
    """
    title = paper.get("title", "Untitled")
    paper_id = paper.get("arxiv_id") or paper.get("paper_id") or "unknown"
    authors_list = paper.get("authors", [])
    authors = ", ".join(authors_list[:5]) if isinstance(authors_list, list) else str(authors_list)
    domain = paper.get("best_domain") or paper.get("domain") or ""
    if not domain or domain == "Other":
        try:
            from scholar_agent.engine.domain_router import infer_domain

            knowledge_root = Path(output_dir).parent / "knowledge"
            paper_abstract = paper.get("summary", "") or paper.get("abstract", "")
            slug, _ = infer_domain(
                query=title,
                knowledge_root=knowledge_root,
                card_title=title,
                card_summary=paper_abstract[:500] if paper_abstract else "",
            )
            domain = slug if slug else "Other"
        except Exception:
            domain = "Other"
    date = paper.get("published", "")[:10] if paper.get("published") else datetime.now().strftime("%Y-%m-%d")
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    scores = paper.get("scores")
    abstract = paper.get("summary") or paper.get("abstract") or ""
    arxiv_id = paper.get("arxiv_id", "")
    affiliations = paper.get("affiliations")
    conference = paper.get("conference", "")
    pdf_url = paper.get("pdf_url", "")
    related = paper.get("related_papers")

    # Compute relative path from note file to local PDF
    local_pdf_rel = ""
    if local_pdf_path and os.path.isfile(local_pdf_path):
        # Note will be at output_dir/domain/filename/filename.md (same subfolder as download_paper)
        filename = title_to_filename(title)
        safe_domain = domain.strip("/\\").replace("..", "") or "Other"
        note_path_abs = os.path.join(output_dir, safe_domain, filename, f"{filename}.md")
        try:
            local_pdf_rel = os.path.relpath(local_pdf_path, os.path.dirname(note_path_abs))
        except ValueError:
            local_pdf_rel = local_pdf_path  # fallback to absolute on cross-drive

    # Detect math depth from abstract and domain
    paper_abstract = abstract or ""
    math_depth = detect_math_depth(paper_abstract, domain)

    content = _generate_note_body(
        paper_id,
        title,
        authors,
        domain,
        date,
        scores,
        abstract,
        arxiv_id,
        affiliations,
        conference,
        pdf_url,
        related,
        images,
        local_pdf_rel=local_pdf_rel,
        math_depth=math_depth,
        language=language,
    )

    filename = title_to_filename(title)
    # Sanitize domain for directory name
    safe_domain = domain.strip("/\\").replace("..", "") or "Other"
    # Create subfolder matching download_paper structure: domain/title/title.md
    note_dir = os.path.join(output_dir, safe_domain, filename)
    os.makedirs(note_dir, exist_ok=True)
    note_path = os.path.join(note_dir, f"{filename}.md")

    atomic_write_text(Path(note_path), content)

    logger.info("Generated note: %s", note_path)
    return note_path


def check_note_quality(note_path: str) -> dict:
    """Check a generated note for quality issues.

    Detects unfilled LLM placeholders and duplicate content across
    method/experiments/analysis sections.

    Args:
        note_path: Path to the markdown note file.

    Returns:
        Dict with 'has_issues', 'issues', and 'placeholder_count'.
    """
    content = Path(note_path).read_text(encoding="utf-8")
    issues: list[str] = []

    # Check for unfilled LLM placeholders
    placeholder_count = len(re.findall(r"<!--\s*LLM:", content))
    if placeholder_count > 0:
        issues.append(f"Found {placeholder_count} unfilled <!-- LLM: --> placeholders")

    # Extract method/experiments/analysis sections
    section_names = [
        "方法概述",
        "实验结果",
        "深度分析",
        "Method Overview",
        "Experimental Results",
        "Deep Analysis",
    ]
    sections: dict[str, str] = {}
    for name in section_names:
        match = re.search(
            rf"^## {re.escape(name)}\s*\n(.*?)(?=^## |\Z)",
            content,
            re.MULTILINE | re.DOTALL,
        )
        if match:
            sections[name] = match.group(1).strip()[:200]

    # Compare section pairs for identical content
    names = list(sections.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            s1, s2 = sections[names[i]], sections[names[j]]
            if len(s1) > 50 and s1 == s2:
                issues.append(f"Sections '{names[i]}' and '{names[j]}' are identical")

    return {
        "has_issues": len(issues) > 0,
        "issues": issues,
        "placeholder_count": placeholder_count,
    }


# ---------------------------------------------------------------------------
# LLM-powered auto-fill
# ---------------------------------------------------------------------------

_FILL_SECTION_SYSTEM_PROMPT = """\
You are a research paper analysis assistant. You are given ONE section of a
structured markdown note plus the paper's PDF full text. Fill in ALL
<!-- LLM: ... --> placeholders found in THAT SECTION ONLY.

Rules:
1. Replace each <!-- LLM: ... --> comment with substantive content fulfilling
   the instruction inside the comment; remove the comment markers.
2. Output the COMPLETE section verbatim — keep every heading, table scaffold,
   blockquote and surrounding text unchanged. Only placeholder comments get
   replaced by their content.
3. Do NOT add preamble, summaries, or any section beyond what is given. Do NOT
   wrap the output in code fences.
4. Write in the section's language (Chinese for zh, English for en).
5. Use LaTeX for math ($...$ inline, $$...$$ block).
6. Be specific — cite numbers, dataset names, method details from the PDF.
7. If the PDF text is insufficient for a placeholder, write what you can and
   leave a brief honest note rather than inventing facts.
"""

_SECTION_HEADING_RE = re.compile(r"(?m)^(## .*)$")


def _split_into_sections(content: str) -> list[str]:
    """Split a note into chunks by top-level (##) headings.

    The preamble (frontmatter + title, before the first ## ) is the first
    chunk; each subsequent chunk is one ## section (heading + body). This lets
    us fill each section in its own LLM call so no single call's output is
    large enough to hit the model's token limit.
    """
    parts = _SECTION_HEADING_RE.split(content)
    chunks: list[str] = []
    if parts[0].strip():
        chunks.append(parts[0])
    i = 1
    while i < len(parts):
        heading = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        chunks.append(heading + body)
        i += 2
    return chunks


def _strip_code_fences(text: str) -> str:
    if text.startswith("```markdown\n"):
        text = text[len("```markdown\n") :]
    if text.startswith("```\n"):
        text = text[len("```\n") :]
    if text.endswith("\n```"):
        text = text[:-4]
    return text


def _strip_orphaned_comment_markers(text: str) -> str:
    """Drop orphaned ``-->`` left when the LLM fills content but keeps the
    placeholder's closing marker. Balanced ``<!-- ... -->`` blocks (including
    unfilled ``<!-- LLM: ... -->`` placeholders) are preserved.
    """
    out: list[str] = []
    i = 0
    open_count = 0
    n = len(text)
    while i < n:
        if text.startswith("<!--", i):
            open_count += 1
            out.append("<!--")
            i += 4
        elif text.startswith("-->", i):
            if open_count > 0:
                open_count -= 1
                out.append("-->")
            # else: orphaned --> — drop it
            i += 3
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def fill_note_from_pdf(note_path: str, pdf_text: str) -> dict:
    """Fill <!-- LLM: --> placeholders section-by-section using PDF text via LLM.

    Splits the note into ## sections and fills each in its own LLM call, then
    *re-fills* any section that still has placeholders — a continuation loop —
    because a single pass often leaves a few sections partly filled (truncated
    LLM output or a skipped section). The loop stops when no placeholders remain
    or a round makes no progress, capped at ``max_rounds``.

    Before writing, orphaned ``-->`` markers are stripped (A2b).

    Returns:
        Dict with 'status' (ok/partial/error/skipped), 'placeholders_filled',
        'placeholders_remaining', 'sections_filled', 'sections_failed',
        'rounds_used', 'model_used', 'api_format'.
    """
    content = Path(note_path).read_text(encoding="utf-8")
    total = len(re.findall(r"<!--\s*LLM:", content))
    if total == 0:
        return {"status": "skipped", "reason": "No placeholders to fill", "placeholders_filled": 0}

    providers = resolve_providers()
    if not providers:
        return {"status": "skipped", "reason": "No API key configured", "placeholders_filled": 0}

    # Truncate PDF text to stay within token budget (shared across all sections)
    max_pdf_chars = 60000
    truncated = pdf_text[:max_pdf_chars]
    if len(pdf_text) > max_pdf_chars:
        truncated += "\n\n[... PDF text truncated ...]"

    def _fill_round(text: str) -> tuple[str, int, int, str | None, str | None]:
        """One pass over sections still containing placeholders."""
        filled_chunks: list[str] = []
        sections_filled = 0
        sections_failed = 0
        last_model: str | None = None
        last_format: str | None = None
        for chunk in _split_into_sections(text):
            if not re.search(r"<!--\s*LLM:", chunk):
                # No placeholders in this section — keep verbatim.
                filled_chunks.append(chunk)
                continue
            try:
                messages = [
                    {"role": "system", "content": _FILL_SECTION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Here is the paper's PDF full text:\n\n---\n{truncated}\n---\n\n"
                            "Fill EVERY <!-- LLM: --> placeholder in the section below. "
                            "Output the COMPLETE section, unchanged except for filled placeholders:\n\n"
                            f"{chunk}"
                        ),
                    },
                ]
                resp = chat_with_fallback(messages, providers=providers, max_tokens=4096, temperature=0.3)
                filled = _strip_code_fences(resp.content)
                last_model = resp.model
                last_format = resp.provider_format
                sections_filled += 1
                filled_chunks.append(filled if filled.strip() else chunk)
            except Exception:
                sections_failed += 1
                filled_chunks.append(chunk)  # keep original section on failure
        return "".join(filled_chunks), sections_filled, sections_failed, last_model, last_format

    # Continuation loop: re-fill remaining placeholders each round; stop on
    # completion or no-progress (avoids spinning on a section the LLM won't fill).
    max_rounds = 3
    prev_remaining: int | None = None
    rounds_used = 0
    total_filled = 0
    total_failed = 0
    last_model: str | None = None
    last_format: str | None = None
    text = content
    for _ in range(max_rounds):
        rounds_used += 1
        text, filled, failed, model, fmt = _fill_round(text)
        total_filled += filled
        total_failed += failed
        if model:
            last_model = model
        if fmt:
            last_format = fmt
        remaining = len(re.findall(r"<!--\s*LLM:", text))
        if remaining == 0 or remaining == prev_remaining:
            break
        prev_remaining = remaining

    final = _strip_orphaned_comment_markers(text)
    final = final.replace("status: skeleton", "status: filled", 1)
    try:
        atomic_write_text(Path(note_path), final)
    except OSError as exc:
        return {"status": "error", "reason": f"Write failed: {exc}", "placeholders_filled": 0}

    remaining = len(re.findall(r"<!--\s*LLM:", final))
    if remaining == 0:
        status = "ok"
    elif total - remaining > 0:
        status = "partial"
    else:
        status = "error"
    return {
        "status": status,
        "placeholders_filled": total - remaining,
        "placeholders_remaining": remaining,
        "sections_filled": total_filled,
        "sections_failed": total_failed,
        "rounds_used": rounds_used,
        "model_used": last_model,
        "api_format": last_format,
    }


# ---------------------------------------------------------------------------
# Self-repair (C loop): expand thin sections + backfill metadata
# ---------------------------------------------------------------------------

_EXPAND_SECTION_SYSTEM_PROMPT = """\
You are a research paper analysis assistant. A section of a structured markdown
note is too thin (only bullets/tables, no explanatory prose). Rewrite THIS
SECTION ONLY, keeping its `##` heading and any existing content, and ADD
substantive prose paragraphs (each over 50 characters, in your own words)
grounded in the paper's PDF.

Rules:
1. Output the COMPLETE section — keep the `##` heading and existing tables/lists;
   ADD prose explaining the key ideas. Do NOT drop existing content.
2. Do NOT add new `##` sections or touch other sections. Do NOT wrap in code fences.
3. Write in the section's language (Chinese for zh, English for en). Use LaTeX for math.
4. Cite specifics from the PDF. Do NOT invent numbers or facts the PDF does not support.
"""

# validate_note content-density errors → section alias group for expand_section.
_THIN_ERROR_TO_ALIAS = {
    "method_section_lacks_prose": "method",
    "findings_section_lacks_substance": "findings",
}

# metadata_unknown:{key} → paper_json field holding a known replacement value.
_METADATA_BACKFILL = {
    "authors": "authors",
    "domain": "best_domain",
    "conference": "conference",
    "arxiv_id": "arxiv_id",
}


def expand_section(note_path: str, section_title: str, pdf_text: str) -> bool:
    """Expand a thin section with LLM-generated prose. Returns True if rewritten.

    Locates the ``## {section_title}`` chunk; if it has no prose paragraph, asks
    the LLM to expand it using the PDF text, then writes the note back.
    """
    providers = resolve_providers()
    if not providers:
        return False
    content = Path(note_path).read_text(encoding="utf-8")
    heading = f"## {section_title}"
    chunks = _split_into_sections(content)
    idx = next((i for i, c in enumerate(chunks) if c.startswith(heading)), None)
    if idx is None:
        return False
    chunk = chunks[idx]
    if _has_prose_paragraph(chunk):
        return False  # already substantive

    truncated = pdf_text[:60000]
    messages = [
        {"role": "system", "content": _EXPAND_SECTION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Paper PDF full text:\n\n---\n{truncated}\n---\n\n"
                "Expand this thin section with substantive prose:\n\n"
                f"{chunk}"
            ),
        },
    ]
    try:
        resp = chat_with_fallback(messages, providers=providers, max_tokens=4096, temperature=0.3)
        expanded = _strip_code_fences(resp.content)
    except Exception:
        return False
    if not expanded.strip() or not _has_prose_paragraph(expanded):
        return False
    if not expanded.startswith("##"):
        expanded = f"{heading}\n\n{expanded}"
    chunks[idx] = expanded
    new_content = _strip_orphaned_comment_markers("".join(chunks))
    atomic_write_text(Path(note_path), new_content)
    return True


def _resolve_section_title(note_path: str, error: str) -> str | None:
    """Map a thin/prose error to the section title (via validate_note aliases)."""
    content = Path(note_path).read_text(encoding="utf-8")
    sections = extract_sections(content)
    alias_key: str | None
    if error.startswith("thin_section:"):
        alias_key = error.split(":", 1)[1]
        if alias_key == "dataset_fallback":
            alias_key = "dataset"
    else:
        alias_key = _THIN_ERROR_TO_ALIAS.get(error)
    if not alias_key or alias_key not in SECTION_ALIASES:
        return None
    title, _body = find_section(sections, SECTION_ALIASES[alias_key])
    return title


def _backfill_metadata(note_path: str, key: str, paper_json: dict) -> bool:
    """Replace an unknown metadata value with a known one from paper_json."""
    source_key = _METADATA_BACKFILL.get(key)
    if not source_key:
        return False
    val = paper_json.get(source_key)
    if isinstance(val, list):
        val = ", ".join(str(v) for v in val) if val else ""
    if not val or (isinstance(val, str) and val.strip().lower() in UNKNOWN_VALUES):
        return False
    content = Path(note_path).read_text(encoding="utf-8")
    pattern = re.compile(rf"(?m)^({re.escape(key)}):\s.*$")
    new_content, n = pattern.subn(rf'\1: "{val}"', content, count=1)
    if n == 0:
        return False
    atomic_write_text(Path(note_path), new_content)
    return True


_TYPE_SPECIFIC_ERRORS = frozenset(
    {
        "empirical_requires_two_quantitative_results",
        "theory_requires_problem_definition_or_mechanism",
        "survey_requires_taxonomy",
        "survey_requires_consensus_or_disagreement",
        "benchmark_requires_protocol_baseline_and_risk",
    }
)


def _resolve_type_specific_section(note_path: str, err: str) -> str | None:
    """Map a type_specific error to the section whose prose should carry the marker.

    Most type_specific markers (quantitative results, taxonomy, problem
    definition, baseline/protocol) belong in findings or method.
    """
    content = Path(note_path).read_text(encoding="utf-8")
    sections = extract_sections(content)
    for key in ("findings", "method"):
        title, _body = find_section(sections, SECTION_ALIASES[key])
        if title:
            return title
    return None


def auto_repair_note(note_path: str, errors: list[str], pdf_text: str, paper_json: dict) -> dict:
    """Auto-repair validate_note errors in place. Returns {repaired, unresolved}.

    Dispatch by error prefix:
    - placeholder/skeleton/pdf_placeholder → fill_note_from_pdf (one re-fill fixes all)
    - thin_section:* / *_lacks_prose / *_lacks_substance → expand_section
    - metadata_unknown:* → backfill from paper_json
    - structural (duplicated_frontmatter, etc.) → not auto-repairable
    """
    repaired = False
    unresolved: list[str] = []
    needs_fill = False
    for err in errors:
        if err in ("llm_placeholder_comment", "skeleton_status", "pdf_placeholder_text"):
            needs_fill = True
        elif err.startswith("thin_section:") or err in _THIN_ERROR_TO_ALIAS:
            title = _resolve_section_title(note_path, err)
            if title and expand_section(note_path, title, pdf_text):
                repaired = True
            else:
                unresolved.append(err)
        elif err.startswith("metadata_unknown:"):
            key = err.split(":", 1)[1]
            if _backfill_metadata(note_path, key, paper_json):
                repaired = True
            else:
                unresolved.append(err)
        elif err in _TYPE_SPECIFIC_ERRORS:
            # type_specific marker/quantitative gaps → expand the relevant section
            # so the LLM injects the expected markers/numbers.
            title = _resolve_type_specific_section(note_path, err)
            if title and expand_section(note_path, title, pdf_text):
                repaired = True
            else:
                unresolved.append(err)
        else:
            unresolved.append(err)
    if needs_fill:
        fill_note_from_pdf(note_path, pdf_text)
        repaired = True
    return {"repaired": repaired, "unresolved": unresolved}
