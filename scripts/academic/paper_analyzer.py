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
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from common import sanitize_title

logger = logging.getLogger(__name__)

# Backward-compatible alias used by note_linker.py
title_to_filename = sanitize_title

# ---------------------------------------------------------------------------
# Math depth detection
# ---------------------------------------------------------------------------

_MATH_HEAVY_DOMAINS = {
    "运筹优化", "运筹优化与库存规划", "库存规划", "供应链优化",
    "供应链", "supply-chain", "newsvendor",
    "统计推断", "概率论", "信息论", "控制论", "优化理论",
    "计量经济学", "数学物理", "博弈论",
    "quantitative-finance", "量化金融",
    "operations-research", "optimization", "control-theory",
    "statistics", "probability", "information-theory",
    "econometrics", "mathematical-physics", "game-theory",
    "bayesian", "reinforcement-learning",
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
    r"(?:\$\$.*?\$\\$|\$[^$]+\$|\\begin\{equation|\\end\{equation|"
    r"\\frac\{|\\sum_|\\int_|\\prod_|\\mathbb\{|\\mathcal\{|\\boldsymbol)",
    re.DOTALL,
)


def detect_math_depth(abstract: str, domain: str, pdf_text: str = "") -> str:
    """Detect whether a paper needs heavy, light, or no math treatment.

    Returns one of: "heavy", "light", "none".
    """
    text = f"{abstract} {pdf_text[:2000]}"

    domain_match = any(
        kw in domain.lower() for kw in _MATH_HEAVY_DOMAINS
    )

    keyword_hits = len(_MATH_HEAVY_KEYWORDS.findall(text))
    latex_hits = len(_LATEX_MARKERS.findall(text))

    if domain_match and (keyword_hits >= 3 or latex_hits >= 2):
        return "heavy"
    if keyword_hits >= 2 or latex_hits >= 1:
        return "light"
    if domain_match:
        return "light"
    return "none"


def _yaml_escape(s: str) -> str:
    """Escape a string for safe embedding in YAML double-quoted values."""
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


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
# Chinese template sections
# ---------------------------------------------------------------------------

