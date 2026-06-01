#!/usr/bin/env python3
"""Promote a staged paper note into a canonical paper-notes location."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Path to the staged markdown note")
    parser.add_argument("--paper-notes-root", required=True, help="Root paper-notes directory")
    parser.add_argument("--domain", required=True, help="Canonical domain directory name")
    parser.add_argument("--paper-folder", required=True, help="Canonical paper folder name")
    parser.add_argument(
        "--filename-mode",
        default="folder",
        choices=["folder", "note", "explicit"],
        help="folder => <paper-folder>.md, note => note.md, explicit => --filename",
    )
    parser.add_argument("--filename", help="Target filename when --filename-mode explicit")
    parser.add_argument("--promote", action="store_true", help="Move the file into the canonical target")
    parser.add_argument("--overwrite", action="store_true", help="Allow overwriting the target file")
    parser.add_argument(
        "--allow-non-staging",
        action="store_true",
        help="Allow sources outside .staging; default behavior is fail-closed",
    )
    parser.add_argument("--json-indent", type=int, default=2, help="Indentation for JSON output")
    return parser.parse_args()


def build_target_filename(args: argparse.Namespace) -> str:
    if args.filename_mode == "folder":
        return f"{args.paper_folder}.md"
    if args.filename_mode == "note":
        return "note.md"
    if not args.filename:
        raise ValueError("explicit filename mode requires --filename")
    return str(args.filename)


def prune_empty_parents(path: Path, stop_at: Path) -> None:
    current = path.parent
    while current != stop_at and stop_at in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def main() -> int:
    args = parse_args()
    source = Path(args.source).expanduser().resolve()
    root = Path(args.paper_notes_root).expanduser().resolve()

    result: dict[str, Any] = {
        "ok": False,
        "source": str(source),
        "paper_notes_root": str(root),
        "errors": [],
        "warnings": [],
    }

    if not source.exists():
        result["errors"].append("source_not_found")
        print(json.dumps(result, ensure_ascii=False, indent=args.json_indent))
        return 1

    if source.suffix.lower() != ".md":
        result["errors"].append("source_must_be_markdown")
        print(json.dumps(result, ensure_ascii=False, indent=args.json_indent))
        return 1

    try:
        filename = build_target_filename(args)
    except ValueError as exc:
        result["errors"].append(str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=args.json_indent))
        return 1

    staging_root = root / ".staging"
    if not args.allow_non_staging and staging_root not in source.parents:
        result["errors"].append("source_not_in_staging")
        print(json.dumps(result, ensure_ascii=False, indent=args.json_indent))
        return 1

    target_dir = root / args.domain / args.paper_folder
    target = target_dir / filename
    result["target"] = str(target)

    if target.exists() and target != source and not args.overwrite:
        result["errors"].append("target_exists")
        print(json.dumps(result, ensure_ascii=False, indent=args.json_indent))
        return 1

    if not args.promote:
        result["ok"] = True
        result["warnings"].append("dry_run_only")
        print(json.dumps(result, ensure_ascii=False, indent=args.json_indent))
        return 0

    target_dir.mkdir(parents=True, exist_ok=True)
    if target.exists() and args.overwrite:
        target.unlink()

    shutil.move(str(source), str(target))
    if staging_root.exists() and staging_root in source.parents:
        prune_empty_parents(target, stop_at=target_dir)
        prune_empty_parents(source, stop_at=staging_root)

    result["ok"] = True
    print(json.dumps(result, ensure_ascii=False, indent=args.json_indent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
