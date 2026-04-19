"""Note linker — find and create wiki-links between related papers.

Analyzes paper metadata (shared authors, keywords, references) to suggest
connections between papers in the knowledge base.

Also provides:
  - scan_notes_for_keywords: build a keyword→note mapping from existing notes
  - linkify_keywords: replace keywords with [[wikilinks]] in note text
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from academic.paper_analyzer import title_to_filename

# Allow importing common from parent scripts/ directory
import sys
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from common import parse_frontmatter

logger = logging.getLogger(__name__)


def find_related_papers(
    paper: dict[str, Any],
    all_papers: list[dict[str, Any]],
    max_links: int = 5,
    min_shared_keywords: int = 1,
) -> list[str]:
    """Find related papers based on shared keywords, authors, and domain.

    Args:
        paper: The target paper dict.
        all_papers: All available papers to search.
        max_links: Maximum number of related papers to return.
        min_shared_keywords: Minimum shared keywords for a match.

    Returns:
        List of note filenames (without extension) for wiki-links.
    """
    title = paper.get("title", "").lower()
    matched_kw = set(kw.lower() for kw in paper.get("matched_keywords", []))
    domain = paper.get("matched_domain", "")
    authors = set(
        a.lower() if isinstance(a, str) else str(a).lower()
        for a in paper.get("authors", [])[:5]
    )

    scored: list[tuple[float, str]] = []
    for other in all_papers:
        if other.get("title", "").lower() == title:
            continue

        other_kw = set(kw.lower() for kw in other.get("matched_keywords", []))
        other_domain = other.get("matched_domain", "")
        other_authors = set(
            a.lower() if isinstance(a, str) else str(a).lower()
            for a in other.get("authors", [])[:5]
        )

        score = 0.0

        # Shared keywords
        shared_kw = matched_kw & other_kw
        if len(shared_kw) >= min_shared_keywords:
            score += len(shared_kw) * 2.0

        # Same domain
        if domain and domain == other_domain:
            score += 1.0

        # Shared authors
        shared_authors = authors & other_authors
        if shared_authors:
            score += len(shared_authors) * 1.5

        # Title keyword overlap (lightweight)
        title_words = set(re.sub(r"[^a-z0-9\s]", "", title).split())
        other_title_words = set(re.sub(r"[^a-z0-9\s]", "", other.get("title", "").lower()).split())
        overlap = title_words & other_title_words - {"a", "an", "the", "of", "in", "for", "and", "with", "using"}
        if len(overlap) >= 2:
            score += 0.5 * len(overlap)

        if score > 0:
            fn = title_to_filename(other.get("title", ""))
            scored.append((score, fn))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [fn for _, fn in scored[:max_links]]


def insert_wikilinks(
    note_path: str,
    related_filenames: list[str],
) -> bool:
    """Insert wiki-links into an existing note file.

    Adds links under a "## Related Papers" section.

    Args:
        note_path: Path to the markdown note.
        related_filenames: List of note filenames for [[wikilinks]].

    Returns:
        True if the note was updated.
    """
    if not related_filenames:
        return False

    try:
        with open(note_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check if Related Papers section exists
        links_section = "## Related Papers\n"
        for fn in related_filenames:
            links_section += f"- [[{fn}]]\n"

        if "## Related Papers" in content:
            # Append to existing section
            lines = content.split("\n")
            new_lines = []
            in_section = False
            for line in lines:
                new_lines.append(line)
                if line.strip() == "## Related Papers":
                    in_section = True
                    for fn in related_filenames:
                        wikilink = f"- [[{fn}]]"
                        if wikilink not in content:
                            new_lines.append(wikilink)
                elif in_section and line.startswith("## "):
                    in_section = False
            content = "\n".join(new_lines)
        else:
            content = content.rstrip() + "\n\n" + links_section

        with open(note_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True

    except Exception as e:
        logger.error("Failed to insert wikilinks: %s", e)
        return False


# ---------------------------------------------------------------------------
# Keyword scanning and auto-linking
# ---------------------------------------------------------------------------

# Common words that are too generic for wikilinks
COMMON_WORDS = frozenset({
    "model", "learning", "network", "method", "approach", "based", "using",
    "system", "data", "training", "task", "paper", "results", "analysis",
    "performance", "problem", "framework", "algorithm", "feature", "input",
    "output", "layer", "attention", "deep", "neural", "representation",
    "pre-training", "fine-tuning", "evaluation", "benchmark", "dataset",
    "image", "text", "language", "visual", "generation", "classification",
    "detection", "segmentation", "object", "graph", "embedding", "loss",
    "optimization", "inference", "prediction", "architecture", "module",
    "component", "encoder", "decoder", "token", "sequence", "batch",
})


def _extract_keywords_from_title(title: str) -> list[str]:
    """Extract linkable keywords from a paper title.

    Three strategies:
    1. Leading acronym: "BLIP-2: ..." → "BLIP-2"
    2. Pre-colon text: "LoRA: Low-Rank ..." → "LoRA"
    3. Hyphenated/capitalized terms: "Vision-Language" → "Vision-Language"
    """
    keywords: list[str] = []

    # Strategy 1 & 2: pre-colon text
    if ":" in title:
        pre_colon = title.split(":")[0].strip()
        # If it looks like an acronym or short name (≤30 chars)
        if len(pre_colon) <= 30:
            keywords.append(pre_colon)

    # Strategy 3: capitalized/hyphenated terms
    # Match terms like "Vision-Language", "Mixture-of-Experts", "BLIP"
    for m in re.finditer(r'\b([A-Z][A-Za-z]*(?:-[A-Za-z]+)+)\b', title):
        term = m.group(1)
        if len(term) >= 4:
            keywords.append(term)

    # Uppercase acronyms (≥2 chars)
    for m in re.finditer(r'\b([A-Z]{2,}(?:-\d+)?)\b', title):
        acr = m.group(1)
        if acr not in {"AI", "ML", "NLP", "CV", "II", "III", "IV"}:
            keywords.append(acr)

    return keywords


def scan_notes_for_keywords(
    notes_dir: str,
    knowledge_dir: str = "",
) -> dict[str, str]:
    """Scan notes directory and build keyword→note_stem mapping.

    Extracts keywords from titles, tags, and frontmatter. Only keeps
    keywords that map to a unique note (ambiguous multi-mapping keywords
    are dropped).

    Args:
        notes_dir: Path to paper-notes directory.
        knowledge_dir: Optional path to knowledge directory for extra cards.

    Returns:
        Dict mapping lowercase keyword to note filename stem.
    """
    notes_path = Path(notes_dir)
    if not notes_path.exists():
        return {}

    # keyword_lower → set of note stems (to detect ambiguity)
    raw_map: dict[str, set[str]] = {}

    for md_file in notes_path.rglob("*.md"):
        stem = md_file.stem
        try:
            raw = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        meta, _ = parse_frontmatter(raw)
        title = meta.get("title", stem.replace("_", " "))

        # Extract from title
        kws = _extract_keywords_from_title(str(title))

        # Extract from tags
        tags = meta.get("tags", [])
        if isinstance(tags, list):
            for t in tags:
                t_str = str(t).strip()
                if t_str and t_str.lower() not in COMMON_WORDS and len(t_str) >= 3:
                    kws.append(t_str)

        # Register keywords
        for kw in kws:
            kw_lower = kw.lower().strip()
            if kw_lower and kw_lower not in COMMON_WORDS and len(kw_lower) >= 2:
                raw_map.setdefault(kw_lower, set()).add(stem)

    # Keep only unique mappings (keyword → exactly one note)
    result: dict[str, str] = {}
    for kw_lower, stems in raw_map.items():
        if len(stems) == 1:
            result[kw_lower] = next(iter(stems))

    logger.info("Scanned %s: %d unique keywords from notes", notes_dir, len(result))
    return result


def linkify_keywords(
    note_path: str,
    keyword_index: dict[str, str],
) -> tuple[bool, int]:
    """Replace keywords with [[wikilinks]] in a note.

    Rules:
    - Skips frontmatter (--- ... ---)
    - Skips code blocks (``` ... ```)
    - Skips existing [[...]] content
    - Skips heading lines (# ...)
    - Each keyword linked only on first occurrence
    - Does not link to the note's own filename

    Args:
        note_path: Path to the markdown file.
        keyword_index: Mapping from keyword_lower to note_stem.

    Returns:
        (modified, links_added) tuple.
    """
    path = Path(note_path)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.error("Cannot read %s: %s", note_path, e)
        return False, 0

    self_stem = path.stem
    lines = content.split("\n")
    new_lines: list[str] = []
    in_frontmatter = False
    frontmatter_count = 0
    in_code_block = False
    linked_keywords: set[str] = set()
    total_links = 0

    for line in lines:
        stripped = line.strip()

        # Track frontmatter
        if stripped == "---":
            frontmatter_count += 1
            if frontmatter_count == 1:
                in_frontmatter = True
            elif frontmatter_count == 2:
                in_frontmatter = False
            new_lines.append(line)
            continue

        if in_frontmatter:
            new_lines.append(line)
            continue

        # Track code blocks
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            new_lines.append(line)
            continue

        if in_code_block:
            new_lines.append(line)
            continue

        # Skip heading lines
        if stripped.startswith("#"):
            new_lines.append(line)
            continue

        # Process line for keywords
        modified_line = line
        for kw_lower, target_stem in keyword_index.items():
            if kw_lower in linked_keywords:
                continue
            if target_stem == self_stem:
                continue

            # Build pattern: case-insensitive, word boundary
            pattern = re.compile(
                r'(?<!\[\[)(?<!\|)\b(' + re.escape(kw_lower) + r')\b(?!\]\])(?!\|)',
                re.IGNORECASE,
            )

            match = pattern.search(modified_line)
            if match:
                original_text = match.group(1)
                replacement = f"[[{target_stem}|{original_text}]]"
                modified_line = modified_line[:match.start()] + replacement + modified_line[match.end():]
                linked_keywords.add(kw_lower)
                total_links += 1

        new_lines.append(modified_line)

    if total_links == 0:
        return False, 0

    new_content = "\n".join(new_lines)
    path.write_text(new_content, encoding="utf-8")
    logger.info("Linkified %s: %d links added", note_path, total_links)
    return True, total_links
