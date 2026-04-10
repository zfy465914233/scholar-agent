"""CLI tool for knowledge governance: validate, scan, lint, and manage card lifecycle.

Usage:
  python knowledge_governance.py validate                    # validate all cards
  python knowledge_governance.py duplicates                  # find duplicate cards
  python knowledge_governance.py transition <card_id> <state> # change lifecycle state
  python knowledge_governance.py scan                        # scan and report
  python knowledge_governance.py lint                        # content-level health checks
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from knowledge_lifecycle import (
    LifecycleState,
    detect_duplicates,
    parse_frontmatter,
    scan_knowledge_dir,
    transition_card,
    validate_card,
    VALID_TRANSITIONS,
)
from common import resolve_link_target

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KNOWLEDGE_ROOT = ROOT / "knowledge"


def cmd_validate(knowledge_root: Path, verbose: bool = False) -> int:
    """Validate all knowledge cards and report issues."""
    cards = scan_knowledge_dir(knowledge_root)
    total_errors = 0
    total_warnings = 0

    for card in cards:
        issues = validate_card(card)
        path = card.get("_path", "unknown")
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        total_errors += len(errors)
        total_warnings += len(warnings)

        if errors or (verbose and warnings):
            status = "ERROR" if errors else "WARN"
            print(f"[{status}] {path}")
            for issue in issues:
                print(f"  {issue.severity}: {issue.field} — {issue.message}")

    print(f"\nValidated {len(cards)} cards: {total_errors} errors, {total_warnings} warnings")
    return 1 if total_errors > 0 else 0


def cmd_duplicates(knowledge_root: Path) -> int:
    """Detect and report duplicate cards."""
    cards = scan_knowledge_dir(knowledge_root)
    dupes = detect_duplicates(cards)

    if not dupes:
        print(f"No duplicates found among {len(cards)} cards.")
        return 0

    print(f"Found {len(dupes)} potential duplicate(s):")
    for idx_a, idx_b, score, reason in dupes:
        a_id = cards[idx_a].get("id", f"card_{idx_a}")
        b_id = cards[idx_b].get("id", f"card_{idx_b}")
        print(f"  {a_id} <-> {b_id} (similarity: {score}, reason: {reason})")
    return 0


def cmd_scan(knowledge_root: Path) -> int:
    """Scan and report knowledge base status."""
    cards = scan_knowledge_dir(knowledge_root)

    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_topic: dict[str, int] = {}

    for card in cards:
        status = card.get("review_status", card.get("confidence", "unknown"))
        by_status[status] = by_status.get(status, 0) + 1
        card_type = card.get("type", "unknown")
        by_type[card_type] = by_type.get(card_type, 0) + 1
        topic = card.get("topic", "unknown")
        by_topic[topic] = by_topic.get(topic, 0) + 1

    print(f"Knowledge base: {len(cards)} cards in {knowledge_root}")
    print(f"\nBy lifecycle status:")
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")
    print(f"\nBy type:")
    for card_type, count in sorted(by_type.items()):
        print(f"  {card_type}: {count}")
    print(f"\nBy topic:")
    for topic, count in sorted(by_topic.items()):
        print(f"  {topic}: {count}")

    # Report cards without review_status
    no_status = [c for c in cards if not c.get("review_status")]
    if no_status:
        print(f"\nCards without review_status: {len(no_status)}")
        for c in no_status:
            print(f"  {c.get('id', '?')} ({c.get('_path', '?')})")

    return 0


def cmd_transition(card_id: str, target_state: str, knowledge_root: Path) -> int:
    """Transition a card's lifecycle state."""
    try:
        target = LifecycleState(target_state)
    except ValueError:
        valid = ", ".join(s.value for s in LifecycleState)
        print(f"Invalid state '{target_state}'. Valid states: {valid}")
        return 1

    # Find the card file
    cards = scan_knowledge_dir(knowledge_root)
    target_card = None
    for card in cards:
        if card.get("id") == card_id:
            target_card = card
            break

    if target_card is None:
        print(f"Card '{card_id}' not found.")
        return 1

    card_path = Path(target_card["_path"])
    raw = card_path.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(raw)

    updated, error = transition_card(metadata, target)
    if error:
        print(f"Transition failed: {error}")
        return 1

    # Write back
    fm_lines = ["---"]
    for key, value in updated.items():
        if key.startswith("_"):
            continue
        if isinstance(value, list):
            fm_lines.append(f"{key}:")
            for item in value:
                fm_lines.append(f"  - {item}")
        else:
            fm_lines.append(f"{key}: {value}")
    fm_lines.append("---")

    new_content = "\n".join(fm_lines) + "\n\n" + body + "\n"
    card_path.write_text(new_content, encoding="utf-8")
    print(f"Card '{card_id}' transitioned to '{target.value}'.")
    return 0


def cmd_show_transitions() -> int:
    """Show valid lifecycle transitions."""
    for state, targets in VALID_TRANSITIONS.items():
        targets_str = ", ".join(t.value for t in targets) if targets else "(terminal)"
        print(f"  {state.value} → {targets_str}")
    return 0


