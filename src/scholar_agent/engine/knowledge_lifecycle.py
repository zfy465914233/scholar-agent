"""Knowledge card schema definition and lifecycle management.

Defines the expected frontmatter schema for knowledge cards, validates cards
against it, manages lifecycle transitions, and detects duplicates.

Lifecycle states:
  draft      — newly created, not yet reviewed
  reviewed   — reviewed for accuracy, not yet battle-tested
  trusted    — validated through usage
  stale      — potentially outdated, needs review
  deprecated — superseded or incorrect, should not be used

Usage:
  from knowledge_lifecycle import validate_card, transition_card, detect_duplicates
  from knowledge_lifecycle import (
      scan_stale_card_summaries, mark_card_stale, extract_card_urls,
      refresh_card_sources, stamp_captured_at, set_frontmatter_key,
  )
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from scholar_agent.engine.common import is_reserved_knowledge_path
from scholar_agent.engine.common import parse_frontmatter as _parse_frontmatter

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ── Lifecycle states ───────────────────────────────────────────────


class LifecycleState(str, Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    TRUSTED = "trusted"
    STALE = "stale"
    DEPRECATED = "deprecated"


VALID_TRANSITIONS: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.DRAFT: {LifecycleState.REVIEWED, LifecycleState.DEPRECATED},
    LifecycleState.REVIEWED: {LifecycleState.TRUSTED, LifecycleState.STALE, LifecycleState.DEPRECATED},
    LifecycleState.TRUSTED: {LifecycleState.STALE, LifecycleState.DEPRECATED},
    LifecycleState.STALE: {LifecycleState.REVIEWED, LifecycleState.TRUSTED, LifecycleState.DEPRECATED},
    LifecycleState.DEPRECATED: set(),  # terminal state
}


# ── Schema definition ─────────────────────────────────────────────

CARD_TYPES = {"knowledge", "method", "engineering"}
CONFIDENCE_LEVELS = {"draft", "confirmed", "likely", "unknown", "reviewed"}
ORIGINS = {
    "local_seed",
    "manual_web_research",
    "web_research_with_synthesis",
    "distilled",
    "promoted",
    "promoted_from_distilled_note",
    "imported",
}

# F4: domain-specific freshness thresholds (years). Fast-moving fields
# (AI/ML) decay quickly; slow fields (history/math) stay valid much longer.
# Keys are matched case-insensitively; unknown domains fall back to the
# default below.
_DEFAULT_FRESHNESS_YEARS: float = 3.0
_DOMAIN_FRESHNESS_YEARS: dict[str, float] = {
    "ai": 0.5,
    "llm-agents": 0.5,
    "llm": 0.5,
    "machine-learning": 0.5,
    "ml": 0.5,
    "deep-learning": 0.5,
    "transformers": 0.5,
    "history": 5.0,
    "math": 5.0,
    "mathematics": 5.0,
    "philosophy": 5.0,
}


def _freshness_years_for(domain: str | None) -> float:
    """Return the staleness threshold (years) for a card's domain.

    Unknown/empty domains fall back to ``_DEFAULT_FRESHNESS_YEARS``.
    Match is case-insensitive.
    """
    if not domain:
        return _DEFAULT_FRESHNESS_YEARS
    key = str(domain).strip().lower()
    return _DOMAIN_FRESHNESS_YEARS.get(key, _DEFAULT_FRESHNESS_YEARS)


def scan_stale_cards(root: Path, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Scan a knowledge directory for stale cards.

    A card is stale when ``now.year - source_year`` exceeds its per-domain
    freshness threshold (:func:`_freshness_years_for`); the source year is the
    first 4-digit run in ``source_date``, falling back to ``updated_at``.
    Reserved paths, unreadable files, and files without frontmatter or a
    parseable year are skipped.

    Returns dicts ``{"path", "id", "title", "domain", "source_year",
    "threshold_years", "days_stale"}`` sorted by path. Advisory; never raises
    for a single unreadable card.
    """
    current = now or datetime.now()
    stale: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.md")):
        if is_reserved_knowledge_path(path):
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not raw.startswith("---\n"):
            continue
        meta, _body = parse_frontmatter(raw)
        source_date = meta.get("source_date") or meta.get("updated_at")
        if not source_date:
            continue
        match = re.search(r"\d{4}", str(source_date))
        if not match:
            continue
        source_year = int(match.group())
        threshold = _freshness_years_for(meta.get("domain"))
        years_elapsed = current.year - source_year
        if years_elapsed <= threshold:
            continue
        stale.append(
            {
                "path": str(path),
                "id": meta.get("id", ""),
                "title": meta.get("title", ""),
                "domain": meta.get("domain", ""),
                "source_year": source_year,
                "threshold_years": threshold,
                "days_stale": round((years_elapsed - threshold) * 365.25),
            }
        )
    return stale