_ZH_SECTIONS = {
    "abstract_translation": """\
## 摘要翻译

### 英文摘要

{abstract}

### 中文翻译

<!-- LLM: 请将上方英文摘要翻译为流畅、准确的中文，保留专业术语的英文原文（首次出现时括号标注） -->

### 核心要点

<!-- LLM: 从摘要中提炼以下要点（每条1-2句）：
1. 研究背景与动机
2. 核心方法/创新
3. 主要结果
4. 研究意义
-->
""",

    "background": """\
## 研究背景与动机

<!-- LLM: 请分析并撰写：
1. **领域现状**：该研究所在领域的发展阶段和主流方法
2. **现有方法局限性**：当前方法存在的关键问题或瓶颈
3. **研究动机**：本文为什么提出新方法，要解决什么gap
4. **问题重要性**：为什么这个问题值得研究
-->
""",

    "research_questions": """\
## 研究问题

<!-- LLM: 提炼本文要解决的核心问题：
1. **主要研究问题**（RQ1）：[最核心的问题]
2. **子问题**（如有）：[分解的具体子问题]
3. **假设**（如有）：[作者的核心假设]
-->
""",

    "method": """\
## 方法概述

### 核心思想

{math_instruction_core}

### 整体框架

{framework_images}<!-- LLM: 描述整体架构/流程：
1. 输入是什么、输出是什么
2. 主要模块/阶段有哪些
3. 模块之间如何连接
4. 如有框架图请引用 ![[images/fig]]
-->

### 模块详解

{math_instruction_details}
""",

    "experiments": """\
## 实验结果

### 数据集

<!-- LLM: 用表格整理实验使用的数据集：

| 数据集 | 规模 | 特点 | 用途 |
|:--|:--|:--|:--|
| | | | |
-->

### 基线方法

<!-- LLM: 列出所有对比方法，简要说明每个方法的核心思路：
1. **[方法名]**：[一句话描述]
2. ...
-->

### 主要结果

{results_images}<!-- LLM: 用表格呈现主要实验结果（从论文表格中提取关键数据）：

| 方法 | 指标1 | 指标2 | 指标3 |
|:--|:--|:--|:--|
| 本文方法 | **最优值** | | |
| 基线1 | | | |

关键发现：
1. [发现1]
2. [发现2]
-->

### 消融实验

<!-- LLM: 整理消融实验的关键发现：
1. **[被移除/修改的组件]**：移除后性能变化，说明了什么
2. ...

如有消融结果表格，请一并整理。
-->
""",

    "analysis": """\
## 深度分析

### 理论贡献

<!-- LLM: 分析本文的理论价值：
1. 提出了什么新概念/框架/定理？
2. 对领域理论体系有何推进？
3. 是否开辟了新的研究方向？
-->

### 实际应用

<!-- LLM: 分析本文的应用价值：
1. 可以应用于哪些场景？
2. 部署/使用的难度和成本如何？
3. 对我的研究方向（{domain}）有何启发？
-->

### 优势

<!-- LLM: 详细分析本文的优势（每条2-3句）：
1. **[优势1]**：[具体分析]
2. **[优势2]**：[具体分析]
3. ...
-->

### 局限性

<!-- LLM: 详细分析本文的局限性（每条2-3句）：
1. **[局限1]**：[具体分析和潜在影响]
2. **[局限2]**：[具体分析和潜在影响]
3. ...
-->
""",

    "comparison": """\
## 与相关工作对比

<!-- LLM: 选择2-3篇最相关的论文进行深度对比：

### 方法对比

| 维度 | 本文 | [相关论文1] | [相关论文2] |
|:--|:--|:--|:--|
| 核心思路 | | | |
| 模型架构 | | | |
| 训练策略 | | | |
| 数据需求 | | | |

### 性能对比

| 指标 | 本文 | [相关论文1] | [相关论文2] |
|:--|:--|:--|:--|
| | | | |

### 关键差异分析
1. **与[论文1]的区别**：[具体分析]
2. **与[论文2]的区别**：[具体分析]
-->
""",

    "roadmap": """\
## 技术路线定位

<!-- LLM: 描述本文在技术发展脉络中的位置：
1. **前序工作**：本文建立在哪些工作基础上？
2. **技术演进**：从早期方法到本文，经历了怎样的演进？
3. **本文定位**：在当前技术路线图中处于什么位置？
4. **发展趋势**：该方向未来可能的发展趋势
-->
""",

    "future_work": """\
## 未来工作

<!-- LLM: 分三部分撰写：

### 作者建议
[从论文 Future Work / Conclusion 中提取作者自己提到的后续方向]

### 延伸方向
[基于论文方法，分析可能的延伸研究方向]

### 改进建议
[基于局限性分析，提出具体的改进思路]
-->
""",

    "evaluation": """\
## 综合评价

| 维度 | 评分 | 说明 |
|:--|:--|:--|
| 创新性 | /10 | <!-- LLM: 评价方法的新颖程度 --> |
| 技术质量 | /10 | <!-- LLM: 评价技术方案的严谨性 --> |
| 实验充分性 | /10 | <!-- LLM: 评价实验设计和结果的充分性 --> |
| 写作质量 | /10 | <!-- LLM: 评价论文的写作水平 --> |
| 实用性 | /10 | <!-- LLM: 评价方法的实际应用价值 --> |

<!-- LLM: 用2-3句话给出总体评价，包括是否推荐精读、适合什么水平的读者 -->

> [!tip] 关键启示
> <!-- LLM: 用1-2句话提炼本文最核心的洞见或启发 -->

> [!success] 推荐指数
> <!-- LLM: 给出推荐星级（1-5星）和一句话推荐理由，如：⭐⭐⭐⭐⭐ [推荐理由] -->
""",
}

# ---------------------------------------------------------------------------
# English template sections
# ---------------------------------------------------------------------------

