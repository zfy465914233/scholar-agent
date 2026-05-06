"""Inter-note linking engine for the paper-notes knowledge base.

Discovers cross-paper relationships via shared metadata (keywords, authors,
domain) and auto-generates ``[[wiki-links]]`` between notes.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Sequence

import sys
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from common import parse_frontmatter
from academic.paper_analyzer import title_to_filename

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stop-list — words too generic to be useful link targets
# ---------------------------------------------------------------------------

_SKIP_TERMS: frozenset[str] = frozenset({
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


# ---------------------------------------------------------------------------
# Related-paper discovery
# ---------------------------------------------------------------------------

def find_related_papers(
    paper: dict[str, Any],
    all_papers: list[dict[str, Any]],
    max_links: int = 5,
) -> list[str]:
    """Rank other papers by affinity and return the top note stems.

    Affinity is computed from shared keywords, shared domain, shared authors,
    and title-word overlap.
    """
    my_title = paper.get("title", "").lower()
    my_kw = {kw.lower() for kw in paper.get("matched_keywords", [])}
    my_domain = paper.get("matched_domain", "")
    my_authors = {
        (a.lower() if isinstance(a, str) else str(a).lower())
        for a in paper.get("authors", [])[:5]
    }

    _FILLER = {"a", "an", "the", "of", "in", "for", "and", "with", "using"}
    my_words = set(re.sub(r"[^a-z0-9\s]", "", my_title).split()) - _FILLER

    candidates: list[tuple[float, str]] = []
    for other in all_papers:
        if other.get("title", "").lower() == my_title:
            continue

        score = 0.0

        # keyword overlap
        other_kw = {kw.lower() for kw in other.get("matched_keywords", [])}
        shared = my_kw & other_kw
        if shared:
            score += len(shared) * 2.0

        # domain match
        if my_domain and other.get("matched_domain", "") == my_domain:
            score += 1.0

        # author overlap
        other_authors = {
            (a.lower() if isinstance(a, str) else str(a).lower())
            for a in other.get("authors", [])[:5]
        }
        shared_auth = my_authors & other_authors
        if shared_auth:
            score += len(shared_auth) * 1.5

        # title word overlap (bonus)
        other_words = set(
            re.sub(r"[^a-z0-9\s]", "", other.get("title", "").lower()).split()
        ) - _FILLER
        overlap = my_words & other_words
        if len(overlap) >= 2:
            score += 0.5 * len(overlap)

        if score > 0:
            candidates.append((score, title_to_filename(other.get("title", ""))))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [stem for _, stem in candidates[:max_links]]


def insert_wikilinks(
    note_path: str,
    related_filenames: list[str],
) -> bool:
    """Append ``## Related Papers`` section with links if not already present."""
    if not related_filenames:
        return False
    try:
        with open(note_path, "r", encoding="utf-8") as fh:
            body = fh.read()

        if "## Related Papers" in body:
            lines = body.split("\n")
            patched: list[str] = []
            inside = False
            for ln in lines:
                patched.append(ln)
                if ln.strip() == "## Related Papers":
                    inside = True
                    for stem in related_filenames:
                        link = f"- [[{stem}]]"
                        if link not in body:
                            patched.append(link)
                elif inside and ln.startswith("## "):
                    inside = False
            body = "\n".join(patched)
        else:
            block = "## Related Papers\n" + "\n".join(f"- [[{s}]]" for s in related_filenames)
            body = body.rstrip() + "\n\n" + block + "\n"

        with open(note_path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return True
    except Exception as exc:
        logger.error("insert_wikilinks failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Keyword extraction from note metadata
# ---------------------------------------------------------------------------

def _pull_title_terms(title: str) -> list[str]:
    """Extract link-worthy tokens from a paper title.

    Strategies:
    1. Pre-colon segment (acronym or short name, ≤30 chars)
    2. Capitalised hyphenated spans (e.g. Vision-Language)
    3. All-caps acronyms ≥2 chars (excluding tiny generics)
    """
    hits: list[str] = []
    if ":" in title:
        head = title.split(":")[0].strip()
        if len(head) <= 30:
            hits.append(head)
    for m in re.finditer(r"\b([A-Z][A-Za-z]*(?:-[A-Za-z]+)+)\b", title):
        if len(m.group(1)) >= 4:
            hits.append(m.group(1))
    for m in re.finditer(r"\b([A-Z]{2,}(?:-\d+)?)\b", title):
        token = m.group(1)
        if token not in {"AI", "ML", "NLP", "CV", "II", "III", "IV"}:
            hits.append(token)
    return hits


def scan_notes_for_keywords(
    notes_dir: str,
    knowledge_dir: str = "",
) -> dict[str, str]:
    """Build a unique keyword → note-stem index from a directory of notes.

    Ambiguous keywords (mapping to more than one note) are dropped.
    """
    root = Path(notes_dir)
    if not root.exists():
        return {}

    # intermediate: keyword → {stems}
    bucket: dict[str, set[str]] = {}

    for md in root.rglob("*.md"):
        stem = md.stem
        try:
            raw = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        meta, _ = parse_frontmatter(raw)
        title = meta.get("title", stem.replace("_", " "))

        terms = _pull_title_terms(str(title))

        for tag in meta.get("tags", []):
            t = str(tag).strip()
            if t and t.lower() not in _SKIP_TERMS and len(t) >= 3:
                terms.append(t)

        for t in terms:
            low = t.lower().strip()
            if low and low not in _SKIP_TERMS and len(low) >= 2:
                bucket.setdefault(low, set()).add(stem)

    # keep only unambiguous mappings
    index: dict[str, str] = {}
    for low, stems in bucket.items():
        if len(stems) == 1:
            index[low] = next(iter(stems))

    logger.info("Keyword scan of %s: %d unambiguous terms", notes_dir, len(index))
    return index


# ---------------------------------------------------------------------------
# In-place linkification
# ---------------------------------------------------------------------------

def linkify_keywords(
    note_path: str,
    keyword_index: dict[str, str],
) -> tuple[bool, int]:
    """Replace bare keywords with ``[[target|display]]`` wiki-links.

    Skips: frontmatter, code fences, headings, and existing ``[[…]]`` spans.
    Each keyword is linked at most once per note.
    """
    fp = Path(note_path)
    try:
        text = fp.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("Cannot read %s: %s", note_path, exc)
        return False, 0

    self_stem = fp.stem
    linked: set[str] = set()
    added = 0
    in_fm = False
    fm_dashes = 0
    in_fence = False
    out: list[str] = []

    for line in text.split("\n"):
        stripped = line.strip()

        # --- frontmatter tracking ---
        if stripped == "---":
            fm_dashes += 1
            in_fm = fm_dashes == 1
            if fm_dashes == 2:
                in_fm = False
            out.append(line)
            continue
        if in_fm:
            out.append(line)
            continue

        # --- code-fence tracking ---
        if stripped.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue

        # --- skip headings ---
        if stripped.startswith("#"):
            out.append(line)
            continue

        # --- attempt linking ---
        mutated = line
        for kw_low, target in keyword_index.items():
            if kw_low in linked or target == self_stem:
                continue
            pat = re.compile(
                r"(?<!\[\[)(?<!\|)\b(" + re.escape(kw_low) + r")\b(?!\]\])(?!\|)",
                re.IGNORECASE,
            )
            hit = pat.search(mutated)
            if hit:
                display = hit.group(1)
                mutated = mutated[: hit.start()] + f"[[{target}|{display}]]" + mutated[hit.end():]
                linked.add(kw_low)
                added += 1

        out.append(mutated)

    if added == 0:
        return False, 0

    fp.write_text("\n".join(out), encoding="utf-8")
    logger.info("Linked %s: +%d wiki-links", note_path, added)
    return True, added
