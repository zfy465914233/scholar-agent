#!/usr/bin/env python3
"""Validate a paper note and fail closed on placeholders or weak structure."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"status\s*:\s*skeleton\b", "skeleton_status"),
    (r"\[SCORE\]\s*/\s*10", "placeholder_score"),
    (r"<!--\s*LLM:", "llm_placeholder_comment"),
    (r"PDF\s*片段未直接抽取", "pdf_placeholder_text"),
]

SECTION_ALIASES = {
    "motivation": ["研究动机", "动机", "motivation", "background", "problem setting"],
    "method": ["方法论", "方法", "method", "approach"],
    "dataset": ["数据区间", "数据集", "dataset", "data", "实验设置", "experimental setup"],
    "findings": [
        "核心结论",
        "关键发现",
        "主要结论",
        "主要结果",
        "实验结果",
        "实验与评估",
        "results",
        "findings",
        "实验",
        "评估",
    ],
    "limitations": ["局限性", "局限", "limitations", "caveats", "discussion"],
}

DATASET_FALLBACK_ALIASES = [
    "problem definition",
    "问题定义",
    "task definition",
    "任务定义",
    "evaluation protocol",
    "评测协议",
    "theory",
    "理论",
    "assumption",
    "假设",
    "proof",
    "证明",
    "case study",
    "案例",
    "setting",
    "实验设定",
]

UNKNOWN_VALUES = {"unknown", "tbd", "n/a", "na", "none", "null", "[unknown]"}
# Legitimate math_depth values (shared semantics with paper_analyzer.detect_math_depth).
# "none" means the paper has NO math requirement — it is a valid value, not "unknown".
LEGAL_MATH_DEPTH = {"heavy", "light", "none"}
MIN_SECTION_CHARS = 24

# Regex to detect LaTeX math in markdown
_LATEX_INLINE = re.compile(r"(?<!\$)\$(?!\$).+?\$(?!\$)")
_LATEX_BLOCK = re.compile(r"\$\$.+?\$\$", re.DOTALL)
_LATEX_ENV = re.compile(r"\\begin\{(?:equation|align|gather|multline|eqnarray)")
_MATH_SYMBOL_TABLE = re.compile(
    r"\|.*\$.*\\(?:alpha|beta|gamma|delta|theta|lambda|mu|sigma|omega|mathbb|mathcal|boldsymbol|x?hat|bar|tilde).*\$\s*\|",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--note", required=True, help="Path to the markdown note")
    parser.add_argument(
        "--paper-type",
        default="generic",
        choices=["generic", "empirical", "theory", "survey", "benchmark"],
        help="Paper type specific checks to apply",
    )
    parser.add_argument(
        "--require-frontmatter",
        action="store_true",
        help="Fail if the note does not start with YAML frontmatter",
    )
    parser.add_argument(
        "--require-evidence",
        action="store_true",
        help="Require at least one evidence marker or source identifier",
    )
    parser.add_argument(
        "--dataset-policy",
        default="required",
        choices=["required", "fallback", "auto"],
        help=(
            "required: dataset section is mandatory; "
            "fallback: dataset can be replaced by alternative problem/evaluation/theory section; "
            "auto: use required for empirical/benchmark and fallback for theory/survey/generic"
        ),
    )
    parser.add_argument(
        "--json-indent",
        type=int,
        default=2,
        help="Indentation for JSON output",
    )
    return parser.parse_args()


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def split_frontmatter(text: str) -> tuple[dict[str, str], str, list[str]]:
    errors: list[str] = []
    metadata: dict[str, str] = {}
    body = text
    if not text.startswith("---\n"):
        return metadata, body, errors

    end = text.find("\n---\n", 4)
    if end == -1:
        errors.append("unterminated_frontmatter")
        return metadata, body, errors

    frontmatter_block = text[4:end]
    body = text[end + 5 :]

    for raw_line in frontmatter_block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if match:
            key, value = match.groups()
            metadata[key] = value.strip().strip("\"'")

    duplicate_pattern = re.compile(r"(?m)^---\n[A-Za-z0-9_-]+:\s")
    if duplicate_pattern.search(body):
        errors.append("duplicated_frontmatter")

    return metadata, body, errors


def extract_sections(body: str) -> dict[str, str]:
    """Extract top-level sections, folding deeper headings into their parent.

    Level-1/2 headings (``#``/``##``) define section boundaries; ``###``/``####``
    content folds into the nearest parent section so a section's content isn't
    truncated at its first sub-heading (which previously made method/findings
    look empty). If the note has only level-3+ headings, treat ``###`` as top.
    """
    sections: dict[str, str] = {}
    matches = list(re.finditer(r"(?m)^(#{1,2})\s+(.+?)\s*$", body))
    if not matches:
        matches = list(re.finditer(r"(?m)^(###)\s+(.+?)\s*$", body))
    if not matches:
        return sections

    for index, match in enumerate(matches):
        title = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[title] = body[start:end].strip()
    return sections


def find_section(sections: dict[str, str], aliases: list[str]) -> tuple[str | None, str | None]:
    """Find the best-matching section for a key.

    Prefers an exact title==alias, then a title starting with the alias, then a
    plain substring — so ``方法`` matches ``方法概述`` (starts-with) over
    ``基线方法`` (substring only), letting the main section win over incidental
    look-alikes. Ties broken by shorter title.
    """
    best: tuple[int, str, str] | None = None
    lowered_aliases = [a.lower() for a in aliases]
    for title, content in sections.items():
        lowered = title.lower()
        for alias in lowered_aliases:
            if alias not in lowered:
                continue
            if lowered == alias:
                priority = 0
            elif lowered.startswith(alias):
                priority = 1
            else:
                priority = 2
            if best is None or (priority, len(title)) < (best[0], len(best[1])):
                best = (priority, title, content)
    if best is None:
        return None, None
    return best[1], best[2]


def has_substantive_text(text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) < MIN_SECTION_CHARS:
        return False
    letters = re.findall(r"[A-Za-z\u4e00-\u9fff]", cleaned)
    return len(letters) >= max(12, MIN_SECTION_CHARS // 2)


def collect_forbidden_errors(text: str) -> list[str]:
    errors: list[str] = []
    for pattern, name in FORBIDDEN_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            errors.append(name)
    return errors


def collect_unknown_metadata_errors(metadata: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for key, value in metadata.items():
        normalized = value.strip().lower()
        if normalized in UNKNOWN_VALUES:
            # math_depth has legitimate non-unknown values (heavy/light/none);
            # "none" must not trip the generic blacklist.
            if key == "math_depth" and normalized in LEGAL_MATH_DEPTH:
                continue
            errors.append(f"metadata_unknown:{key}")
    return errors


def validate_core_sections(
    sections: dict[str, str],
    dataset_policy: str,
    body: str,
) -> tuple[list[str], list[str], dict[str, str]]:
    errors: list[str] = []
    warnings: list[str] = []
    resolved: dict[str, str] = {}

    keys = ["motivation", "method", "dataset", "findings", "limitations"]
    if dataset_policy == "fallback":
        keys = ["motivation", "method", "findings", "limitations"]

    for key in keys:
        aliases = SECTION_ALIASES[key]
        title, content = find_section(sections, aliases)
        if title is None or content is None:
            errors.append(f"missing_section:{key}")
            continue
        resolved[key] = title
        if not has_substantive_text(content):
            errors.append(f"thin_section:{key}")

    if dataset_policy == "required":
        title, content = find_section(sections, SECTION_ALIASES["dataset"])
        if title is None or content is None:
            errors.append("missing_section:dataset")
        elif not has_substantive_text(content):
            errors.append("thin_section:dataset")
        else:
            resolved["dataset"] = title
    else:
        title, content = find_section(sections, SECTION_ALIASES["dataset"])
        if title is not None and content is not None and has_substantive_text(content):
            resolved["dataset"] = title
        else:
            fallback_title, fallback_content = find_section(sections, DATASET_FALLBACK_ALIASES)
            if fallback_title is None or fallback_content is None:
                # Secondary fallback: accept strong body-level evidence for non-dataset papers.
                body_marker_pattern = re.compile(
                    r"(?:problem\s+definition|问题定义|task\s+definition|任务定义|"
                    r"evaluation\s+protocol|评测协议|theorem|proof|assumption|"
                    r"理论|假设|benchmark|ablation|case\s+study|案例)",
                    flags=re.IGNORECASE,
                )
                if body_marker_pattern.search(body):
                    warnings.append("dataset_fallback_used_body_markers")
                else:
                    errors.append("missing_section:dataset_or_fallback")
            elif not has_substantive_text(fallback_content):
                errors.append("thin_section:dataset_fallback")
            else:
                resolved["dataset_fallback"] = fallback_title
                warnings.append("dataset_fallback_used")

    return errors, warnings, resolved


def count_quantitative_results(text: str) -> int:
    pattern = re.compile(
        r"(?:\b\d+(?:\.\d+)?\s*(?:%|x|times|pts?|points?)(?![\d.])|"
        r"\b\d+(?:\.\d+)?\b[^\n]{0,12}?\b(?:accuracy|acc|auc|f1|ap|map|precision|recall|sharpe)\b|"
        r"\b(?:AUC|F1|AP|mAP|accuracy|acc|precision|recall|Sharpe)\b[^\n]{0,24}?\d+(?:\.\d+)?)",
        flags=re.IGNORECASE,
    )
    return len(pattern.findall(text))


def type_specific_checks(paper_type: str, sections: dict[str, str], resolved: dict[str, str]) -> list[str]:
    errors: list[str] = []
    combined = "\n".join(sections.values())
    findings_text = ""
    if "findings" in resolved:
        findings_text = sections[resolved["findings"]]

    if paper_type == "empirical" and count_quantitative_results(findings_text or combined) < 2:
        errors.append("empirical_requires_two_quantitative_results")

    if paper_type == "theory":
        theory_markers = ["问题定义", "problem definition", "assumption", "假设", "theorem", "命题", "mechanism"]
        if not any(marker.lower() in combined.lower() for marker in theory_markers):
            errors.append("theory_requires_problem_definition_or_mechanism")

    if paper_type == "survey":
        taxonomy_markers = ["taxonomy", "分类", "framework", "脉络"]
        consensus_markers = ["共识", "consensus", "分歧", "disagreement"]
        if not any(marker.lower() in combined.lower() for marker in taxonomy_markers):
            errors.append("survey_requires_taxonomy")
        if not any(marker.lower() in combined.lower() for marker in consensus_markers):
            errors.append("survey_requires_consensus_or_disagreement")

    if paper_type == "benchmark":
        benchmark_markers = ["baseline", "protocol", "评测协议", "risk", "bias", "偏差"]
        lowered = combined.lower()
        missing = [marker for marker in benchmark_markers if marker.lower() not in lowered]
        if len(missing) == len(benchmark_markers):
            errors.append("benchmark_requires_protocol_baseline_and_risk")

    return errors


def provenance_checks(metadata: dict[str, str], body: str) -> list[str]:
    errors: list[str] = []
    source_keys = {"pdf_path", "source_pdf", "arxiv_id", "paper_id", "doi"}
    has_source_key = any(key in metadata and metadata[key].strip() for key in source_keys)
    evidence_pattern = re.compile(
        r"(?:Figure\s+\d+|Fig\.\s*\d+|Table\s+\d+|Section\s+\d+|Sec\.\s*\d+|"
        r"图\s*\d+|表\s*\d+|第\s*\d+\s*节|p\.\s*\d+|页\s*\d+)",
        flags=re.IGNORECASE,
    )
    has_evidence_marker = bool(evidence_pattern.search(body))
    if not has_source_key and not has_evidence_marker:
        errors.append("missing_evidence_markers")
    return errors


def math_depth_checks(metadata: dict[str, str], body: str, sections: dict[str, str]) -> list[str]:
    """Check that math-heavy papers have LaTeX formulas in the note."""
    errors: list[str] = []
    math_depth = metadata.get("math_depth", "").strip().lower()

    if math_depth not in LEGAL_MATH_DEPTH:
        return errors
    if math_depth == "none":
        return errors  # paper has no math requirement; skip LaTeX/symbol checks

    has_inline = bool(_LATEX_INLINE.search(body))
    has_block = bool(_LATEX_BLOCK.search(body))
    has_env = bool(_LATEX_ENV.search(body))
    has_any_latex = has_inline or has_block or has_env

    if math_depth == "heavy":
        if not has_any_latex:
            errors.append("heavy_math_requires_latex_formulas")
        # Check for symbol definition table
        if not _MATH_SYMBOL_TABLE.search(body):
            # Also accept inline symbol definitions in the method section
            method_text = ""
            for title, content in sections.items():
                if any(kw in title.lower() for kw in ["method", "方法", "模块"]):
                    method_text += content
            symbol_inline = re.compile(
                r"\$\\(?:alpha|beta|gamma|delta|theta|lambda|mu|sigma|omega|mathbb|mathcal|x?hat)\$"
            )
            if not symbol_inline.search(method_text):
                errors.append("heavy_math_requires_symbol_definitions")

    elif math_depth == "light":
        if not has_any_latex:
            errors.append("light_math_requires_latex_formulas")

    return errors


def image_checks(metadata: dict[str, str], body: str) -> list[str]:
    """Check that notes with images directory have embedded image references."""
    warnings: list[str] = []
    # Check if images directory exists relative to the note
    # This is a soft check — just warn if no image embeds found
    has_image_embed = bool(re.search(r"!\[\[images/", body))
    has_image_md = bool(re.search(r"!\[.*\]\(images/", body))
    if not has_image_embed and not has_image_md:
        # Not an error — some papers genuinely have no useful figures
        pass
    return warnings


def _has_prose_paragraph(content: str) -> bool:
    """True if content has >=1 prose paragraph (>50 chars, not table/heading/list/comment)."""
    for para in content.split("\n\n"):
        p = para.strip()
        if (
            p
            and not p.startswith("|")  # table
            and not p.startswith("#")  # heading
            and not p.startswith("-")  # list
            and not p.startswith("<!")  # comment
            and len(p) > 50
        ):
            return True
    return False


def content_density_checks(sections: dict[str, str], paper_type: str) -> list[str]:
    """Check that the MAIN method/findings sections have prose, not just bullets.

    Only the section resolved by ``find_section`` is checked — not every heading
    containing "方法"/"method" (e.g. "基线方法", "方法对比"), which are often
    table/list sections and would falsely trigger lacks_prose.
    """
    errors: list[str] = []

    _method_title, method_content = find_section(sections, SECTION_ALIASES["method"])
    if method_content and not _has_prose_paragraph(method_content):
        errors.append("method_section_lacks_prose")

    _findings_title, findings_content = find_section(sections, SECTION_ALIASES["findings"])
    if findings_content:
        has_table = bool(re.search(r"\|.+\|.+\|", findings_content))
        if not has_table and not _has_prose_paragraph(findings_content):
            errors.append("findings_section_lacks_substance")

    return errors


def validate_note(
    source: Path | str,
    paper_type: str = "generic",
    dataset_policy: str = "auto",
    require_frontmatter: bool = False,
    require_evidence: bool = False,
) -> dict:
    """Validate a note and return a structured result dict.

    Programmatic entry point (no CLI/argparse, no printing). ``main()``
    delegates here. ``source`` accepts a ``Path`` (read from disk, fail with
    ``note_not_found`` if missing) or raw note ``str`` text.
    """
    if isinstance(source, Path):
        note_path = source.expanduser().resolve()
        if not note_path.exists():
            return {
                "ok": False,
                "note": str(note_path),
                "paper_type": paper_type,
                "errors": ["note_not_found"],
                "warnings": [],
                "summary": {},
            }
        text = load_text(note_path)
        note_str = str(note_path)
    else:
        text = source
        note_str = ""

    metadata, body, frontmatter_errors = split_frontmatter(text)
    sections = extract_sections(body)

    effective_dataset_policy = dataset_policy
    if dataset_policy == "auto":
        effective_dataset_policy = "required" if paper_type in {"empirical", "benchmark"} else "fallback"

    errors: list[str] = []
    warnings: list[str] = []
    errors.extend(frontmatter_errors)
    errors.extend(collect_forbidden_errors(text))
    errors.extend(collect_unknown_metadata_errors(metadata))

    if require_frontmatter and not metadata:
        errors.append("missing_frontmatter")

    if not sections:
        errors.append("no_markdown_sections_found")
    else:
        core_errors, core_warnings, resolved = validate_core_sections(sections, effective_dataset_policy, body)
        errors.extend(core_errors)
        warnings.extend(core_warnings)
        errors.extend(type_specific_checks(paper_type, sections, resolved))

    if require_evidence:
        errors.extend(provenance_checks(metadata, body))

    # Math depth checks (always on — reads math_depth from frontmatter)
    errors.extend(math_depth_checks(metadata, body, sections))

    # Content density checks
    if sections:
        errors.extend(content_density_checks(sections, paper_type))

    return {
        "ok": not errors,
        "note": note_str,
        "paper_type": paper_type,
        "errors": sorted(set(errors)),
        "warnings": warnings,
        "summary": {
            "has_frontmatter": bool(metadata),
            "section_count": len(sections),
            "metadata_keys": sorted(metadata.keys()),
            "dataset_policy": effective_dataset_policy,
        },
    }


def main() -> int:
    args = parse_args()
    result = validate_note(
        Path(args.note),
        paper_type=args.paper_type,
        dataset_policy=args.dataset_policy,
        require_frontmatter=args.require_frontmatter,
        require_evidence=args.require_evidence,
    )
    print(json.dumps(result, ensure_ascii=False, indent=args.json_indent))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
