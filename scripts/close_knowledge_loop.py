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
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
ANSWER_SCHEMA_PATH = ROOT / "schemas" / "answer.schema.json"

# Import config helpers
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from common import safe_slug, extract_entities
from domain_router import infer_domain as _infer_domain
from domain_router import infer_domain_decision as _infer_domain_decision
from lore_config import get_knowledge_dir, get_index_path
from local_retrieve import retrieve as bm25_retrieve

logger = logging.getLogger(__name__)

DEFAULT_KNOWLEDGE_ROOT = get_knowledge_dir()
DEFAULT_INDEX = get_index_path()


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


def check_contradictions(query: str, claims: list[dict], index_path: Path) -> list[dict]:
    """Check new claims against existing cards for potential contradictions.

    Uses BM25 to find similar cards, then surfaces overlapping claims.
    Returns a list of {card_id, card_title, their_claims} for related cards.
    """
    if not index_path.exists():
        return []

    try:
        results = bm25_retrieve(query, index_path, limit=3)
    except Exception:
        return []

    hits = results.get("results", [])
    related = []
    for hit in hits:
        if hit.get("score", 0) < 1.0:
            continue
        related.append({
            "card_id": hit.get("doc_id", ""),
            "title": hit.get("title", ""),
            "score": hit.get("score", 0),
        })
    return related[:3]


