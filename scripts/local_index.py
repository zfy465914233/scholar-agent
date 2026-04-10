"""Build a minimal JSON index from local knowledge cards.

Supports incremental indexing: if an existing index is found alongside a
manifest of file modification times, only changed or new cards are
re-parsed.  Deleted cards are removed from the index automatically.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from common import extract_wiki_links, parse_frontmatter, resolve_link_target

logger = logging.getLogger(__name__)


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
    parser.add_argument(
        "--build-embedding-index",
        action="store_true",
        help="Also build an embedding index alongside the BM25 index.",
    )
    parser.add_argument(
        "--embedding-output",
        type=Path,
        default=Path("indexes/local/embeddings.json"),
        help="Output path for the embedding index.",
    )
    parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Force a full rebuild ignoring any existing manifest.",
    )
    return parser.parse_args()


def parse_card(path: Path) -> dict[str, object]:
    raw = path.read_text(encoding="utf-8")
    metadata, body = split_frontmatter(raw)
    links = extract_wiki_links(body)
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
        "links": links,
    }


def split_frontmatter(raw: str) -> tuple[dict[str, object], str]:
    """Split raw markdown into (frontmatter_dict, body) using common parser."""
    return parse_frontmatter(raw)


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


def is_card(path: Path) -> bool:
    if "templates" in path.parts or path.name.lower() == "readme.md" or not path.is_file():
        return False
    return path.read_text(encoding="utf-8").startswith("---\n")


def iter_cards(knowledge_root: Path) -> list[Path]:
    return sorted(
        path
        for path in knowledge_root.rglob("*.md")
        if is_card(path)
    )


def _manifest_path(index_output: Path) -> Path:
    return index_output.parent / f"{index_output.stem}.manifest.json"


def _load_manifest(index_output: Path) -> dict[str, float]:
    """Load the manifest mapping relative path -> mtime."""
    mp = _manifest_path(index_output)
    if not mp.exists():
        return {}
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_manifest(manifest: dict[str, float], index_output: Path) -> None:
    mp = _manifest_path(index_output)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_backlinks(documents: list[dict]) -> dict[str, list[str]]:
    """Build a mapping of doc_id -> list of doc_ids that link to it.

    Links are resolved by exact doc_id match first, then by partial
    match (target is a substring of the doc_id).
    """
    backlinks: dict[str, list[str]] = {}
    doc_ids = {doc["doc_id"] for doc in documents}

    for doc in documents:
        source_id = doc["doc_id"]
        for target in doc.get("links", []):
            resolved = resolve_link_target(target, doc_ids)
            if resolved and resolved != source_id:
                backlinks.setdefault(resolved, []).append(source_id)

    return backlinks


def _attach_backlinks(documents: list[dict]) -> None:
    """Attach backlink lists to each document in-place."""
    bl_map = build_backlinks(documents)
    for doc in documents:
        doc["backlinks"] = bl_map.get(doc["doc_id"], [])


def build_index(knowledge_root: Path) -> dict[str, object]:
    """Build a full index from scratch."""
    documents = [parse_card(path) for path in iter_cards(knowledge_root)]
    _attach_backlinks(documents)
    return {
        "knowledge_root": str(knowledge_root.as_posix()),
        "documents": documents,
    }


def build_index_incremental(
    knowledge_root: Path,
    index_output: Path,
) -> dict[str, object]:
    """Build index incrementally, only re-parsing changed cards.

    Falls back to a full rebuild if the existing index is missing or corrupt.
    """
    old_manifest = _load_manifest(index_output)
    if not old_manifest:
        logger.info("No manifest found, performing full rebuild")
        payload = build_index(knowledge_root)
        manifest = _build_manifest(payload, knowledge_root)
        _save_manifest(manifest, index_output)
        return payload

    # Load existing index
    try:
        existing = json.loads(index_output.read_text(encoding="utf-8"))
        existing_docs = {doc["path"]: doc for doc in existing.get("documents", [])}
    except (json.JSONDecodeError, OSError, KeyError):
        logger.info("Existing index corrupt, performing full rebuild")
        payload = build_index(knowledge_root)
        manifest = _build_manifest(payload, knowledge_root)
        _save_manifest(manifest, index_output)
        return payload

    card_paths = iter_cards(knowledge_root)

    # Build current manifest using absolute paths as canonical keys
    current_manifest: dict[str, float] = {}
    # Map absolute path -> card Path for quick lookup
    path_by_abs: dict[str, Path] = {}
    for path in card_paths:
        abs_key = str(path.resolve().as_posix())
        current_manifest[abs_key] = path.stat().st_mtime
        path_by_abs[abs_key] = path

    # Determine which cards need re-parsing
    changed: set[str] = set()
    for abs_key, mtime in current_manifest.items():
        if old_manifest.get(abs_key) != mtime:
            changed.add(abs_key)

    # Also add any new cards (not in old manifest)
    for abs_key in current_manifest:
        if abs_key not in old_manifest:
            changed.add(abs_key)

    # Build docs only from cards that currently exist (removes deleted ghosts)
    new_docs: dict[str, dict] = {}
    for abs_key, path in path_by_abs.items():
        if abs_key in changed:
            new_docs[abs_key] = parse_card(path)
        elif abs_key in existing_docs:
            new_docs[abs_key] = existing_docs[abs_key]
        else:
            new_docs[abs_key] = parse_card(path)

    documents = list(new_docs.values())
    _attach_backlinks(documents)

    removed = len(existing_docs) - len(existing_docs.keys() & current_manifest.keys())
    logger.info(
        "Incremental index: %d docs total, %d re-parsed, %d removed",
        len(documents), len(changed & current_manifest.keys()), removed,
    )

    manifest = dict(current_manifest)
    _save_manifest(manifest, index_output)

    return {
        "knowledge_root": str(knowledge_root.as_posix()),
        "documents": documents,
    }


def _build_manifest(payload: dict, knowledge_root: Path) -> dict[str, float]:
    """Build a manifest from a full index payload."""
    manifest: dict[str, float] = {}
    for doc in payload.get("documents", []):
        path_str = doc.get("path", "")
        try:
            p = Path(path_str)
            if p.exists():
                manifest[str(p.resolve().as_posix())] = p.stat().st_mtime
        except OSError:
            pass
    return manifest


def main() -> int:
    args = parse_args()

    if args.full_rebuild or not args.output.exists():
        payload = build_index(args.knowledge_root)
        manifest = _build_manifest(payload, args.knowledge_root)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _save_manifest(manifest, args.output)
    else:
        payload = build_index_incremental(args.knowledge_root, args.output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.build_embedding_index:
        try:
            from embedding_retrieve import build_embedding_index as build_emb
            emb_index = build_emb(payload.get("documents", []))
            valid = sum(1 for e in emb_index["embeddings"] if e)
            total = len(emb_index["doc_ids"])
            args.embedding_output.parent.mkdir(parents=True, exist_ok=True)
            args.embedding_output.write_text(
                json.dumps(emb_index, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            logger.info("Embedding index: %d/%d docs embedded → %s", valid, total, args.embedding_output)
        except Exception as exc:
            logger.warning("embedding index build failed (%s), skipping", exc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
