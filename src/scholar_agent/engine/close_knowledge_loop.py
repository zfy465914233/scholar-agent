"""Close the knowledge loop: research → synthesize → distill → promote → reindex.

This script takes a research evidence JSON file and a structured answer JSON,
then:
  1. Builds an answer context from the evidence
  2. Distills the answer into a draft knowledge card
  3. Promotes the draft into the local knowledge tree
  4. Rebuilds the index so the new knowledge is immediately retrievable

Usage:
  python close_knowledge_loop.py \\
    --research /tmp/research.json \\
    --answer /tmp/answer.json \\
    --query "XGBoost for QPE radar rainfall estimation"
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Import config helpers
from scholar_agent.engine.common import atomic_write_text, extract_entities, get_package_data_path, safe_slug

ANSWER_SCHEMA_PATH = get_package_data_path("schemas", "answer.schema.json")

from scholar_agent.engine.domain_router import infer_domain as _infer_domain
from scholar_agent.engine.domain_router import infer_domain_decision as _infer_domain_decision
from scholar_agent.engine.local_retrieve import retrieve as bm25_retrieve
from scholar_agent.engine.scholar_config import get_index_path, get_knowledge_dir

logger = logging.getLogger(__name__)

DEFAULT_KNOWLEDGE_ROOT = get_knowledge_dir()
DEFAULT_INDEX = get_index_path()


def _normalize_answer_markdown(text: str) -> str:
    """Ensure markdown headers are on their own lines with proper spacing.

    Skips content inside fenced code blocks (``` ... ```).
    """
    if not text:
        return text
    import re

    # Split into segments: alternating prose / code-block
    parts = re.split(r"(```.*?```)", text, flags=re.DOTALL)
    for i in range(0, len(parts), 2):
        seg = parts[i]
        # Ensure headers start at beginning of a line. (?<!#) prevents matching
        # a header from its 2nd+ '#', which would split an in-place ## heading.
        seg = re.sub(r"(?<!^)(?<!\n)(?<!#)(#{1,6}\s)", r"\n\1", seg, flags=re.MULTILINE)
        # Ensure a blank line before headers
        seg = re.sub(r"([^\n])\n(#{1,6}\s)", r"\1\n\n\2", seg)
        # Collapse 3+ consecutive blank lines into 2
        seg = re.sub(r"\n{4,}", "\n\n\n", seg)
        # F1: demote every answer header so it sits below the card's own
        # sections (## 回答 / ## 支撑论据) and never rivals the card H1.
        # Done last so the structural fixes above operate on the original
        # levels; min level 3 => even a bare # in the answer becomes ###.
        seg = re.sub(
            r"^(#{1,6})(\s)",
            lambda m: "#" * min(max(len(m.group(1)) + 1, 3), 6) + m.group(2),
            seg,
            flags=re.MULTILINE,
        )
        parts[i] = seg
    return "".join(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Close the knowledge loop.")
    parser.add_argument("--query", required=True, help="The original query.")
    parser.add_argument(
        "--research",
        type=Path,
        help="Path to research evidence JSON from research_harness.py.",
    )
    parser.add_argument(
        "--answer",
        type=Path,
        required=True,
        help="Path to structured answer JSON.",
    )
    parser.add_argument(
        "--knowledge-root",
        type=Path,
        default=DEFAULT_KNOWLEDGE_ROOT,
    )
    parser.add_argument(
        "--index-output",
        type=Path,
        default=DEFAULT_INDEX,
    )
    return parser.parse_args()


def infer_domain(query: str) -> str:
    """Backward-compatible wrapper: returns only the slug string."""
    slug, _path = _infer_domain(query, DEFAULT_KNOWLEDGE_ROOT)
    return slug


def collect_source_urls(research_data: dict | None) -> list[str]:
    """Extract source URLs from research evidence."""
    urls: list[str] = []
    if research_data is None:
        return urls
    for item in research_data.get("evidence", []):
        url = item.get("url", "")
        if url and url not in urls:
            urls.append(url)
    return urls


def check_contradictions(
    query: str,
    claims: list[dict],
    index_path: Path,
    *,
    current_domain: str = "",
) -> list[dict]:
    """Check new claims against existing cards for potential contradictions.

    Uses BM25 to find similar cards, then surfaces overlapping claims.
    Returns a list of {card_id, card_title, their_claims} for related cards.
    When *current_domain* is set, same-domain cards are preferred; cross-domain
    cards require a higher similarity threshold (>= 15) to be included.
    """
    if not index_path.exists():
        return []

    try:
        results = bm25_retrieve(query, index_path, limit=8)
    except Exception:
        return []

    hits = results.get("results", [])
    same_domain: list[dict] = []
    cross_domain: list[dict] = []
    for hit in hits:
        score = hit.get("score", 0)
        if score < 1.0:
            continue
        entry = {
            "card_id": hit.get("doc_id", ""),
            "title": hit.get("title", ""),
            "score": score,
        }
        hit_domain = hit.get("topic", "") or ""
        if current_domain and hit_domain == current_domain:
            same_domain.append(entry)
        elif current_domain and score >= 15.0:
            cross_domain.append(entry)
        elif not current_domain:
            same_domain.append(entry)

    related = same_domain + cross_domain
    return related[:3]


# Keywords suggesting an image is a useful diagram/chart rather than a photo
_CONTENT_IMAGE_KEYWORDS = (
    "diagram",
    "chart",
    "graph",
    "figure",
    "plot",
    "flow",
    "architecture",
    "pipeline",
    "framework",
    "structure",
    "schematic",
    "overview",
    "comparison",
    "model",
    "process",
    "algorithm",
    "table",
    "results",
    "performance",
    "heatmap",
    "confusion",
    "分布",
    "流程",
    "架构",
    "对比",
    "示意图",
    "模型",
    "图",
)


def collect_source_images(research_data: dict | None) -> list[dict[str, str]]:
    """Collect relevant source images from research evidence.

    Filters images by alt text heuristics: keeps those whose alt text or
    filename suggests they are diagrams, charts, or figures — not decorative.
    Deduplicates by URL. Returns up to 6 images.
    """
    seen_urls: set[str] = set()
    images: list[dict[str, str]] = []
    if research_data is None:
        return images
    for item in research_data.get("evidence", []):
        for img in item.get("source_images", []):
            url = img.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            alt = img.get("alt_text", "").lower()
            src = url.lower()
            # Accept if alt text or filename contains content-related keywords
            if any(kw in alt or kw in src for kw in _CONTENT_IMAGE_KEYWORDS):
                images.append(img)
            elif alt and len(alt) > 5:
                # Has meaningful alt text but no keyword match — keep as borderline
                images.append(img)
    return images[:6]


def _build_evidence_map(research_data: dict | None) -> dict[str, dict[str, str]]:
    """F3: ``{evidence_id: {url, label}}`` from research evidence.

    Lets ``## 支撑论据`` render evidence_ids as readable source refs instead
    of opaque ids; label falls back to the url when no title is present.
    """
    mapping: dict[str, dict[str, str]] = {}
    if not research_data:
        return mapping
    for idx, item in enumerate(research_data.get("evidence", []), 1):
        eid = item.get("id") or f"e{idx}"
        url = item.get("url", "")
        mapping[eid] = {"url": url, "label": item.get("title", "") or url}
    return mapping


def _evidence_map_from_sources(sources) -> dict[str, dict[str, str]]:
    """F3 fallback: when there is no research_data (e.g. save_research path),
    map each source URL to itself so claims whose ``evidence_ids`` cite a source
    URL still render as source links instead of opaque bare ids. Label is the
    URL's host (falls back to the full URL) to keep the rendered ref concise.
    """
    from urllib.parse import urlparse

    mapping: dict[str, dict[str, str]] = {}
    for url in sources or []:
        url = str(url).strip()
        if not url:
            continue
        try:
            host = urlparse(url).netloc
            label = host or url
        except Exception:
            label = url
        mapping[url] = {"url": url, "label": label}
    return mapping


def validate_answer_schema(answer_data: dict) -> list[str]:
    """Validate answer_data against schemas/answer.schema.json.

    Returns a list of warning messages. Empty list means valid.
    Does not abort — warnings are informational only.
    """
    if not ANSWER_SCHEMA_PATH.exists():
        return ["Answer schema file not found, skipping validation"]

    schema = json.loads(ANSWER_SCHEMA_PATH.read_text(encoding="utf-8"))
    warnings: list[str] = []
    required = schema.get("required", [])
    props = schema.get("properties", {})

    # Check required fields
    for field in required:
        if field not in answer_data:
            warnings.append(f"Missing required field: {field}")
        elif field == "answer" and not isinstance(answer_data[field], str):
            warnings.append(f"Field 'answer' must be a string, got {type(answer_data[field]).__name__}")
        elif field == "supporting_claims":
            if not isinstance(answer_data[field], list):
                warnings.append("Field 'supporting_claims' must be an array")
            else:
                claim_schema = props.get("supporting_claims", {}).get("items", {})
                claim_required = claim_schema.get("required", [])
                for i, claim in enumerate(answer_data[field]):
                    if not isinstance(claim, dict):
                        warnings.append(f"supporting_claims[{i}] must be an object")
                        continue
                    for cf in claim_required:
                        if cf not in claim:
                            warnings.append(f"supporting_claims[{i}] missing required field: {cf}")
                    conf = claim.get("confidence", "")
                    if conf and conf not in ("high", "medium", "low"):
                        warnings.append(f"supporting_claims[{i}] confidence must be high/medium/low, got '{conf}'")

    return warnings


# ---------------------------------------------------------------------------
# Quality gate thresholds
# ---------------------------------------------------------------------------
QUALITY_THRESHOLD_SAVE_RESEARCH = 0.30
QUALITY_THRESHOLD_CAPTURE_ANSWER = 0.20
# Above this quality score, a freshly-saved card auto-promotes from draft to
# reviewed (it cleared the gate AND is substantively rich). trusted remains a
# manual / usage-driven step — so the knowledge base self-refines instead of
# every card sitting at draft forever.
REVIEWED_QUALITY_THRESHOLD = 0.6


def confidence_from_quality(quality_result: dict) -> str:
    """Map a quality_score_answer_data result to a confidence label."""
    if quality_result.get("passed") and quality_result.get("score", 0.0) >= REVIEWED_QUALITY_THRESHOLD:
        return "reviewed"
    return "draft"


MIN_ANSWER_LENGTH_SAVE = 200
MIN_ANSWER_LENGTH_CAPTURE = 150
MIN_CLAIMS_SAVE = 1
MIN_CLAIM_TEXT_LENGTH = 20


def quality_score_answer_data(answer_data: dict, source: str = "save_research") -> dict:
    """Score answer_data quality and return a structured result.

    Returns dict with:
      - score: float 0.0-1.0
      - passed: bool
      - violations: list[str] describing each failure
      - details: dict of individual metric scores

    Scoring formula (max 1.0):
      - answer_length_score (0-0.3): min(answer_len / 500, 1.0) * 0.3
      - claims_score (0-0.3): min(num_claims / 3, 1.0) * 0.3
      - claim_depth_score (0-0.2): min(avg_claim_len / 50, 1.0) * 0.2
      - structural_richness (0-0.2): 0.05 per non-empty optional field
    """
    if source == "capture_answer":
        threshold = QUALITY_THRESHOLD_CAPTURE_ANSWER
        min_answer_len = MIN_ANSWER_LENGTH_CAPTURE
        min_claims = 0
    else:
        threshold = QUALITY_THRESHOLD_SAVE_RESEARCH
        min_answer_len = MIN_ANSWER_LENGTH_SAVE
        min_claims = MIN_CLAIMS_SAVE

    violations: list[str] = []
    answer_text = str(answer_data.get("answer", ""))
    answer_len = len(answer_text)
    claims = answer_data.get("supporting_claims", [])
    if not isinstance(claims, list):
        claims = []

    # --- Hard constraints (violations regardless of score) ---
    if answer_len < min_answer_len:
        violations.append(f"answer is {answer_len} characters, minimum is {min_answer_len}")
    if len(claims) < min_claims:
        violations.append(f"supporting_claims has {len(claims)} items, minimum is {min_claims}")
    for i, claim in enumerate(claims):
        if isinstance(claim, dict):
            claim_text = str(claim.get("claim", ""))
            if len(claim_text) < MIN_CLAIM_TEXT_LENGTH:
                violations.append(
                    f"supporting_claims[{i}].claim is {len(claim_text)} characters, minimum is {MIN_CLAIM_TEXT_LENGTH}"
                )

    # --- Soft scoring ---
    answer_length_score = min(answer_len / 500, 1.0) * 0.3
    claims_score = min(len(claims) / 3, 1.0) * 0.3
    avg_claim_len = sum(len(str(c.get("claim", ""))) for c in claims if isinstance(c, dict)) / max(len(claims), 1)
    claim_depth_score = min(avg_claim_len / 50, 1.0) * 0.2

    optional_fields = ["inferences", "uncertainty", "missing_evidence", "suggested_next_steps"]
    filled_optional = sum(1 for f in optional_fields if answer_data.get(f) and len(answer_data[f]) > 0)
    structural_richness = filled_optional * 0.05

    score = round(
        answer_length_score + claims_score + claim_depth_score + structural_richness,
        4,
    )
    passed = score >= threshold and len(violations) == 0

    return {
        "score": score,
        "passed": passed,
        "violations": violations,
        "details": {
            "answer_length_score": round(answer_length_score, 4),
            "claims_score": round(claims_score, 4),
            "claim_depth_score": round(claim_depth_score, 4),
            "structural_richness": round(structural_richness, 4),
            "answer_length": answer_len,
            "num_claims": len(claims),
            "filled_optional_fields": filled_optional,
        },
    }


def _append_visual_aids(lines: list[str], aids: list[dict]) -> None:
    """Render a list of visual aids into the card lines."""
    if not aids:
        return
    for va in aids:
        va_type = va.get("type", "")
        content = va.get("content", "")
        caption = va.get("caption", "")
        alt_text = va.get("alt_text", caption)
        if va_type == "mermaid":
            lines.append(f"**{caption}**")
            lines.append("```mermaid")
            lines.append(content)
            lines.append("```")
        elif va_type in ("image_url", "image_path"):
            lines.append(f"![{alt_text}]({content})")
            lines.append(f"*{caption}*")
        lines.append("")


def _infer_card_type(query: str, answer_data: dict) -> str:
    """Infer card type from query and answer content.

    Returns 'engineering' for how-to/implementation content backed by structured
    steps, 'method' for other procedural content, otherwise 'knowledge'.
    An explicit answer_data['card_type'] overrides inference.
    """
    explicit = str(answer_data.get("card_type", "")).strip().lower()
    if explicit in ("engineering", "method", "knowledge"):
        return explicit

    normalized = query.lower().strip()

    # Engineering: concrete implementation/landing content with structured steps.
    engineering_keywords = (
        "how to ",
        "implement",
        "deploy",
        "install",
        "configure",
        "setup",
        "落地",
        "实现",
        "部署",
        "安装",
    )
    has_engineering_kw = any(kw in normalized for kw in engineering_keywords)
    has_steps = bool(answer_data.get("implementation_steps"))
    if has_engineering_kw and has_steps:
        return "engineering"

    procedural_keywords = (
        "how to ",
        "implement",
        "deploy",
        "train",
        "build",
        "configure",
        "setup",
        "install",
        "run ",
        "optimize",
        "tune ",
        "debug",
        "fix ",
        "procedure",
        "algorithm",
    )
    if any(kw in normalized for kw in procedural_keywords):
        return "method"
    # Check if answer contains step-by-step content
    answer = str(answer_data.get("answer", "")).lower()
    step_markers = ("step 1", "step 2", "first,", "then,", "procedure:", "algorithm:")
    if any(m in answer for m in step_markers):
        return "method"
    return "knowledge"


_CARD_TYPE_PREFIX = {"method": "method", "engineering": "engineering"}


def _card_note_label(card_type: str) -> str:
    """Return the human-readable note label for a card type."""
    if card_type == "method":
        return "Method Note"
    if card_type == "engineering":
        return "Engineering Playbook"
    return "Knowledge Note"


def _card_id(card_type: str, slug: str) -> str:
    """Return the canonical id for a generated card."""
    prefix = _CARD_TYPE_PREFIX.get(card_type, "knowledge")
    return f"{prefix}-{slug}"


def _card_note_tag(card_type: str) -> str:
    """Return the canonical note tag for a card type."""
    prefix = _CARD_TYPE_PREFIX.get(card_type, "knowledge")
    return f"{prefix}-note"


def _resolve_card_metadata(
    query: str,
    answer_data: dict,
    knowledge_root: Path,
    domain_override: str | None,
) -> dict:
    """Resolve domain, type, slug, and other card metadata."""
    card_summary = str(answer_data.get("answer", ""))[:500]
    routing = _infer_domain_decision(
        query,
        knowledge_root,
        card_title=query,
        card_summary=card_summary,
        domain_override=domain_override,
    )
    card_type = _infer_card_type(query, answer_data)
    slug = safe_slug(query)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "major_domain": str(routing["major_domain"]),
        "topic": str(routing.get("subdomain", "")).strip(),
        "output_dir": Path(str(routing["output_path"])),
        "card_type": card_type,
        "slug": slug,
        "now": now,
        "card_id": _card_id(card_type, slug),
        "note_label": _card_note_label(card_type),
    }


def _collect_tags(query: str, answer_data: dict, major_domain: str, topic: str, card_type: str) -> list[str]:
    """Infer tags from query, domain, and answer_data."""
    base_tags = [_card_note_tag(card_type), major_domain]
    if topic:
        base_tags.append(topic)
    query_lower = query.lower()
    for keyword, tag in [
        ("xgboost", "xgboost"),
        ("random forest", "random-forest"),
        ("cnn", "cnn"),
        ("lstm", "lstm"),
        ("transformer", "transformer"),
        ("qpe", "ml-qpe"),
        ("radar", "radar"),
        ("rainfall", "rainfall"),
        ("precipitation", "precipitation"),
        ("markov", "markov-chain"),
        ("quantum", "quantum"),
        ("quantization", "quantization"),
    ]:
        if keyword in query_lower and tag not in base_tags:
            base_tags.append(tag)
    for extra_tag in answer_data.get("tags", []):
        if extra_tag and extra_tag not in base_tags:
            base_tags.append(extra_tag)
    return base_tags


def _index_visual_aids(visual_aids: list[dict]) -> dict[str | None, list[dict]]:
    """Group visual aids by their target section."""
    va_by_section: dict[str | None, list[dict]] = {}
    for va in visual_aids:
        if not isinstance(va, dict):
            continue
        section = va.get("after_section") or None
        va_by_section.setdefault(section, []).append(va)
    return va_by_section


def _extract_source_years_list(answer_data: dict, source_urls: list[str]) -> list[int]:
    """F4/G4: all candidate source years found in the answer + sources.

    Prefers explicit 4-digit years; falls back to the arxiv-id prefix
    (YYMM -> 20YY). Returns the years sorted ascending (deduped), or [].
    Shared by ``_extract_source_year`` (earliest, single-value frontmatter) and
    ``_build_frontmatter`` (source_years range + info_freshness) so the regex is
    evaluated only once per card.
    """
    import re

    blob = " ".join([str(answer_data.get("answer", "")), *source_urls])
    years = {int(m) for m in re.findall(r"\b(?:19|20)\d{2}\b", blob)}
    if not years:
        for prefix in re.findall(r"\b(\d{2})\d{2}\.\d{4,5}\b", blob):
            y = 2000 + int(prefix)
            if 1990 <= y <= 2030:
                years.add(y)
    return sorted(years)


def _extract_source_year(answer_data: dict, source_urls: list[str]) -> str:
    """F4: best-effort earliest source year for freshness tracking.

    Thin wrapper over ``_extract_source_years_list``; returns '' when none found.
    """
    years = _extract_source_years_list(answer_data, source_urls)
    return str(years[0]) if years else ""


# Domains whose knowledge changes fast (sub-year staleness, mirrors
# knowledge_lifecycle._DOMAIN_FRESHNESS_YEARS). Kept inline to avoid a circular
# import; both lists must stay in sync.
_FAST_CHANGE_DOMAINS = {
    "ai",
    "llm",
    "llm-agents",
    "machine-learning",
    "ml",
    "deep-learning",
    "transformers",
}


def _format_source_years(years: list[int], now: str) -> str:
    """G4: render the source_years frontmatter value.

    Empty -> 'unknown'. Single year -> 'YYYY'. Multiple -> 'min~max'.
    ``now`` (YYYY-MM-DD) is accepted for symmetry but not used here; the range
    is bounded by the years actually found in the sources.
    """
    del now  # accepted for call-site symmetry; range uses only found years
    if not years:
        return "unknown"
    if len(years) == 1:
        return str(years[0])
    return f"{years[0]}~{years[-1]}"


def _build_info_freshness(years: list[int], domain: str, now: str) -> str:
    """G4: one-line freshness description for the info_freshness field.

    Combines the latest covered year with a domain-aware review cadence hint:
    fast-changing domains (AI/ML/LLM) prompt more frequent re-verification.
    """
    now_year = int(now[:4]) if now and now[:4].isdigit() else None
    if years:
        latest = years[-1]
        coverage = f"覆盖到 {latest}"
        if now_year is not None and latest < now_year:
            coverage += f"(距今 {now_year - latest} 年)"
    else:
        coverage = "未标定源年份"
    key = (domain or "").strip().lower()
    cadence = "该领域变化较快，建议每 6 个月复核一次" if key in _FAST_CHANGE_DOMAINS else "该领域变化较慢，建议定期复核"
    return f"{coverage}；{cadence}"


def _build_frontmatter(
    card_id: str,
    note_label: str,
    query: str,
    card_type: str,
    major_domain: str,
    topic: str,
    tags: list[str],
    source_urls: list[str],
    now: str,
    answer_data: dict,
    confidence: str = "draft",
) -> list[str]:
    """Build the YAML frontmatter and card header lines."""
    card_language = answer_data.get("language", "zh")
    lines = [
        "---",
        f"id: {json.dumps(card_id, ensure_ascii=False)}",
        f"title: {json.dumps(f'{note_label} — {query}', ensure_ascii=False)}",
        f"type: {card_type}",
        f"domain: {major_domain}",
        "tags:",
    ]
    effective_topic = topic or major_domain
    if effective_topic:
        lines.insert(len(lines) - 1, f"topic: {json.dumps(effective_topic, ensure_ascii=False)}")
    for tag in tags:
        lines.append(f"  - {tag}")
    if source_urls:
        lines.append("source_refs:")
        for url in source_urls[:10]:
            lines.append(f"  - {url}")
    card_label = "知识卡片" if card_type == "knowledge" else "方法卡片"
    # F4/G4: record source vintage for freshness tracking. Compute the year list
    # once and reuse for source_date (single year) + source_years (range) +
    # info_freshness (prose), so the regex is not re-evaluated.
    source_years_list = _extract_source_years_list(answer_data, source_urls)
    source_date = str(source_years_list[0]) if source_years_list else ""
    fm_block = [
        f"confidence: {confidence}",
        f"created_at: {now}",
        f"updated_at: {now}",
    ]
    if source_date:
        fm_block.append(f"source_date: {source_date}")
    # G4: source_years range (min~max, or single year) for freshness overview.
    source_years_field = _format_source_years(source_years_list, now)
    fm_block.append(f"source_years: {json.dumps(source_years_field, ensure_ascii=False)}")
    # G4: human-readable freshness hint; varies by domain change-rate.
    info_freshness = _build_info_freshness(source_years_list, major_domain, now)
    fm_block.append(f"info_freshness: {json.dumps(info_freshness, ensure_ascii=False)}")
    # G4: card version — new cards start at 1.0 (incremental updates bump it).
    fm_block.append('version: "1.0"')
    fm_block.extend(
        [
            "origin: web_research_with_synthesis",
            "review_status: draft",
            f'language: "{card_language}"',
            "---",
            "",
            f"# {note_label} — {query}",
            "",
            f"> **{card_label}** | scholar-agent",
            ">",
        ]
    )
    lines.extend(fm_block)
    if source_urls:
        lines.append(f"> 主要参考：{', '.join(source_urls[:5])}")
    lines.extend(
        [
            ">",
            "---",
            "",
        ]
    )
    return lines


def _build_toc(
    claims: list,
    inferences: list,
    uncertainties: list,
    missing: list,
    next_steps: list,
    card_type: str,
    expected_output: str,
    example: str,
    unplaced_aids: list[dict],
    source_images: list[dict],
    prerequisites: list | None = None,
    implementation_steps: list | None = None,
    verification: str = "",
    pitfalls: list | None = None,
    rollback: str = "",
) -> list[str]:
    """Build the table-of-contents section."""
    entries = []
    entries.append("1. [问题](#问题)")
    entries.append("2. [回答](#回答)")
    idx = 3
    if claims:
        entries.append(f"{idx}. [支撑论据](#支撑论据)")
        idx += 1
    if inferences:
        entries.append(f"{idx}. [推论](#推论)")
        idx += 1
    if uncertainties:
        entries.append(f"{idx}. [不确定性](#不确定性)")
        idx += 1
    if missing:
        entries.append(f"{idx}. [缺失证据](#缺失证据)")
        idx += 1
    if next_steps:
        entries.append(f"{idx}. [建议后续步骤](#建议后续步骤)")
        idx += 1
    if card_type == "method":
        if expected_output:
            entries.append(f"{idx}. [预期输出](#预期输出)")
            idx += 1
        if example:
            entries.append(f"{idx}. [具体示例](#具体示例)")
            idx += 1
    if card_type == "engineering":
        if prerequisites:
            entries.append(f"{idx}. [前置条件](#前置条件)")
            idx += 1
        if implementation_steps:
            entries.append(f"{idx}. [实现步骤](#实现步骤)")
            idx += 1
        if verification:
            entries.append(f"{idx}. [验收标准](#验收标准)")
            idx += 1
        if pitfalls:
            entries.append(f"{idx}. [陷阱与注意](#陷阱与注意)")
            idx += 1
        if rollback:
            entries.append(f"{idx}. [回滚方案](#回滚方案)")
            idx += 1
    if unplaced_aids:
        entries.append(f"{idx}. [可视化辅助](#可视化辅助)")
        idx += 1
    if source_images:
        entries.append(f"{idx}. [来源图片](#来源图片)")
        idx += 1
    entries.append(f"{idx}. [参考文献](#参考文献)")
    idx += 1
    entries.append(f"{idx}. [See Also](#see-also)")
    return ["## 目录", "", *entries, "", "---", ""]


def _build_body_sections(
    query: str,
    main_answer: str,
    claims: list,
    inferences: list,
    uncertainties: list,
    missing: list,
    next_steps: list,
    card_type: str,
    expected_output: str,
    example: str,
    va_by_section: dict[str | None, list[dict]],
    prerequisites: list | None = None,
    implementation_steps: list | None = None,
    verification: str = "",
    pitfalls: list | None = None,
    rollback: str = "",
    evidence_map: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    """Build the main body sections (answer, claims, inferences, etc.)."""
    lines: list[str] = []

    lines.extend(["## 问题", "", query, ""])
    lines.extend(["## 回答", ""])
    lines.extend(main_answer.splitlines())
    lines.append("")
    _append_visual_aids(lines, va_by_section.get("answer", []))

    if claims:
        lines.extend(["## 支撑论据", ""])
        emap = evidence_map or {}
        for c in claims:
            if isinstance(c, dict):
                claim_text = c.get("claim", "")
                conf = c.get("confidence", "")
                ids = c.get("evidence_ids", [])
                lines.append(f"- **[{conf}]** {claim_text}")
                # F3: resolve evidence_ids to readable source links (arxiv
                # URLs become [[wikilinks]] to paper-notes via E1).
                refs = [f"[{emap[i]['label']}]({emap[i]['url']})" for i in ids if i in emap and emap[i].get("url")]
                if refs:
                    lines.append(f"  - 来源：{', '.join(refs)}")
                elif ids:
                    lines.append(f"  - 来源：{', '.join(ids)}（详见参考文献）")
            else:
                lines.append(f"- {c}")
        lines.append("")
    _append_visual_aids(lines, va_by_section.get("supporting_claims", []))

    if inferences:
        lines.extend(["## 推论", ""])
        for inf in inferences:
            lines.append(f"- {inf}")
        lines.append("")
    _append_visual_aids(lines, va_by_section.get("inferences", []))

    if uncertainties:
        lines.extend(["## 不确定性", ""])
        for u in uncertainties:
            lines.append(f"- {u}")
        lines.append("")
    _append_visual_aids(lines, va_by_section.get("uncertainty", []))

    if missing:
        lines.extend(["## 缺失证据", ""])
        for m in missing:
            lines.append(f"- {m}")
        lines.append("")
    _append_visual_aids(lines, va_by_section.get("missing_evidence", []))

    if next_steps:
        lines.extend(["## 建议后续步骤", ""])
        for s in next_steps:
            lines.append(f"- {s}")
        lines.append("")
    _append_visual_aids(lines, va_by_section.get("suggested_next_steps", []))

    if card_type == "method":
        if expected_output:
            lines.extend(["## 预期输出", "", expected_output, ""])
        if example:
            lines.extend(["## 具体示例", "", example, ""])

    if card_type == "engineering":
        if prerequisites:
            lines.extend(["## 前置条件", ""])
            for p in prerequisites:
                lines.append(f"- {p}")
            lines.append("")
        if implementation_steps:
            lines.extend(["## 实现步骤", ""])
            for i, st in enumerate(implementation_steps, 1):
                if isinstance(st, dict):
                    desc = st.get("step", f"步骤 {i}")
                    lines.append(f"### 步骤 {i}：{desc}")
                    lines.append("")
                    files = st.get("files") or []
                    if files:
                        lines.append("**涉及文件**：" + ", ".join(f"`{f}`" for f in files))
                        lines.append("")
                    commands = st.get("commands") or []
                    if commands:
                        lines.extend(["```bash", *commands, "```", ""])
                    code = st.get("code", "")
                    if code:
                        lines.extend(["```python", code, "```", ""])
                else:
                    lines.append(f"{i}. {st}")
                    lines.append("")
            _append_visual_aids(lines, va_by_section.get("implementation_steps", []))
        if verification:
            lines.extend(["## 验收标准", "", verification, ""])
        if pitfalls:
            lines.extend(["## 陷阱与注意", ""])
            for pit in pitfalls:
                lines.append(f"- {pit}")
            lines.append("")
        if rollback:
            lines.extend(["## 回滚方案", "", rollback, ""])

    return lines


def _build_footer(
    unplaced_aids: list[dict],
    source_images: list[dict],
    research_data: dict | None,
    full_text: str,
    source_urls: list[str],
    query: str,
    claims: list,
    major_domain: str,
    index_path: Path,
    now: str,
    card_label: str,
) -> list[str]:
    """Build footer sections: visual aids, images, entities, references, see-also."""
    lines: list[str] = []

    if unplaced_aids:
        lines.extend(["## 可视化辅助", ""])
        _append_visual_aids(lines, unplaced_aids)

    if source_images:
        lines.extend(["## 来源图片", ""])
        for img in source_images:
            url = img.get("url", "")
            alt = img.get("alt_text", "") or img.get("title", "") or "Source image"
            source_url = ""
            if research_data:
                for item in research_data.get("evidence", []):
                    for si in item.get("source_images", []):
                        if si.get("url") == url:
                            source_url = item.get("url", "")
                            break
            lines.append(f"![{alt}]({url})")
            if source_url:
                lines.append(f"*{alt} — [source]({source_url})*")
            else:
                lines.append(f"*{alt}*")
            lines.append("")

    entities = extract_entities(full_text)
    if entities:
        lines.extend(["## Entities", ""])
        for entity in entities[:15]:
            entity_slug = safe_slug(entity)
            lines.append(f"- [[{entity_slug}|{entity}]]")
        lines.append("")

    if source_urls:
        lines.extend(["## 参考文献", ""])
        url_title_map: dict[str, str] = {}
        if research_data:
            for item in research_data.get("evidence", []):
                u = item.get("url", "")
                t = item.get("title", "")
                if u and t:
                    url_title_map[u] = t
        for i, url in enumerate(source_urls, 1):
            title = url_title_map.get(url, "")
            if title:
                lines.append(f"{i}. [{title}]({url})")
            else:
                lines.append(f"{i}. [{url}]({url})")
        lines.extend(["", "---", ""])

    lines.extend(["## See Also", ""])
    related = check_contradictions(query, claims, index_path, current_domain=major_domain)
    if related:
        for r in related:
            lines.append(f"- [[{r['card_id']}]] — {r['title']} (similarity: {r['score']:.1f})")
    else:
        lines.append("<!-- No related cards yet — links appear automatically as the knowledge base grows -->")
    lines.extend(["", "---", ""])

    lines.extend(
        [
            f"*文档生成时间：{now}*",
            f"*版本：v1.0 | scholar-agent {card_label}*",
            "",
        ]
    )
    return lines


def build_knowledge_card(
    query: str,
    answer_data: dict,
    research_data: dict | None,
    knowledge_root: Path,
    index_path: Path | None = None,
    domain_override: str | None = None,
    confidence: str = "draft",
) -> Path:
    """Build a knowledge card from research evidence and structured answer."""
    # 1. Resolve metadata
    meta = _resolve_card_metadata(query, answer_data, knowledge_root, domain_override)
    major_domain = meta["major_domain"]
    topic = meta["topic"]
    output_dir = meta["output_dir"]
    card_type = meta["card_type"]
    now = meta["now"]
    card_id = meta["card_id"]
    note_label = meta["note_label"]

    # 2. Collect sources
    source_urls = collect_source_urls(research_data)
    if not source_urls:
        ans_sources = answer_data.get("sources") or answer_data.get("source_refs") or []
        if isinstance(ans_sources, list):
            source_urls = [str(s) for s in ans_sources if s]

    # 3. Extract structured content
    main_answer = _normalize_answer_markdown(answer_data.get("answer", str(answer_data)))
    claims = answer_data.get("supporting_claims", [])
    inferences = answer_data.get("inferences", [])
    uncertainties = answer_data.get("uncertainty", [])
    missing = answer_data.get("missing_evidence", [])
    next_steps = answer_data.get("suggested_next_steps", [])
    expected_output = answer_data.get("expected_output", "")
    example = answer_data.get("example", "")
    prerequisites = answer_data.get("prerequisites", [])
    impl_steps = answer_data.get("implementation_steps", [])
    verification = answer_data.get("verification", "")
    pitfalls = answer_data.get("pitfalls", [])
    rollback = answer_data.get("rollback", "")

    # 4. Tags and visual aids
    tags = _collect_tags(query, answer_data, major_domain, topic, card_type)
    va_by_section = _index_visual_aids(answer_data.get("visual_aids", []))
    source_images = collect_source_images(research_data)
    # F3: map evidence ids to source refs so claims link to their sources.
    evidence_map = _build_evidence_map(research_data)
    # F3 (save_research path): no research_data → fall back to answer sources
    # so claims whose evidence_ids cite a source URL still render as links.
    if not evidence_map:
        evidence_map = _evidence_map_from_sources(source_urls)

    # 5. Assemble card
    lines = _build_frontmatter(
        card_id,
        note_label,
        query,
        card_type,
        major_domain,
        topic,
        tags,
        source_urls,
        now,
        answer_data,
        confidence=confidence,
    )
    lines.extend(
        _build_toc(
            claims,
            inferences,
            uncertainties,
            missing,
            next_steps,
            card_type,
            expected_output,
            example,
            va_by_section.get(None, []),
            source_images,
            prerequisites,
            impl_steps,
            verification,
            pitfalls,
            rollback,
        )
    )
    lines.extend(
        _build_body_sections(
            query,
            main_answer,
            claims,
            inferences,
            uncertainties,
            missing,
            next_steps,
            card_type,
            expected_output,
            example,
            va_by_section,
            prerequisites,
            impl_steps,
            verification,
            pitfalls,
            rollback,
            evidence_map,
        )
    )

    unplaced_aids = va_by_section.get(None, [])
    card_label = {"knowledge": "知识卡片", "method": "方法卡片", "engineering": "工程操作指南"}.get(
        card_type, "知识卡片"
    )
    full_text = "\n".join(lines)
    _idx = index_path if index_path is not None else DEFAULT_INDEX
    lines.extend(
        _build_footer(
            unplaced_aids,
            source_images,
            research_data,
            full_text,
            source_urls,
            query,
            claims,
            major_domain,
            _idx,
            now,
            card_label,
        )
    )

    # 6. Write to knowledge tree
    output_dir.mkdir(parents=True, exist_ok=True)
    card_path: Path = output_dir / f"{card_id}.md"
    body = "\n".join(lines) + "\n"
    # E1: convert arxiv URLs (sources/参考文献) to [[wikilink]] where a matching
    # paper-note exists (E4: only existing stems, no dangling links).
    try:
        from scholar_agent.engine.academic.note_linker import arxiv_urls_to_wikilinks
        from scholar_agent.engine.scholar_config import get_paper_notes_dir

        pn = get_paper_notes_dir()
        if pn.exists():
            body, _ = arxiv_urls_to_wikilinks(body, str(pn))
    except Exception:
        logger.warning("arxiv URL→wikilink failed", exc_info=True)
    atomic_write_text(card_path, body, encoding="utf-8")

    detail = f"type={card_type}, domain={major_domain}"
    if topic:
        detail += f", topic={topic}"
    append_changelog(knowledge_root, "created", card_id, detail)

    return card_path


def reindex(knowledge_root: Path, index_output: Path) -> bool:
    """Rebuild the local index, refreshing the embedding index too if one exists.

    Honors the build-once-auto-enable policy (decision D1): when an embedding
    index sits next to the BM25 index (built via ``scholar-agent index
    --build-embedding-index``), automatic reindex keeps it fresh so newly
    added cards become semantically searchable. Absent the embedding index,
    reindex stays BM25-only.
    """
    try:
        from scholar_agent.engine.local_index import write_index

        embedding_path = index_output.parent / "embeddings.json"
        write_index(
            knowledge_root,
            index_output,
            build_embedding_index=embedding_path.exists(),
            embedding_output=embedding_path,
        )
        return True
    except Exception:
        logger.exception("local index rebuild failed")
        return False


def append_changelog(
    knowledge_root: Path,
    action: str,
    card_id: str,
    detail: str = "",
) -> None:
    """Append an entry to the knowledge base changelog.

    Args:
        knowledge_root: Root directory of the knowledge base.
        action: One of 'created', 'updated', 'deprecated', 'transitioned'.
        card_id: The card identifier.
        detail: Optional extra context (e.g. target state for transitions).
    """
    changelog_path = knowledge_root.parent / "changelog.md"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"- **{now}** [{action}] {card_id}"
    if detail:
        entry += f" — {detail}"
    entry += "\n"

    lock_path = changelog_path.with_suffix(".lock")
    changelog_path.parent.mkdir(parents=True, exist_ok=True)

    # Simple file-based lock for concurrent access safety
    for _ in range(10):
        try:
            import os

            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            import time

            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > 10:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                pass
            time.sleep(0.1)
    else:
        pass  # Proceed without lock rather than hanging

    try:
        if not changelog_path.exists():
            header = "# Knowledge Base Changelog\n\nAll changes to knowledge cards are recorded here.\n\n"
            atomic_write_text(changelog_path, header + entry, encoding="utf-8")
        else:
            with open(changelog_path, "a", encoding="utf-8") as f:
                f.write(entry)
    finally:
        with contextlib.suppress(FileNotFoundError):
            lock_path.unlink()


def main() -> int:
    args = parse_args()

    # Load inputs
    research_data = None
    if args.research and args.research.exists():
        try:
            research_data = json.loads(args.research.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load research file %s: %s", args.research, exc)
            return 1
    try:
        answer_data = json.loads(args.answer.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load answer file %s: %s", args.answer, exc)
        return 1

    # Step 0: Validate answer against schema
    schema_warnings = validate_answer_schema(answer_data)
    for w in schema_warnings:
        logger.warning("Schema warning: %s", w)

    # Step 1: Build knowledge card
    card_path = build_knowledge_card(
        args.query,
        answer_data,
        research_data,
        args.knowledge_root,
        index_path=args.index_output,
    )
    logger.info("Knowledge card written: %s", card_path)

    # Step 2: Rebuild index
    if reindex(args.knowledge_root, args.index_output):
        logger.info("Index rebuilt: %s", args.index_output)
    else:
        logger.warning("index rebuild failed")

    # Step 3: Verify retrievability
    import subprocess

    verify = subprocess.run(
        [
            sys.executable,
            "-m",
            "scholar_agent.engine.local_retrieve",
            args.query,
            "--index",
            str(args.index_output),
            "--limit",
            "3",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if verify.returncode == 0:
        results = json.loads(verify.stdout)
        slug = safe_slug(args.query)
        expected_prefixes = (f"knowledge-{slug}", f"method-{slug}")
        found = any(r.get("doc_id", "").startswith(expected_prefixes) for r in results.get("results", []))
        status = "verified retrievable" if found else "written but not in top results"
        logger.info("Verification: %s", status)
    else:
        logger.info("Verification: could not check retrievability")

    logger.info("Done. Knowledge loop closed for: %s", args.query)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s: %(message)s")
    raise SystemExit(main())