_EN_SECTIONS = {
    "abstract_analysis": """\
## Abstract Analysis

### Original Abstract

{abstract}

### Key Points

<!-- LLM: Extract the following from the abstract (1-2 sentences each):
1. Research background and motivation
2. Core method/innovation
3. Main results
4. Significance
-->
""",

    "background": """\
## Research Background & Motivation

<!-- LLM: Please analyze and write:
1. **Field status**: Current state of the art and mainstream approaches
2. **Limitations**: Key problems or bottlenecks in existing methods
3. **Motivation**: Why the authors propose a new method, what gap they address
4. **Importance**: Why this problem matters
-->
""",

    "research_questions": """\
## Research Questions

<!-- LLM: Extract the core research questions:
1. **Primary RQ**: [the main question]
2. **Sub-questions** (if any): [specific sub-problems]
3. **Hypotheses** (if any): [core hypotheses]
-->
""",

    "method": """\
## Method Overview

### Core Idea

{math_instruction_core}

### Overall Framework

{framework_images}<!-- LLM: Describe the overall architecture/pipeline:
1. What are the inputs and outputs?
2. What are the main modules/stages?
3. How do modules connect?
4. Reference framework figures if available: ![[images/fig]]
-->

### Module Details

{math_instruction_details}
""",

    "experiments": """\
## Experimental Results

### Datasets

<!-- LLM: Summarize datasets in a table:

| Dataset | Size | Characteristics | Usage |
|:--|:--|:--|:--|
| | | | |
-->

### Baselines

<!-- LLM: List all compared methods with a one-line description:
1. **[Method]**: [core idea]
2. ...
-->

### Main Results

{results_images}<!-- LLM: Present key results in a table:

| Method | Metric 1 | Metric 2 | Metric 3 |
|:--|:--|:--|:--|
| Ours | **best** | | |
| Baseline 1 | | | |

Key findings:
1. [Finding 1]
2. [Finding 2]
-->

### Ablation Study

<!-- LLM: Summarize key ablation findings:
1. **[Removed/modified component]**: Performance change and implications
2. ...
-->
""",

    "analysis": """\
## Deep Analysis

### Theoretical Contributions

<!-- LLM: Analyze the theoretical value:
1. What new concepts/frameworks/theorems are proposed?
2. How does it advance the field's theoretical framework?
3. Does it open new research directions?
-->

### Practical Applications

<!-- LLM: Analyze application value:
1. What scenarios can this be applied to?
2. Deployment difficulty and cost?
3. Implications for my research area ({domain})?
-->

### Strengths

<!-- LLM: Detailed analysis of strengths (2-3 sentences each):
1. **[Strength 1]**: [analysis]
2. **[Strength 2]**: [analysis]
-->

### Limitations

<!-- LLM: Detailed analysis of limitations (2-3 sentences each):
1. **[Limitation 1]**: [analysis and potential impact]
2. **[Limitation 2]**: [analysis and potential impact]
-->
""",

    "comparison": """\
## Comparison with Related Work

<!-- LLM: Select 2-3 most relevant papers for in-depth comparison:

### Method Comparison

| Aspect | This Paper | [Related 1] | [Related 2] |
|:--|:--|:--|:--|
| Core idea | | | |
| Architecture | | | |
| Training | | | |
| Data needs | | | |

### Performance Comparison

| Metric | This Paper | [Related 1] | [Related 2] |
|:--|:--|:--|:--|
| | | | |

### Key Differences
1. **vs [Paper 1]**: [analysis]
2. **vs [Paper 2]**: [analysis]
-->
""",

    "roadmap": """\
## Technical Roadmap

<!-- LLM: Describe where this paper sits in the technical landscape:
1. **Prior work**: What does this paper build upon?
2. **Evolution**: How has the approach evolved from earlier methods?
3. **Positioning**: Where does this paper sit in the current roadmap?
4. **Trends**: Likely future directions for this line of research
-->
""",

    "future_work": """\
## Future Work

<!-- LLM: Cover three aspects:

### Author Suggestions
[Extract from the paper's Future Work / Conclusion section]

### Extension Directions
[Analyze possible extensions based on the method]

### Improvement Suggestions
[Propose improvements based on the limitations analysis]
-->
""",

    "evaluation": """\
## Comprehensive Evaluation

| Dimension | Score | Notes |
|:--|:--|:--|
| Novelty | /10 | <!-- LLM: How novel is the approach? --> |
| Technical Quality | /10 | <!-- LLM: How rigorous is the technical design? --> |
| Experimental Rigor | /10 | <!-- LLM: How thorough are the experiments? --> |
| Writing Quality | /10 | <!-- LLM: How well is the paper written? --> |
| Practicality | /10 | <!-- LLM: How useful is this in practice? --> |

<!-- LLM: Provide a 2-3 sentence overall assessment, including reading recommendation and target audience -->

> [!tip] Key Insights
> <!-- LLM: Distill the most core insight or takeaway in 1-2 sentences -->

> [!success] Recommendation
> <!-- LLM: Give a star rating (1-5) and one-sentence reason, e.g.: ⭐⭐⭐⭐⭐ [reason] -->
""",
}


# ---------------------------------------------------------------------------
# Note generators
# ---------------------------------------------------------------------------

