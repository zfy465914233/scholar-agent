"""One-time migration: reorganize flat knowledge/ into hierarchical structure.

Moves 14 operations-research sub-folders under a new operations-research/ parent,
updates topic frontmatter on all cards.

Usage:
    python -m scholar_agent.engine.migrate_hierarchy --knowledge-root ../knowledge --dry-run
    python -m scholar_agent.engine.migrate_hierarchy --knowledge-root ../knowledge
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from scholar_agent.engine.common import parse_frontmatter
from scholar_agent.engine.domain_router import clear_folder_cache

OR_CHILDREN = [
    "linear-programming",
    "integer-programming",
    "dynamic-programming",
    "graph-theory",
    "nonlinear-programming",
    "game-theory",
    "decision-theory",
    "queueing-theory",
    "inventory-theory",
    "scheduling",
    "transportation",
    "metaheuristics",
    "applications",
    "interdisciplinary",
]

TOP_LEVEL = [
    "probability-statistics",
    "general",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate flat knowledge/ to hierarchical structure.")
    parser.add_argument("--knowledge-root", type=Path, default=Path("knowledge"))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def update_topic_frontmatter(card_path: Path, new_topic: str, dry_run: bool) -> None:
    raw = card_path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        return
    new_raw = re.sub(
        r"^topic:\s*.+$",
        f"topic: {new_topic}",
        raw,
        count=1,
        flags=re.MULTILINE,
    )
    if new_raw != raw:
        if dry_run:
            print(f"  [frontmatter] {card_path.name}: topic -> {new_topic}")
        else:
            card_path.write_text(new_raw, encoding="utf-8")


def migrate(knowledge_root: Path, dry_run: bool) -> None:
    or_dir = knowledge_root / "operations-research"

    if dry_run:
        print(f"Would create: {or_dir}/")
    else:
        or_dir.mkdir(parents=True, exist_ok=True)

    for folder_name in OR_CHILDREN:
        src = knowledge_root / folder_name
        dst = or_dir / folder_name
        if not src.exists():
            print(f"  [skip] {folder_name}/ not found")
            continue
        if dst.exists():
            print(f"  [skip] {folder_name}/ already at destination")
            continue

        if dry_run:
            print(f"Would move: {src} -> {dst}")
        else:
            shutil.move(str(src), str(dst))

        if dst.exists() or dry_run:
            target = dst if not dry_run else src
            for card in target.rglob("*.md"):
                new_topic = f"operations-research/{folder_name}"
                update_topic_frontmatter(card, new_topic, dry_run)

    for folder_name in TOP_LEVEL:
        folder = knowledge_root / folder_name
        if not folder.exists():
            continue
        for card in folder.rglob("*.md"):
            update_topic_frontmatter(card, folder_name, dry_run)

    if not dry_run:
        clear_folder_cache()


def main() -> int:
    args = parse_args()
    knowledge_root = args.knowledge_root.resolve()
    if not knowledge_root.exists():
        print(f"Error: {knowledge_root} does not exist")
        return 1

    print(f"Knowledge root: {knowledge_root}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print()

    migrate(knowledge_root, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