# Required fields for a valid card
REQUIRED_FIELDS = {"id", "title", "type", "topic", "confidence", "updated_at"}

# Optional but recommended fields
OPTIONAL_FIELDS = {
    "tags",
    "source_refs",
    "origin",
    "aliases",
    "domain",
    "review_status",
    "last_reviewed_at",
    "freshness_expectation",
    "supersedes",
    "conflicts_with",
    "question_types",
    "prerequisites",
}


@dataclass
class CardIssue:
    severity: str  # "error" or "warning"
    field: str
    message: str


def parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-like frontmatter from a markdown string.

    Delegates to common.parse_frontmatter for the implementation.
    """
    return _parse_frontmatter(raw)


def validate_card(metadata: dict[str, Any]) -> list[CardIssue]:
    """Validate a card's frontmatter against the schema.

    Returns a list of issues (errors and warnings).
    """
    issues: list[CardIssue] = []

    # Check required fields
    for field in REQUIRED_FIELDS:
        if field not in metadata or not metadata[field]:
            issues.append(CardIssue("error", field, f"Missing required field: {field}"))

    # Validate type
    card_type = metadata.get("type", "")
    if card_type and card_type not in CARD_TYPES:
        issues.append(CardIssue("error", "type", f"Invalid type '{card_type}'. Must be one of: {CARD_TYPES}"))

    # Validate confidence
    confidence = metadata.get("confidence", "")
    if confidence and confidence not in CONFIDENCE_LEVELS:
        issues.append(CardIssue("error", "confidence", f"Invalid confidence '{confidence}'."))

    # Validate origin
    origin = metadata.get("origin", "")
    if origin and origin not in ORIGINS:
        issues.append(CardIssue("warning", "origin", f"Unrecognized origin '{origin}'."))

    # Validate review_status if present
    review_status = metadata.get("review_status", "")
    valid_states = {s.value for s in LifecycleState}
    if review_status and review_status not in valid_states:
        issues.append(CardIssue("error", "review_status", f"Invalid review_status '{review_status}'."))

    # Validate tags is a list
    tags = metadata.get("tags")
    if tags is not None and not isinstance(tags, list):
        issues.append(CardIssue("error", "tags", "tags must be a list."))

    # Warn about missing recommended fields
    recommended = {"tags", "source_refs"}
    for field in recommended:
        if field not in metadata or not metadata[field]:
            issues.append(CardIssue("warning", field, f"Missing recommended field: {field}"))

    # Warn if no review_status but origin is promoted/distilled
    if not review_status and metadata.get("origin") in {"promoted", "distilled", "promoted_from_distilled_note"}:
        issues.append(CardIssue("warning", "review_status", "Promoted/distilled cards should have review_status."))

    return issues


def validate_card_quality(
    card_path: str,
    *,
    freshness_years: float = 3.0,
    now_year: int | None = None,
) -> dict[str, Any]:
    """F2/F4: validate a persisted card's frontmatter schema, body density,
    and source freshness.

    Wraps :func:`validate_card` (frontmatter schema), adds a body-density
    check, and flags a ``source_date`` older than ``freshness_years`` (F4).
    Returns ``{"errors": [...], "warnings": [...]}`` with ``{field, message}``
    items. Advisory — never raises; a failed read yields a single error entry.
    """
    from pathlib import Path

    try:
        raw = Path(card_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"errors": [{"field": "file", "message": f"cannot read card: {exc}"}], "warnings": []}
    meta, body = _parse_frontmatter(raw)
    issues = validate_card(meta)
    errors = [{"field": i.field, "message": i.message} for i in issues if i.severity == "error"]
    warnings = [{"field": i.field, "message": i.message} for i in issues if i.severity == "warning"]
    body_text = body.strip() if isinstance(body, str) else ""
    if len(body_text) < 300:
        warnings.append({"field": "body", "message": f"card body is thin ({len(body_text)} chars < 300)"})
    # F4: flag stale sources so old cards surface for refresh.
    # When the caller left freshness_years at the default, derive the
    # threshold from the card's domain (AI/ML decay fast, history/math
    # decay slowly) instead of a one-size-fits-all 3 years.
    effective_freshness = _freshness_years_for(meta.get("domain")) if freshness_years == 3.0 else freshness_years
    source_date = meta.get("source_date")
    if source_date:
        m = re.search(r"\d{4}", str(source_date))
        if m:
            sy = int(m.group())
            cur = now_year if now_year is not None else datetime.now().year
            if cur - sy > effective_freshness:
                warnings.append({"field": "source_date", "message": f"source is old ({sy}, >{effective_freshness}y)"})
    return {"errors": errors, "warnings": warnings}


def transition_card(
    metadata: dict[str, Any],
    target_state: LifecycleState,
) -> tuple[dict[str, Any], str | None]:
    """Attempt to transition a card to a new lifecycle state.

    Returns (updated_metadata, error_message). If error_message is None,
    the transition was valid.
    """
    current = metadata.get("review_status", "")
    if not current:
        current = "draft"

    try:
        current_state = LifecycleState(current)
    except ValueError:
        return metadata, f"Current state '{current}' is not a valid lifecycle state."

    if target_state not in VALID_TRANSITIONS.get(current_state, set()):
        return metadata, f"Cannot transition from '{current}' to '{target_state.value}'."

    metadata["review_status"] = target_state.value
    return metadata, None


def _card_signature(metadata: dict[str, Any]) -> str:
    """Create a normalized signature for duplicate detection."""
    title = str(metadata.get("title", "")).lower().strip()
    topic = str(metadata.get("topic", "")).lower().strip()
    card_type = str(metadata.get("type", "")).lower().strip()
    return f"{topic}::{card_type}::{title}"


def _normalize_for_comparison(text: str) -> str:
    """Normalize text for similarity comparison."""
    return re.sub(r"\s+", " ", text.lower().strip())


def detect_duplicates(
    cards: list[dict[str, Any]],
    similarity_threshold: float = 0.8,
) -> list[tuple[int, int, float, str]]:
    """Detect potential duplicate cards.

    Returns list of (idx_a, idx_b, similarity_score, reason) tuples.
    """
    duplicates: list[tuple[int, int, float, str]] = []

    # Precompute per-card comparison material once (O(n)) — the pairwise loop
    # below used to redo this work for the same card in every inner iteration.
    ids = [c.get("id") for c in cards]
    signatures = [_card_signature(c) for c in cards]
    titles = [_normalize_for_comparison(str(c.get("title", ""))) for c in cards]
    word_sets = [set(t.split()) for t in titles]

    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            a, b = cards[i], cards[j]

            # Exact ID match
            if ids[i] and ids[j] and ids[i] == ids[j]:
                duplicates.append((i, j, 1.0, "identical_id"))
                continue

            # Same topic + type + similar title
            if signatures[i] == signatures[j]:
                duplicates.append((i, j, 1.0, "identical_signature"))
                continue

            # Title similarity
            if titles[i] and titles[j]:
                # Simple word overlap similarity
                words_a = word_sets[i]
                words_b = word_sets[j]
                if words_a and words_b:
                    overlap = len(words_a & words_b) / max(len(words_a | words_b), 1)
                    if overlap >= similarity_threshold and a.get("topic") == b.get("topic"):
                        duplicates.append((i, j, round(overlap, 2), "similar_title"))

    return duplicates


def scan_knowledge_dir(knowledge_root: Path) -> list[dict[str, Any]]:
    """Scan a knowledge directory and return all card metadata."""
    cards: list[dict[str, Any]] = []
    for path in knowledge_root.rglob("*.md"):
        if is_reserved_knowledge_path(path):
            continue
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n"):
            continue
        metadata, _ = parse_frontmatter(raw)
        metadata["_path"] = str(path)
        cards.append(metadata)
    return cards


def persist_snapshot(
    knowledge_root: Path,
    url: str,
    content_md: str,
    title: str = "",
    *,
    retrieval_status: str | None = None,
) -> tuple[str, str]:
    """G2: archive fetched content to ``knowledge_root/_snapshots/<sha1(url)[:16]>.md``.

    Returns ``(snapshot_path, captured_at)`` — empty strings on failure. Shared
    by the MCP tools (fetch_url, save_research auto-snapshot) and the CLI
    stale-card refresh so dead links stay traceable. ``retrieval_status`` adds
    a ``retrieval_status:`` frontmatter line when given (CLI refresh behavior);
    omitted it matches the original MCP snapshot format byte-for-byte.
    """
    if not content_md:
        return "", ""
    try:
        import hashlib

        snap_dir = knowledge_root / "_snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        captured_at = datetime.now().strftime("%Y-%m-%d")
        status_line = f"retrieval_status: {retrieval_status}\n" if retrieval_status is not None else ""
        snap_path = snap_dir / f"{digest}.md"
        snap_path.write_text(
            f"---\nurl: {url}\ncaptured_at: {captured_at}\ntitle: {title}\n{status_line}---\n\n{content_md}\n",
            encoding="utf-8",
        )
        return str(snap_path), captured_at
    except Exception:
        logger.warning("failed to persist snapshot for %s", url, exc_info=True)
        return "", ""


# ── Stale-card reporting & refresh ────────────────────────────
# Business logic for `scholar-agent scan-stale` (moved here from cli.py;
# cli keeps thin aliases). refresh_card_sources is best-effort per URL and
# never raises.


def scan_stale_card_summaries(
    knowledge_root: Path,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """F4/G3: scan a knowledge directory for stale cards.

    Report-shaped wrapper over :func:`scan_stale_cards`: emits only the
    ``{"path", "domain", "source_year", "threshold_years", "days_stale"}``
    keys, with ``domain`` normalized to ``""`` when unset (derive the year
    from ``source_date``, falling back to ``updated_at``; flag when
    ``now_year - source_year > threshold``).

    Returns a list of dicts for every stale card. Advisory; never raises for
    a single unreadable card (it is skipped).
    """
    return [
        {
            "path": entry["path"],
            "domain": entry["domain"] or "",
            "source_year": entry["source_year"],
            "threshold_years": entry["threshold_years"],
            "days_stale": entry["days_stale"],
        }
        for entry in scan_stale_cards(knowledge_root, now=now)
    ]


def set_frontmatter_key(path: Path, key: str, value: str) -> bool:
    """Set ``key: value`` in a markdown file's frontmatter in place.

    Replaces an existing ``key:`` line, or inserts right after the opening
    ``---`` delimiter when absent. Returns True if the file was written,
    False when the file has no frontmatter block.
    """
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")
    if not lines or lines[0].strip() != "---":
        return False
    # Walk to the closing frontmatter delimiter.
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return False
    for i in range(1, end_idx):
        if lines[i].strip().startswith(f"{key}:"):
            lines[i] = f"{key}: {value}"
            path.write_text("\n".join(lines), encoding="utf-8")
            return True
    # Insert right after opening delimiter.
    lines.insert(1, f"{key}: {value}")
    path.write_text("\n".join(lines), encoding="utf-8")
    return True


def mark_card_stale(card_path: Path) -> bool:
    """Add `stale: true` to a card's frontmatter in place.

    Inserts the key right after the opening ``---`` line if absent. Returns
    True if the file was written, False if it already had the flag.
    """
    raw = card_path.read_text(encoding="utf-8")
    lines = raw.split("\n")
    if not lines or lines[0].strip() != "---":
        return False
    # Walk to the closing frontmatter delimiter.
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return False
    # Already present?
    for line in lines[1:end_idx]:
        if line.strip().startswith("stale:"):
            return False
    return set_frontmatter_key(card_path, "stale", "true")


def extract_card_urls(card_path: Path) -> list[str]:
    """Return the http(s) URLs from a card's frontmatter ``source_refs``.

    ``source_refs`` is a YAML list of URLs. Falls back to an inline ``sources``
    list if present. Non-http entries and duplicates are skipped.
    """
    from scholar_agent.engine.common import extract_source_urls, parse_frontmatter

    try:
        raw = card_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not raw.startswith("---\n"):
        return []
    meta, _body = parse_frontmatter(raw)
    return extract_source_urls(meta)


def refresh_card_sources(
    card_path: Path,
    knowledge_root: Path,
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    """G3: best-effort refresh of one card's source URLs.

    Re-fetches each ``source_refs`` URL via ``fetch_content``, stores a snapshot
    under ``knowledge_root/_snapshots/<sha1(url)[:16]>.md`` on success, and
    stamps the card's ``captured_at`` with today's date.

    Returns ``(refreshed, total)`` — the count of URLs whose snapshot was
    written and the total number of source URLs considered. Does NOT modify the
    answer body. Per-URL failures are logged as warnings and never raise.
    """
    from scholar_agent.engine.research_harness import fetch_content

    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")

    urls = extract_card_urls(card_path)
    if not urls:
        return (0, 0)

    refreshed = 0
    any_success = False
    for url in urls:
        try:
            result = fetch_content(url)
        except Exception as exc:  # best-effort: never abort the whole sweep
            sys.stderr.write(f"[scan-stale --refresh] {url} raised {exc}\n")
            continue

        status = result.get("retrieval_status", "")
        content_md = result.get("content_md", "") or ""
        if status in ("succeeded", "cached") and content_md.strip():
            title = result.get("title", "") or url
            snap_path, _captured_at = persist_snapshot(
                knowledge_root, url, content_md.strip(), title, retrieval_status=status
            )
            if snap_path:
                refreshed += 1
                any_success = True
        else:
            reason = result.get("failure_reason", "")
            sys.stderr.write(
                f"[scan-stale --refresh] {url} not snapshotted (status={status}{f': {reason}' if reason else ''})\n"
            )

    if any_success:
        stamp_captured_at(card_path, today)
    return (refreshed, len(urls))


def stamp_captured_at(card_path: Path, today: str) -> bool:
    """Set/replace ``captured_at`` in a card's frontmatter.

    Returns True if the file was written.
    """
    return set_frontmatter_key(card_path, "captured_at", today)
