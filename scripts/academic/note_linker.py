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
# Related-paper discovery
# ---------------------------------------------------------------------------

def discover_related_notes(
    paper: dict[str, Any],
    all_papers: list[dict[str, Any]],
    max_links: int = 5,
) -> list[str]:
    """Rank other papers by affinity and return the top note stems.

    Affinity is computed from shared keywords, shared domain, shared authors,
    and title-word overlap.
    """
    my_title = paper.get("title", "").lower()
    my_kw = {kw.lower() for kw in paper.get("domain_keywords", [])}
    my_domain = paper.get("best_domain", "")
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
        other_kw = {kw.lower() for kw in other.get("domain_keywords", [])}
        shared = my_kw & other_kw
        if shared:
            score += len(shared) * 2.0

        # domain match
        if my_domain and other.get("best_domain", "") == my_domain:
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


# ---------------------------------------------------------------------------
# KeywordIndex — inverted index with frequency filtering
# ---------------------------------------------------------------------------

class KeywordIndex:
    """Scans notes for linkable keywords, then applies [[wiki-links]].

    Build phase uses an inverted index (keyword → set of note stems)
    with frequency-based filtering: only keywords appearing in exactly
    one note are kept. This is a two-pass approach:
      Pass 1: collect all candidate terms and their frequencies
      Pass 2: keep only terms with frequency == 1 (unambiguous)
    """

    STOP_WORDS: frozenset[str] = frozenset({
        "model", "learning", "network", "method", "approach", "based", "using",
        "system", "data", "training", "task", "paper", "results", "analysis",
        "performance", "problem", "framework", "algorithm", "feature", "input",
        "output", "layer", "attention", "deep", "neural", "representation",
    })

    def __init__(self, notes_dir: str, knowledge_dir: str = ""):
        self._mapping: dict[str, str] = {}  # keyword -> note_stem
        self._build(notes_dir, knowledge_dir)

    def _build(self, notes_dir: str, knowledge_dir: str) -> None:
        """Build inverted index with frequency-based filtering.

        Two-pass approach:
        1. First pass: scan all notes, collect (keyword, stem) pairs into
           an inverted index mapping keyword → set of stems.
        2. Second pass: filter — keep only keywords mapped to exactly 1 stem.
        """
        root = Path(notes_dir)
        if not root.exists():
            return

        # Pass 1: Build inverted index — keyword → set of note stems
        inverted: dict[str, set[str]] = {}
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
                if t and t.lower() not in self.STOP_WORDS and len(t) >= 3:
                    terms.append(t)

            for t in terms:
                low = t.lower().strip()
                if low and low not in self.STOP_WORDS and len(low) >= 2:
                    inverted.setdefault(low, set()).add(stem)

        # Pass 2: Frequency filter — keep only unambiguous (freq == 1)
        self._mapping = {
            kw: next(iter(stems))
            for kw, stems in inverted.items()
            if len(stems) == 1
        }
        logger.info("keyword index built: %d unambiguous terms from %s", len(self._mapping), notes_dir)

    def as_dict(self) -> dict[str, str]:
        return dict(self._mapping)

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> "KeywordIndex":
        idx = cls.__new__(cls)
        idx._mapping = dict(d)
        return idx

    def apply_to(self, note_path: str) -> tuple[bool, int]:
        """Apply wiki-links using region-based document splitting + callback replacement.

        Instead of line-by-line state tracking, this splits the document into
        regions (frontmatter, code blocks, headings, body), then applies
        a single regex-based callback replacement on body regions only.
        """
        fp = Path(note_path)
        try:
            text = fp.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Cannot read %s: %s", note_path, exc)
            return False, 0

        self_stem = fp.stem

        # Build a single combined pattern for all keywords
        keywords = {k: v for k, v in self._mapping.items() if v != self_stem}
        if not keywords:
            return False, 0

        # Sort by length descending to match longer keywords first
        sorted_kw = sorted(keywords.keys(), key=len, reverse=True)
        combined = re.compile(
            r"(?<!\[\[)(?<!\|)\b(" + "|".join(re.escape(k) for k in sorted_kw) + r")\b(?!\]\])(?!\|)",
            re.IGNORECASE,
        )

        # Split document into regions
        lines = text.split("\n")
        regions: list[tuple[str, str]] = []  # (type, content) — type: fm/code/heading/body

        in_fm = False
        fm_dash_count = 0
        in_code = False
        current_body: list[str] = []

        def _flush_body():
            if current_body:
                regions.append(("body", "\n".join(current_body)))
                current_body.clear()

        for line in lines:
            stripped = line.strip()

            # Frontmatter detection
            if stripped == "---":
                fm_dash_count += 1
                if fm_dash_count == 1:
                    _flush_body()
                    in_fm = True
                    current_body.append(line)
                    continue
                elif fm_dash_count == 2:
                    in_fm = False
                    current_body.append(line)
                    regions.append(("fm", "\n".join(current_body)))
                    current_body.clear()
                    continue

            if in_fm:
                current_body.append(line)
                continue

            # Code fence detection
            if stripped.startswith("```"):
                if not in_code:
                    _flush_body()
                    in_code = True
                    current_body.append(line)
                else:
                    current_body.append(line)
                    regions.append(("code", "\n".join(current_body)))
                    current_body.clear()
                    in_code = False
                continue

            if in_code:
                current_body.append(line)
                continue

            # Heading detection
            if stripped.startswith("#"):
                _flush_body()
                regions.append(("heading", line))
                continue

            # Regular body line
            current_body.append(line)

        _flush_body()

        # Apply replacement only on body regions
        linked: set[str] = set()
        added = 0

        def _replace_cb(match: re.Match) -> str:
            nonlocal added
            matched_text = match.group(1)
            kw_low = matched_text.lower()
            target = keywords.get(kw_low)
            if target is None or kw_low in linked:
                return matched_text
            linked.add(kw_low)
            added += 1
            return f"[[{target}|{matched_text}]]"

        new_regions: list[str] = []
        for rtype, content in regions:
            if rtype == "body":
                new_regions.append(combined.sub(_replace_cb, content))
            else:
                new_regions.append(content)

        if added == 0:
            return False, 0

        fp.write_text("\n".join(new_regions), encoding="utf-8")
        logger.info("linked %s: +%d wiki-links", note_path, added)
        return True, added

    def apply_to_all(self, notes_dir: str) -> tuple[int, int]:
        """Apply to all .md files under notes_dir. Returns (files_modified, total_links)."""
        root = Path(notes_dir)
        total_processed = 0
        total_links = 0
        for md_file in root.rglob("*.md"):
            modified, links = self.apply_to(str(md_file))
            if modified:
                total_processed += 1
                total_links += links
        return total_processed, total_links


# ---------------------------------------------------------------------------
# Module-level backward-compat aliases
# ---------------------------------------------------------------------------

_SKIP_TERMS = KeywordIndex.STOP_WORDS  # backward compat


def build_keyword_index(notes_dir: str, knowledge_dir: str = "") -> dict[str, str]:
    """Build keyword -> note-stem mapping from notes directory."""
    return KeywordIndex(notes_dir, knowledge_dir).as_dict()


def apply_wiki_links(note_path: str, keyword_index: dict[str, str]) -> tuple[bool, int]:
    """Apply wiki-links to a single note using a pre-built keyword index."""
    return KeywordIndex.from_dict(keyword_index).apply_to(note_path)
