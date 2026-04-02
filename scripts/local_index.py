"""Build a minimal JSON index from local knowledge cards."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a local JSON index from Markdown knowledge cards.")
    parser.add_argument(
        "--knowledge-root",
        type=Path,
        default=Path("knowledge"),
        help="Root directory containing local knowledge files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("indexes/local/index.json"),
        help="Output path for the generated index.",
    )
    return parser.parse_args()


def parse_card(path: Path) -> dict[str, object]:
    raw = path.read_text(encoding="utf-8")
    metadata, body = split_frontmatter(raw)
    return {
        "doc_id": str(metadata.get("id", path.stem)),
        "path": str(path.as_posix()),
        "title": str(metadata.get("title", path.stem)),
        "type": str(metadata.get("type", "unknown")),
        "topic": str(metadata.get("topic", "")),
        "tags": metadata.get("tags", []),
        "source_refs": metadata.get("source_refs", []),
        "updated_at": metadata.get("updated_at"),
        "search_text": build_search_text(metadata, body),
    }


def split_frontmatter(raw: str) -> tuple[dict[str, object], str]:
    if not raw.startswith("---\n"):
        return {}, raw

    parts = raw.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, raw

    frontmatter, body = parts
    metadata = parse_frontmatter(frontmatter.splitlines()[1:])
    return metadata, body.strip()


def parse_frontmatter(lines: list[str]) -> dict[str, object]:
    data: dict[str, object] = {}
    current_key: str | None = None
    current_list: list[str] | None = None

    for line in lines:
        if not line.strip():
            continue

        if line.startswith("  - ") and current_key is not None and current_list is not None:
            current_list.append(line[4:].strip())
            continue

        if line.startswith("- ") and current_key is not None and current_list is not None:
            current_list.append(line[2:].strip())
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()

        if not value:
            current_key = key
            current_list = []
            data[key] = current_list
            continue

        current_key = None
        current_list = None
        data[key] = normalize_scalar(value)

    return data


def normalize_scalar(value: str) -> str:
    return value.strip().strip("'").strip('"')


def build_search_text(metadata: dict[str, object], body: str) -> str:
    parts: list[str] = []
    for key in ("title", "topic"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    tags = metadata.get("tags", [])
    if isinstance(tags, list):
        parts.extend(str(tag) for tag in tags)
    parts.append(body)
    return " ".join(part for part in parts if part).strip()


def iter_cards(knowledge_root: Path) -> list[Path]:
    return sorted(
        path
        for path in knowledge_root.rglob("*.md")
        if "templates" not in path.parts and path.is_file()
    )


def build_index(knowledge_root: Path) -> dict[str, object]:
    documents = [parse_card(path) for path in iter_cards(knowledge_root)]
    return {
        "knowledge_root": str(knowledge_root.as_posix()),
        "documents": documents,
    }


def main() -> int:
    args = parse_args()
    payload = build_index(args.knowledge_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