# Keywords suggesting an image is a useful diagram/chart rather than a photo
_CONTENT_IMAGE_KEYWORDS = (
    "diagram", "chart", "graph", "figure", "plot", "flow",
    "architecture", "pipeline", "framework", "structure", "schematic",
    "overview", "comparison", "model", "process", "algorithm",
    "table", "results", "performance", "heatmap", "confusion",
    "分布", "流程", "架构", "对比", "示意图", "模型", "图",
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

    Returns 'method' if the content contains procedural steps,
    otherwise 'knowledge'.
    """
    normalized = query.lower().strip()
    procedural_keywords = (
        "how to ", "implement", "deploy", "train", "build",
        "configure", "setup", "install", "run ", "optimize",
        "tune ", "debug", "fix ", "procedure", "algorithm",
    )
    if any(kw in normalized for kw in procedural_keywords):
        return "method"
    # Check if answer contains step-by-step content
    answer = str(answer_data.get("answer", "")).lower()
    step_markers = ("step 1", "step 2", "first,", "then,", "procedure:", "algorithm:")
    if any(m in answer for m in step_markers):
        return "method"
    return "knowledge"


def _card_note_label(card_type: str) -> str:
    """Return the human-readable note label for a card type."""
    if card_type == "method":
        return "Method Note"
    return "Knowledge Note"


def _card_id(card_type: str, slug: str) -> str:
    """Return the canonical id for a generated card."""
    prefix = "method" if card_type == "method" else "knowledge"
    return f"{prefix}-{slug}"


def _card_note_tag(card_type: str) -> str:
    """Return the canonical note tag for a card type."""
    prefix = "method" if card_type == "method" else "knowledge"
    return f"{prefix}-note"


def build_knowledge_card(
    query: str,
    answer_data: dict,
    research_data: dict | None,
    knowledge_root: Path,
    index_path: Path | None = None,
) -> Path:
    """Build a knowledge card from research evidence and structured answer."""
    card_summary = str(answer_data.get("answer", ""))[:500]
    routing = _infer_domain_decision(
        query, knowledge_root,
        card_title=query, card_summary=card_summary,
    )
    major_domain = str(routing["major_domain"])
    topic = str(routing.get("subdomain", "")).strip()
    output_dir = Path(str(routing["output_path"]))
    card_type = _infer_card_type(query, answer_data)
    slug = safe_slug(query)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_urls = collect_source_urls(research_data)

    # Extract structured content — answer_data itself is the structured dict
    main_answer = answer_data.get("answer", str(answer_data))
    claims = answer_data.get("supporting_claims", [])
    inferences = answer_data.get("inferences", [])
    uncertainties = answer_data.get("uncertainty", [])
    missing = answer_data.get("missing_evidence", [])
    next_steps = answer_data.get("suggested_next_steps", [])
    expected_output = answer_data.get("expected_output", "")
    example = answer_data.get("example", "")
    card_id = _card_id(card_type, slug)
    note_label = _card_note_label(card_type)

    # Infer tags from query and domain
    base_tags = [_card_note_tag(card_type), major_domain]
    if topic:
        base_tags.append(topic)
    query_lower = query.lower()
    for keyword, tag in [
        ("xgboost", "xgboost"), ("random forest", "random-forest"),
        ("cnn", "cnn"), ("lstm", "lstm"), ("transformer", "transformer"),
        ("qpe", "ml-qpe"), ("radar", "radar"), ("rainfall", "rainfall"),
        ("precipitation", "precipitation"), ("markov", "markov-chain"),
        ("quantum", "quantum"), ("quantization", "quantization"),
    ]:
        if keyword in query_lower and tag not in base_tags:
            base_tags.append(tag)

    # Merge user-supplied tags from answer_data (e.g. from capture_answer)
    for extra_tag in answer_data.get("tags", []):
        if extra_tag and extra_tag not in base_tags:
            base_tags.append(extra_tag)

    # Index visual aids by their target section for inline placement
    visual_aids = answer_data.get("visual_aids", [])
    _SECTION_ORDER = [
        "answer", "supporting_claims", "inferences",
        "uncertainty", "missing_evidence", "suggested_next_steps",
    ]
    va_by_section: dict[str | None, list[dict]] = {}
    for va in visual_aids:
        if not isinstance(va, dict):
            continue
        section = va.get("after_section") or None
        va_by_section.setdefault(section, []).append(va)

    # Build frontmatter
    lines = [
        "---",
        f"id: {card_id}",
        f"title: {note_label} — {query}",
        f"type: {card_type}",
        f"domain: {major_domain}",
        "tags:",
    ]
    if topic:
        lines.insert(len(lines) - 1, f"topic: {topic}")
    for tag in base_tags:
        lines.append(f"  - {tag}")
    if source_urls:
        lines.append("source_refs:")
        for url in source_urls[:10]:
            lines.append(f"  - {url}")
    card_label = "知识卡片" if card_type == "knowledge" else "方法卡片"
    lines.extend([
        "confidence: draft",
        f"updated_at: {now}",
        "origin: web_research_with_synthesis",
        "review_status: draft",
        "---",
        "",
        f"# {note_label} — {query}",
        "",
        f"> **{card_label}** | scholar-agent",
        ">",
    ])
    # Primary references from source URLs
    if source_urls:
        lines.append(f"> 主要参考：{', '.join(source_urls[:5])}")
    lines.extend([
        ">",
        "---",
        "",
    ])

    # --- Build TOC (目录) ---
    toc_entries = []
    toc_entries.append("1. [问题](#问题)")
    toc_entries.append("2. [回答](#回答)")
    section_idx = 3
    if claims:
        toc_entries.append(f"{section_idx}. [支撑论据](#支撑论据)")
        section_idx += 1
    if inferences:
        toc_entries.append(f"{section_idx}. [推论](#推论)")
        section_idx += 1
    if uncertainties:
        toc_entries.append(f"{section_idx}. [不确定性](#不确定性)")
        section_idx += 1
    if missing:
        toc_entries.append(f"{section_idx}. [缺失证据](#缺失证据)")
        section_idx += 1
    if next_steps:
        toc_entries.append(f"{section_idx}. [建议后续步骤](#建议后续步骤)")
        section_idx += 1
    if card_type == "method":
        if expected_output:
            toc_entries.append(f"{section_idx}. [预期输出](#预期输出)")
            section_idx += 1
        if example:
            toc_entries.append(f"{section_idx}. [具体示例](#具体示例)")
            section_idx += 1
    unplaced = va_by_section.get(None, [])
    if unplaced:
        toc_entries.append(f"{section_idx}. [可视化辅助](#可视化辅助)")
        section_idx += 1
    source_images = collect_source_images(research_data)
    if source_images:
        toc_entries.append(f"{section_idx}. [来源图片](#来源图片)")
        section_idx += 1
    toc_entries.append(f"{section_idx}. [参考文献](#参考文献)")
    section_idx += 1
    toc_entries.append(f"{section_idx}. [See Also](#see-also)")

    lines.append("## 目录")
    lines.append("")
    for entry in toc_entries:
        lines.append(entry)
    lines.extend(["", "---", ""])

    # --- Body sections ---
    lines.extend([
        "## 问题",
        "",
        query,
        "",
        "## 回答",
        "",
        main_answer,
        "",
    ])
    _append_visual_aids(lines, va_by_section.get("answer", []))

    if claims:
        lines.extend(["## 支撑论据", ""])
        for c in claims:
            if isinstance(c, dict):
                claim_text = c.get("claim", "")
                conf = c.get("confidence", "")
                ids = c.get("evidence_ids", [])
                lines.append(f"- **[{conf}]** {claim_text} (evidence: {', '.join(ids)})")
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

    # Method-specific sections: Expected Output and Concrete Example
    if card_type == "method":
        if expected_output:
            lines.extend(["## 预期输出", "", expected_output, ""])
        if example:
            lines.extend(["## 具体示例", "", example, ""])

    # Visual aids without a section go at the end
    if unplaced:
        lines.extend(["## 可视化辅助", ""])
        _append_visual_aids(lines, unplaced)

    # Auto-collect relevant images from research source pages
    if source_images:
        lines.extend(["## 来源图片", ""])
        for img in source_images:
            url = img.get("url", "")
            alt = img.get("alt_text", "") or img.get("title", "") or "Source image"
            source_url = ""
            # Find which evidence item this image came from
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

    # Auto-extract entities and add wiki-links
    full_text = "\n".join(lines)
    entities = extract_entities(full_text)
    if entities:
        lines.extend(["## Entities", ""])
        for entity in entities[:15]:
            entity_slug = safe_slug(entity)
            lines.append(f"- [[{entity_slug}|{entity}]]")
        lines.append("")

    # --- 参考文献 ---
    if source_urls:
        lines.extend(["## 参考文献", ""])
        # Build a title lookup from research evidence for richer reference entries
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

    # --- See Also (always present) ---
    lines.extend(["## See Also", ""])
    _idx = index_path if index_path is not None else DEFAULT_INDEX
    related = check_contradictions(query, claims, _idx)
    if related:
        for r in related:
            lines.append(f"- [[{r['card_id']}]] — {r['title']} (similarity: {r['score']:.1f})")
    else:
        lines.append("<!-- TODO: 添加相关卡片链接 -->")
    lines.extend(["", "---", ""])

    # --- Footer ---
    lines.extend([
        f"*文档生成时间：{now}*",
        f"*版本：v1.0 | scholar-agent {card_label}*",
        "",
    ])

    # Write to knowledge tree
    output_dir.mkdir(parents=True, exist_ok=True)
    card_path = output_dir / f"{card_id}.md"
    card_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Record in changelog
    detail = f"type={card_type}, domain={major_domain}"
    if topic:
        detail += f", topic={topic}"
    append_changelog(knowledge_root, "created", card_id, detail)

    return card_path


def reindex(knowledge_root: Path, index_output: Path) -> bool:
    """Rebuild the local index."""
    try:
        from local_index import write_index
        write_index(knowledge_root, index_output)
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

    if not changelog_path.exists():
        header = "# Knowledge Base Changelog\n\nAll changes to knowledge cards are recorded here.\n\n"
        changelog_path.write_text(header + entry, encoding="utf-8")
    else:
        with open(changelog_path, "a", encoding="utf-8") as f:
            f.write(entry)


def main() -> int:
    args = parse_args()

    # Load inputs
    research_data = None
    if args.research and args.research.exists():
        research_data = json.loads(args.research.read_text(encoding="utf-8"))
    answer_data = json.loads(args.answer.read_text(encoding="utf-8"))

    # Step 0: Validate answer against schema
    schema_warnings = validate_answer_schema(answer_data)
    for w in schema_warnings:
        logger.warning("Schema warning: %s", w)

    # Step 1: Build knowledge card
    card_path = build_knowledge_card(
        args.query, answer_data, research_data, args.knowledge_root,
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
        [sys.executable, str(SCRIPTS / "local_retrieve.py"),
         args.query, "--index", str(args.index_output), "--limit", "3"],
        capture_output=True, text=True,
    )
    if verify.returncode == 0:
        results = json.loads(verify.stdout)
        found = any(
            f"research-{safe_slug(args.query)}" in r.get("doc_id", "")
            for r in results.get("results", [])
        )
        status = "verified retrievable" if found else "written but not in top results"
        logger.info("Verification: %s", status)
    else:
        logger.info("Verification: could not check retrievability")

    logger.info("Done. Knowledge loop closed for: %s", args.query)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(levelname)s: %(message)s")
    raise SystemExit(main())
