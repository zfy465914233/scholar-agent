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
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from scholar_agent.engine.common import parse_frontmatter as _parse_frontmatter

if TYPE_CHECKING:
    from pathlib import Path

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

CARD_TYPES = {"knowledge", "method"}
CONFIDENCE_LEVELS = {"draft", "confirmed", "likely", "unknown"}
ORIGINS = {"local_seed", "manual_web_research", "web_research_with_synthesis", "distilled", "promoted", "imported"}

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
    if not review_status and metadata.get("origin") in {"promoted", "distilled"}:
        issues.append(CardIssue("warning", "review_status", "Promoted/distilled cards should have review_status."))

    return issues


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

    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            a, b = cards[i], cards[j]

            # Exact ID match
            if a.get("id") and b.get("id") and a["id"] == b["id"]:
                duplicates.append((i, j, 1.0, "identical_id"))
                continue

            # Same topic + type + similar title
            sig_a = _card_signature(a)
            sig_b = _card_signature(b)
            if sig_a == sig_b:
                duplicates.append((i, j, 1.0, "identical_signature"))
                continue

            # Title similarity
            title_a = _normalize_for_comparison(str(a.get("title", "")))
            title_b = _normalize_for_comparison(str(b.get("title", "")))
            if title_a and title_b:
                # Simple word overlap similarity
                words_a = set(title_a.split())
                words_b = set(title_b.split())
                if words_a and words_b:
                    overlap = len(words_a & words_b) / max(len(words_a | words_b), 1)
                    if overlap >= similarity_threshold and a.get("topic") == b.get("topic"):
                        duplicates.append((i, j, round(overlap, 2), "similar_title"))

    return duplicates


def scan_knowledge_dir(knowledge_root: Path) -> list[dict[str, Any]]:
    """Scan a knowledge directory and return all card metadata."""
    cards: list[dict[str, Any]] = []
    for path in knowledge_root.rglob("*.md"):
        if "templates" in path.parts or path.name.lower() == "readme.md":
            continue
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n"):
            continue
        metadata, _ = parse_frontmatter(raw)
        metadata["_path"] = str(path)
        cards.append(metadata)
    return cards