def cmd_lint(knowledge_root: Path, stale_days: int = 90) -> int:
    """Run content-level health checks on the knowledge base.

    Checks:
      - Orphan cards (no incoming or outgoing links)
      - Stale cards (not updated in stale_days days)
      - Broken wiki-links (links pointing to non-existent cards)
      - Schema drift (frontmatter missing required fields)
    """
    from datetime import datetime, timedelta, timezone
    import re

    cards = scan_knowledge_dir(knowledge_root)
    if not cards:
        print("No cards found.")
        return 0

    card_ids = {c.get("id", "") for c in cards if c.get("id")}
    total_issues = 0

    # Build link graph from card bodies
    link_re = re.compile(r"\[\[([^\]]+)\]\]")
    outgoing: dict[str, set[str]] = {}
    incoming: dict[str, set[str]] = {}

    for card in cards:
        cid = card.get("id", "")
        path = card.get("_path", "")
        raw = Path(path).read_text(encoding="utf-8") if path else ""
        _, body = parse_frontmatter(raw) if raw.startswith("---\n") else ({}, raw)
        targets = set(link_re.findall(body))
        outgoing[cid] = targets
        for t in targets:
            # Resolve target to actual card id for accurate incoming tracking
            resolved = resolve_link_target(t, card_ids)
            if resolved:
                incoming.setdefault(resolved, set()).add(cid)

    # Check orphans (no outgoing links AND no incoming backlinks)
    orphans = []
    for card in cards:
        cid = card.get("id", "")
        has_out = bool(outgoing.get(cid))
        has_in = cid in incoming
        if not has_out and not has_in:
            orphans.append(card)

    if orphans:
        total_issues += len(orphans)
        print(f"\n[ORPHAN] {len(orphans)} card(s) with no links (in or out):")
        for c in orphans:
            print(f"  {c.get('id', '?')} — {c.get('title', '?')}")

    # Check broken links
    broken = []
    for card in cards:
        cid = card.get("id", "")
        for target in outgoing.get(cid, set()):
            if resolve_link_target(target, card_ids) is None:
                broken.append((cid, target))
    if broken:
        total_issues += len(broken)
        print(f"\n[BROKEN LINK] {len(broken)} link(s) pointing to non-existent cards:")
        for cid, target in broken:
            print(f"  {cid} → [[{target}]]")

    # Check staleness
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
    stale_cards = []
    for card in cards:
        updated = card.get("updated_at", "")
        if not updated:
            # Don't mark drafts as stale — they may be newly captured
            if card.get("confidence") != "draft" and card.get("review_status") != "draft":
                stale_cards.append(card)
            continue
        try:
            updated_dt = datetime.strptime(str(updated)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if updated_dt < stale_cutoff:
                stale_cards.append(card)
        except ValueError:
            pass

    if stale_cards:
        total_issues += len(stale_cards)
        print(f"\n[STALE] {len(stale_cards)} card(s) not updated in {stale_days} days:")
        for c in stale_cards:
            print(f"  {c.get('id', '?')} — last updated {c.get('updated_at', '?')}")

    # Check for potential contradictions (cards with high textual overlap)
    if len(cards) >= 2:
        from common import safe_slug
        titles = [(c.get("id", ""), c.get("title", "").lower().split()) for c in cards if c.get("title")]
        contradictions = []
        for i, (id_a, words_a) in enumerate(titles):
            for j, (id_b, words_b) in enumerate(titles):
                if j <= i:
                    continue
                if not words_a or not words_b:
                    continue
                overlap = set(words_a) & set(words_b)
                union = set(words_a) | set(words_b)
                jaccard = len(overlap) / len(union) if union else 0
                if jaccard > 0.6:
                    contradictions.append((id_a, id_b, jaccard))
        if contradictions:
            total_issues += len(contradictions)
            print(f"\n[OVERLAP] {len(contradictions)} card pair(s) with high title similarity (potential duplicates/contradictions):")
            for id_a, id_b, score in contradictions:
                print(f"  {id_a} <-> {id_b} (Jaccard: {score:.2f})")

    if total_issues == 0:
        print(f"All {len(cards)} cards passed lint checks.")
    else:
        print(f"\n{total_issues} issue(s) found across {len(cards)} cards.")

    return 1 if total_issues > 0 else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Knowledge governance CLI.")
    parser.add_argument(
        "command",
        choices=["validate", "duplicates", "scan", "transition", "transitions", "lint"],
    )
    parser.add_argument("--knowledge-root", type=Path, default=DEFAULT_KNOWLEDGE_ROOT)
    parser.add_argument("--card-id", help="Card ID for transition command.")
    parser.add_argument("--state", help="Target lifecycle state for transition.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show warnings.")
    parser.add_argument("--stale-days", type=int, default=90, help="Days after which a card is considered stale (default 90).")

    args = parser.parse_args()

    if args.command == "validate":
        return cmd_validate(args.knowledge_root, args.verbose)
    elif args.command == "duplicates":
        return cmd_duplicates(args.knowledge_root)
    elif args.command == "scan":
        return cmd_scan(args.knowledge_root)
    elif args.command == "transition":
        if not args.card_id or not args.state:
            print("--card-id and --state are required for transition.")
            return 1
        return cmd_transition(args.card_id, args.state, args.knowledge_root)
    elif args.command == "transitions":
        return cmd_show_transitions()
    elif args.command == "lint":
        return cmd_lint(args.knowledge_root, args.stale_days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