def _generate_zh_note(
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
) -> str:
    """Generate Chinese deep-analysis markdown note."""
    # --- Tags ---
    domain_tags = {
        "LLM与Agent": ["LLM", "Agent", "大模型"],
        "运筹优化与库存规划": ["运筹优化", "库存规划", "供应链"],
        "LLM": ["LLM", "Large-Language-Model"],
        "多模态": ["多模态", "Multimodal", "VLM"],
        "Agent": ["Agent", "Autonomous-Agent"],
    }
    tags = ["论文笔记"] + domain_tags.get(domain, [domain])
    tags_yaml = "\n".join(f"  - {tag}" for tag in tags)

    score_str = f"{scores.get('recommendation', 0):.1f}/10" if scores else "[SCORE]/10"
    _rps = related_papers or []
    if _rps:
        related_yaml = "\n" + "\n".join(f'  - "{rp}"' for rp in _rps)
    else:
        related_yaml = " []"
    affil_str = "、".join(affiliations[:3]) if affiliations else "<!-- LLM: 从论文中提取作者机构信息 -->"

    # --- Links ---
    links = f"[arXiv](https://arxiv.org/abs/{arxiv_id})" if arxiv_id else ""
    # Prefer local PDF link over online URL
    if local_pdf_rel:
        links += f" | [PDF]({local_pdf_rel})" if links else f"[PDF]({local_pdf_rel})"
    elif pdf_url:
        links += f" | [PDF]({pdf_url})" if links else f"[PDF]({pdf_url})"
    elif arxiv_id:
        links += f" | [PDF](https://arxiv.org/pdf/{arxiv_id})"
    if not links:
        links = "<!-- LLM: 补充论文链接 -->"

    # --- Image refs ---
    framework_imgs = _format_image_refs(images, "framework")
    results_imgs = _format_image_refs(images, "results")

    # --- Math instructions based on depth ---
    if math_depth == "heavy":
        math_instruction_core = (
            "<!-- LLM: 用通俗语言（1-2段）概括方法的核心创新。"
            "在通俗解释之后，**必须**给出核心数学公式的直觉解释，"
            "用 $...$ 行内 LaTeX 引用关键符号。不要跳过数学本质。 -->"
        )
        math_instruction_details = (
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
        )
    elif math_depth == "light":
        math_instruction_core = (
            "<!-- LLM: 用通俗语言（1-2段）概括方法的核心创新，"
            "在关键处用 $...$ 行内 LaTeX 标注核心公式 -->"
        )
        math_instruction_details = (
            "<!-- LLM: 对每个核心模块分别描述：\n"
            "#### 模块1：[名称]\n"
            "- **功能**：[该模块的作用]\n"
            "- **输入/输出**：[数据流]\n"
            "- **关键技术**：[使用的技术或算法]\n"
            "- **数学公式**：如有，用 LaTeX：$...$ 行内，$$...$$ 块级\n\n"
            "#### 模块2：[名称]\n"
            "...（以此类推）\n"
            "-->"
        )
    else:
        math_instruction_core = (
            "<!-- LLM: 用通俗语言（1-2段）概括方法的核心创新 -->"
        )
        math_instruction_details = (
            "<!-- LLM: 对每个核心模块分别描述：\n"
            "#### 模块1：[名称]\n"
            "- **功能**：[该模块的作用]\n"
            "- **输入/输出**：[数据流]\n"
            "- **关键技术**：[使用的技术或算法]\n\n"
            "#### 模块2：[名称]\n"
            "...（以此类推）\n"
            "-->"
        )

    # --- Build note ---
    parts: list[str] = []

    # Frontmatter — reordered and added new fields
    parts.append(f'''---
title: "{_yaml_escape(title)}"
paper_id: "{paper_id}"
authors: "{_yaml_escape(authors)}"
domain: "{domain}"
date: "{date}"
status: skeleton
math_depth: "{math_depth}"
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
## 核心信息
- **论文ID**：{paper_id}
- **作者**：{authors}
- **机构**：{affil_str}
- **发布时间**：{date}
- **会议/期刊**：{conference or "<!-- LLM: 从 categories 或论文信息推断 -->"}
- **领域**：{domain}
- **评分**：{score_str}
- **链接**：{links}
""")

    # Template sections
    parts.append(_ZH_SECTIONS["abstract_translation"].format(
        abstract=abstract or "<!-- LLM: 请从论文中提取英文摘要 -->",
    ))
    parts.append(_ZH_SECTIONS["background"])
    parts.append(_ZH_SECTIONS["research_questions"])
    parts.append(_ZH_SECTIONS["method"].format(
        framework_images=framework_imgs + "\n" if framework_imgs else "",
        math_instruction_core=math_instruction_core,
        math_instruction_details=math_instruction_details,
    ))
    parts.append(_ZH_SECTIONS["experiments"].format(
        results_images=results_imgs + "\n" if results_imgs else "",
    ))
    parts.append(_ZH_SECTIONS["analysis"].format(domain=domain))
    parts.append(_ZH_SECTIONS["comparison"])
    parts.append(_ZH_SECTIONS["roadmap"])
    parts.append(_ZH_SECTIONS["future_work"])
    parts.append(_ZH_SECTIONS["evaluation"])

    # Personal notes
    parts.append("""\
## 我的笔记

<!-- 在此记录个人想法、灵感、与自己研究的关联 -->

""")

    # Related papers (wikilinks)
    related_section = "## 相关论文\n\n"
    if related_papers:
        for rp in related_papers[:5]:
            related_section += f"- [[{rp}]]\n"
    else:
        related_section += "<!-- LLM: 根据研究主题，链接知识库中的相关论文笔记 -->\n"
    parts.append(related_section)

    # External resources
    ext_lines = "\n## 外部资源\n\n"
    if arxiv_id:
        ext_lines += f"- [arXiv](https://arxiv.org/abs/{arxiv_id})\n"
    if local_pdf_rel:
        ext_lines += f"- [本地PDF]({local_pdf_rel})\n"
    elif arxiv_id:
        ext_lines += f"- [PDF](https://arxiv.org/pdf/{arxiv_id})\n"
    ext_lines += "<!-- LLM: 补充代码仓库、数据集、项目主页等链接 -->\n"
    parts.append(ext_lines)

    return "\n".join(parts)


def _generate_en_note(
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
) -> str:
    """Generate English deep-analysis markdown note."""
    # --- Tags ---
    domain_tags = {
        "LLM & Agents": ["LLM", "Autonomous-Agent"],
        "LLM": ["LLM", "Large-Language-Model"],
        "Multimodal": ["Multimodal", "VLM"],
        "Agent": ["Agent", "Agentic-System"],
    }
    tags = ["paper-notes"] + domain_tags.get(domain, [domain])
    tags_yaml = "\n".join(f"  - {tag}" for tag in tags)

    score_str = f"{scores.get('recommendation', 0):.1f}/10" if scores else "[SCORE]/10"
    _rps = related_papers or []
    if _rps:
        related_yaml = "\n" + "\n".join(f'  - "{rp}"' for rp in _rps)
    else:
        related_yaml = " []"
    affil_str = ", ".join(affiliations[:3]) if affiliations else "<!-- LLM: Extract author affiliations from the paper -->"

    # --- Links ---
    links = f"[arXiv](https://arxiv.org/abs/{arxiv_id})" if arxiv_id else ""
    # Prefer local PDF link over online URL
    if local_pdf_rel:
        links += f" | [PDF]({local_pdf_rel})" if links else f"[PDF]({local_pdf_rel})"
    elif pdf_url:
        links += f" | [PDF]({pdf_url})" if links else f"[PDF]({pdf_url})"
    elif arxiv_id:
        links += f" | [PDF](https://arxiv.org/pdf/{arxiv_id})"
    if not links:
        links = "<!-- LLM: Add paper links -->"

    # --- Image refs ---
    framework_imgs = _format_image_refs(images, "framework")
    results_imgs = _format_image_refs(images, "results")

    # --- Math instructions based on depth ---
    if math_depth == "heavy":
        math_instruction_core = (
            "<!-- LLM: Explain the core innovation in plain language (1-2 paragraphs). "
            "After the intuitive explanation, you MUST provide the intuition behind "
            "the core mathematical formulas, using $...$ inline LaTeX for key symbols. "
            "Do not skip the mathematical essence. -->"
        )
        math_instruction_details = (
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
        )
    elif math_depth == "light":
        math_instruction_core = (
            "<!-- LLM: Explain the core innovation in plain language (1-2 paragraphs), "
            "annotating key formulas with $...$ inline LaTeX where appropriate -->"
        )
        math_instruction_details = (
            "<!-- LLM: For each core module:\n"
            "#### Module 1: [Name]\n"
            "- **Function**: [what it does]\n"
            "- **Input/Output**: [data flow]\n"
            "- **Key Techniques**: [algorithms or techniques used]\n"
            "- **Math** (if any): Use LaTeX — $...$ inline, $$...$$ block\n\n"
            "#### Module 2: [Name]\n"
            "...(and so on)\n"
            "-->"
        )
    else:
        math_instruction_core = (
            "<!-- LLM: Explain the core innovation in plain language (1-2 paragraphs) -->"
        )
        math_instruction_details = (
            "<!-- LLM: For each core module:\n"
            "#### Module 1: [Name]\n"
            "- **Function**: [what it does]\n"
            "- **Input/Output**: [data flow]\n"
            "- **Key Techniques**: [algorithms or techniques used]\n\n"
            "#### Module 2: [Name]\n"
            "...(and so on)\n"
            "-->"
        )

    # --- Build note ---
    parts: list[str] = []

    # Frontmatter — reordered and added new fields
    parts.append(f'''---
title: "{_yaml_escape(title)}"
paper_id: "{paper_id}"
authors: "{_yaml_escape(authors)}"
domain: "{domain}"
date: "{date}"
status: skeleton
math_depth: "{math_depth}"
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
## Core Information
- **Paper ID**: {paper_id}
- **Authors**: {authors}
- **Affiliation**: {affil_str}
- **Publication Date**: {date}
- **Conference/Journal**: {conference or "<!-- LLM: Infer from categories or paper info -->"}
- **Domain**: {domain}
- **Score**: {score_str}
- **Links**: {links}
""")

    # Template sections
    parts.append(_EN_SECTIONS["abstract_analysis"].format(
        abstract=abstract or "<!-- LLM: Extract the abstract from the paper -->",
    ))
    parts.append(_EN_SECTIONS["background"])
    parts.append(_EN_SECTIONS["research_questions"])
    parts.append(_EN_SECTIONS["method"].format(
        framework_images=framework_imgs + "\n" if framework_imgs else "",
        math_instruction_core=math_instruction_core,
        math_instruction_details=math_instruction_details,
    ))
    parts.append(_EN_SECTIONS["experiments"].format(
        results_images=results_imgs + "\n" if results_imgs else "",
    ))
    parts.append(_EN_SECTIONS["analysis"].format(domain=domain))
    parts.append(_EN_SECTIONS["comparison"])
    parts.append(_EN_SECTIONS["roadmap"])
    parts.append(_EN_SECTIONS["future_work"])
    parts.append(_EN_SECTIONS["evaluation"])

    # Personal notes
    parts.append("""\
## My Notes

<!-- Record personal thoughts, insights, connections to your own research -->

""")

    # Related papers (wikilinks)
    related_section = "## Related Papers\n\n"
    if related_papers:
        for rp in related_papers[:5]:
            related_section += f"- [[{rp}]]\n"
    else:
        related_section += "<!-- LLM: Link to related paper notes in the knowledge base -->\n"
    parts.append(related_section)

    # External resources
    ext_lines = "\n## External Resources\n\n"
    if arxiv_id:
        ext_lines += f"- [arXiv](https://arxiv.org/abs/{arxiv_id})\n"
    if local_pdf_rel:
        ext_lines += f"- [Local PDF]({local_pdf_rel})\n"
    elif arxiv_id:
        ext_lines += f"- [PDF](https://arxiv.org/pdf/{arxiv_id})\n"
    ext_lines += "<!-- LLM: Add code repo, dataset, project page links -->\n"
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
            from domain_router import infer_domain
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

    if language == "zh":
        content = _generate_zh_note(
            paper_id, title, authors, domain, date, scores, abstract,
            arxiv_id, affiliations, conference, pdf_url, related, images,
            local_pdf_rel=local_pdf_rel, math_depth=math_depth,
        )
    else:
        content = _generate_en_note(
            paper_id, title, authors, domain, date, scores, abstract,
            arxiv_id, affiliations, conference, pdf_url, related, images,
            local_pdf_rel=local_pdf_rel, math_depth=math_depth,
        )

    filename = title_to_filename(title)
    # Sanitize domain for directory name
    safe_domain = domain.strip("/\\").replace("..", "") or "Other"
    # Create subfolder matching download_paper structure: domain/title/title.md
    note_dir = os.path.join(output_dir, safe_domain, filename)
    os.makedirs(note_dir, exist_ok=True)
    note_path = os.path.join(note_dir, f"{filename}.md")

    with open(note_path, "w", encoding="utf-8") as f:
        f.write(content)

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
        "方法概述", "实验结果", "深度分析",
        "Method Overview", "Experimental Results", "Deep Analysis",
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
                issues.append(
                    f"Sections '{names[i]}' and '{names[j]}' are identical"
                )

    return {
        "has_issues": len(issues) > 0,
        "issues": issues,
        "placeholder_count": placeholder_count,
    }


# ---------------------------------------------------------------------------
# LLM-powered auto-fill
# ---------------------------------------------------------------------------

_FILL_SYSTEM_PROMPT = """\
You are a research paper analysis assistant. Your task is to fill in ALL
<!-- LLM: ... --> placeholders in a structured markdown note, using the
provided PDF full text as source material.

Rules:
1. Replace each <!-- LLM: ... --> comment with substantive content that
   fulfills the instruction inside the comment.
2. Preserve the surrounding markdown structure — headings, tables, block
   quotes, callouts. Only replace the placeholder comments themselves.
3. Write in the same language as the template (Chinese for zh, English for en).
4. Use LaTeX for mathematical formulas ($...$ inline, $$...$$ block).
5. Be specific — cite numbers, dataset names, method details from the PDF.
6. If the PDF text is insufficient for a section, write what you can and
   append <!-- INCOMPLETE --> after your text.
7. Output the COMPLETE note with all placeholders filled. Do NOT truncate."""


def _resolve_providers() -> list[tuple[str, str, str, str]]:
    """Resolve ordered list of LLM providers to try.

    Each provider is a (format, url, key, model) tuple.  Providers are
    tried in priority order; the first successful call wins.

    Priority:
      1. Explicit SCHOLAR_FILLER_* env vars (user-chosen override)
      2. Anthropic credentials (ANTHROPIC_AUTH_TOKEN / ANTHROPIC_API_KEY)
      3. OpenAI-compatible credentials (SCHOLAR_ROUTER_*, LLM_*, GITHUB_TOKEN)

    Deduplication: same (format, url) pair is only tried once.
    """
    providers: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(fmt: str, url: str, key: str, model: str) -> None:
        signature = (fmt, url.rstrip("/"))
        if signature not in seen and key:
            seen.add(signature)
            providers.append((fmt, url, key, model))

    # --- Priority 1: Explicit SCHOLAR_FILLER_* override ---
    # Only activate if user has explicitly configured at least FORMAT or URL.
    # Otherwise we'd shadow Priority 2/3 with an incomplete config.
    filler_explicit = bool(
        os.getenv("SCHOLAR_FILLER_API_FORMAT")
        or os.getenv("SCHOLAR_FILLER_API_URL")
    )
    if filler_explicit:
        filler_key = (
            os.getenv("SCHOLAR_FILLER_API_KEY")
            or os.getenv("ANTHROPIC_AUTH_TOKEN")
            or os.getenv("ANTHROPIC_API_KEY")
            or ""
        )
        if filler_key:
            filler_fmt = os.getenv("SCHOLAR_FILLER_API_FORMAT", "").lower()
            if filler_fmt not in ("anthropic", "openai"):
                filler_fmt = "openai"  # safe default
            filler_url = os.getenv("SCHOLAR_FILLER_API_URL", "")
            if not filler_url:
                filler_url = (
                    os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
                    if filler_fmt == "anthropic"
                    else "https://api.openai.com/v1"
                )
            filler_model = os.getenv("SCHOLAR_FILLER_MODEL", "")
            if not filler_model:
                filler_model = (
                    os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
                    if filler_fmt == "anthropic"
                    else "gpt-4o-mini"
                )
            _add(filler_fmt, filler_url, filler_key, filler_model)

    # --- Priority 2: Anthropic credentials ---
    anth_key = os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY")
    if anth_key:
        anth_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        anth_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        _add("anthropic", anth_url, anth_key, anth_model)

    # --- Priority 3: OpenAI-compatible credentials ---
    oai_key = (
        os.getenv("SCHOLAR_ROUTER_API_KEY")
        or os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("GITHUB_TOKEN")
        or ""
    )
    if oai_key:
        oai_url = (
            os.getenv("SCHOLAR_ROUTER_API_URL")
            or os.getenv("LLM_API_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        )
        oai_model = (
            os.getenv("SCHOLAR_ROUTER_MODEL")
            or os.getenv("LLM_MODEL")
            or "gpt-4o-mini"
        )
        _add("openai", oai_url, oai_key, oai_model)

    return providers


def _call_llm_anthropic(api_url: str, api_key: str, model: str,
                        system_prompt: str, user_prompt: str) -> str:
    """Call Anthropic /messages endpoint. Returns assistant text."""
    import json as _json

    # Avoid double-appending /messages
    base = api_url.rstrip("/")
    if base.endswith("/messages"):
        url = base
    elif base.endswith("/v1"):
        url = base + "/messages"
    else:
        url = base + "/v1/messages"
    payload = {
        "model": model,
        "max_tokens": 8192,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    req = Request(url, data=_json.dumps(payload).encode("utf-8"),
                  headers=headers, method="POST")
    with urlopen(req, timeout=300) as response:
        data = _json.loads(response.read().decode("utf-8"))

    # Handle API error responses
    if "error" in data:
        err = data["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise RuntimeError(f"Anthropic API error: {msg}")

    # Handle missing content field
    if "content" not in data:
        logger.error("Unexpected Anthropic response (no 'content' key): %s",
                     _json.dumps(data)[:500])
        # Try common proxy wrapper fields
        for alt_key in ("output", "text", "response", "result"):
            if alt_key in data:
                val = data[alt_key]
                if isinstance(val, str):
                    return val.strip()
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict) and item.get("type") == "text":
                            return item["text"].strip()
                        if isinstance(item, str):
                            return item.strip()
        raise KeyError(
            f"Anthropic response missing 'content' key. "
            f"Available keys: {list(data.keys())}. "
            f"Response preview: {_json.dumps(data)[:200]}"
        )

    # Find the first text block (content may start with thinking blocks)
    for block in data["content"]:
        if block.get("type") == "text":
            return block["text"].strip()
    raise KeyError("No text block in Anthropic response")


def _call_llm_openai(api_url: str, api_key: str, model: str,
                     system_prompt: str, user_prompt: str) -> str:
    """Call OpenAI-compatible /chat/completions endpoint. Returns assistant text."""
    import json as _json

    # Avoid double-appending /chat/completions
    base = api_url.rstrip("/")
    if base.endswith("/chat/completions"):
        url = base
    else:
        url = base + "/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 8192,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    req = Request(url, data=_json.dumps(payload).encode("utf-8"),
                  headers=headers, method="POST")
    with urlopen(req, timeout=120) as response:
        data = _json.loads(response.read().decode("utf-8"))

    # Handle API error responses
    if "error" in data:
        err = data["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise RuntimeError(f"OpenAI API error: {msg}")

    if "choices" not in data or not data["choices"]:
        logger.error("Unexpected OpenAI response (no 'choices'): %s",
                     _json.dumps(data)[:500])
        raise KeyError(
            f"OpenAI response has no choices. "
            f"Available keys: {list(data.keys())}. "
            f"Response preview: {_json.dumps(data)[:200]}"
        )

    return data["choices"][0]["message"]["content"].strip()


def fill_note_from_pdf(note_path: str, pdf_text: str) -> dict:
    """Fill <!-- LLM: --> placeholders in a note using PDF text via LLM.

    Automatically discovers available LLM providers from environment
    variables and tries them in priority order until one succeeds.

    Provider priority:
      1. SCHOLAR_FILLER_* explicit override
      2. ANTHROPIC_* credentials
      3. OpenAI-compatible credentials

    Args:
        note_path: Path to the generated markdown note.
        pdf_text: Full text extracted from the PDF.

    Returns:
        Dict with 'status', 'placeholders_filled', 'model_used'.
    """
    content = Path(note_path).read_text(encoding="utf-8")
    placeholder_count = len(re.findall(r"<!--\s*LLM:", content))
    if placeholder_count == 0:
        return {"status": "skipped", "reason": "No placeholders to fill", "placeholders_filled": 0}

    providers = _resolve_providers()
    if not providers:
        return {"status": "skipped", "reason": "No API key configured", "placeholders_filled": 0}

    # Truncate PDF text to avoid token limit
    max_pdf_chars = 60000
    truncated = pdf_text[:max_pdf_chars]
    if len(pdf_text) > max_pdf_chars:
        truncated += "\n\n[... PDF text truncated ...]"

    user_prompt = (
        f"Here is the PDF full text:\n\n---\n{truncated}\n---\n\n"
        f"Now fill ALL <!-- LLM: --> placeholders in this note:\n\n{content}"
    )

    # Try each provider in priority order
    filled_content = None
    used_provider = None
    last_error = None

    for fmt, api_url, key, model in providers:
        try:
            logger.info("Trying LLM fill: %s @ %s (model=%s)", fmt, api_url, model)
            call = _call_llm_anthropic if fmt == "anthropic" else _call_llm_openai
            filled_content = call(api_url, key, model, _FILL_SYSTEM_PROMPT, user_prompt)
            used_provider = (fmt, api_url, model)
            break
        except Exception as exc:
            last_error = exc
            logger.warning("LLM fill failed (%s @ %s): %s", fmt, api_url, exc)
            continue

    if filled_content is None:
        reason = str(last_error) if last_error else "All providers failed"
        return {"status": "error", "reason": reason, "placeholders_filled": 0}

    # Remove markdown code fences if the LLM wrapped its output
    if filled_content.startswith("```markdown\n"):
        filled_content = filled_content[len("```markdown\n"):]
    if filled_content.startswith("```\n"):
        filled_content = filled_content[len("```\n"):]
    if filled_content.endswith("\n```"):
        filled_content = filled_content[:-4]

    remaining = len(re.findall(r"<!--\s*LLM:", filled_content))
    filled_count = placeholder_count - remaining

    # Update frontmatter status
    filled_content = filled_content.replace("status: skeleton", "status: filled", 1)

    Path(note_path).write_text(filled_content, encoding="utf-8")

    return {
        "status": "ok",
        "placeholders_filled": filled_count,
        "placeholders_remaining": remaining,
        "model_used": used_provider[2],
        "api_format": used_provider[0],
    }
