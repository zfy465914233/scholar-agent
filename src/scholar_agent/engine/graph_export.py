"""Machine-readable knowledge-graph export (schema_version 1).

Builds the versioned JSON contract consumed by the PaperPulse frontend
(loopback ``GET /graph``), the CLI (``scholar-agent graph --json``), and the
vis.js HTML visualization (:mod:`scholar_agent.engine.build_graph`).

Contract::

    {"schema_version": 1,
     "nodes": [{"id", "title", "node_type", "topic", "domain", "tags",
                "year", "arxiv_id", "venue", "domains", "is_local"}],
     "edges": [{"source", "target", "rel_type", "confidence", "origin",
                ("reason" for cloud edges)}],
     "stats": {"local_nodes": N, "local_edges": M, "cloud_edges": K}}

Node classification: path under ``paper-notes`` or tag ``论文笔记`` →
``paper-note``; path under ``daily-notes`` → ``daily-note``; index type
``knowledge`` → ``knowledge-card``; otherwise ``other``.

``arxiv_id`` bridging (paper-notes only): first the note's frontmatter
(``arxiv_id``/``paper_id``, read from the file head — frontmatter lives at
the top), then a normalized-title match against the PaperStore papers table.
Cloud relation edges (synced from PaperPulse into ``paper_relations``) are
merged only when BOTH ends resolve to local docs; cloud-only papers never
appear as nodes in this phase.

Everything degrades gracefully: a missing/unreadable index yields an empty
graph; an unreadable note yields a node without ``arxiv_id``; an unavailable
paper store simply drops the bridging/cloud-edge extras.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scholar_agent.engine.common import parse_frontmatter, resolve_link_target

if TYPE_CHECKING:
    from scholar_agent.engine.paper_store import PaperStore

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Frontmatter sits at the top of the note; reading the head avoids parsing
# full bodies (same pattern as daily_workflow.get_analyzed_paper_ids).
_NOTE_HEAD_BYTES = 4096

_ARXIV_PREFIX_RE = re.compile(r"^arxiv:\s*", re.IGNORECASE)
_YEAR_RE = re.compile(r"(\d{4})")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """Normalize a title for fuzzy matching: lowercase, punctuation → space, collapse whitespace."""
    text = _NON_ALNUM_RE.sub(" ", title.lower())
    return _WHITESPACE_RE.sub(" ", text).strip()


def extract_arxiv_id(meta: dict[str, Any]) -> str | None:
    """Pull an arXiv id from note frontmatter (``arxiv_id`` or ``paper_id``).

    The id is historically stored under ``paper_id``, sometimes with an
    ``arXiv:`` prefix (see note_linker.build_arxiv_id_to_stem).
    """
    raw = meta.get("arxiv_id") or meta.get("paper_id") or ""
    text = _ARXIV_PREFIX_RE.sub("", str(raw)).strip()
    return text or None


def read_note_frontmatter(note_path: Path) -> dict[str, Any]:
    """Parse frontmatter from the first ~4KB of a markdown note. Never raises."""
    try:
        with note_path.open(encoding="utf-8", errors="replace") as fh:
            raw = fh.read(_NOTE_HEAD_BYTES)
    except OSError:
        return {}
    meta, _ = parse_frontmatter(raw)
    return meta


def _empty_export() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "nodes": [],
        "edges": [],
        "stats": {"local_nodes": 0, "local_edges": 0, "cloud_edges": 0},
    }


def _load_documents(index_path: Path) -> list[dict[str, Any]]:
    try:
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    documents = index_data.get("documents", [])
    if not isinstance(documents, list):
        return []
    return [doc for doc in documents if isinstance(doc, dict)]


def _classify_node(doc: dict[str, Any], tags: list[str]) -> str:
    path = str(doc.get("path", "") or "")
    if "paper-notes" in path or "论文笔记" in tags:
        return "paper-note"
    if "daily-notes" in path:
        return "daily-note"
    if doc.get("type") == "knowledge":
        return "knowledge-card"
    return "other"


def _parse_year(value: Any) -> int | None:
    """Extract a plausible 4-digit year from a date-ish value."""
    if value is None:
        return None
    match = _YEAR_RE.search(str(value))
    if not match:
        return None
    year = int(match.group(1))
    return year if 1900 <= year <= 2100 else None


def _open_paper_store() -> PaperStore | None:
    """Open the configured paper store for read-only lookups; None when unavailable.

    Deliberately does NOT call ``initialize()`` — export is a read path and
    must not migrate (or even create) the database as a side effect.
    """
    try:
        from scholar_agent.engine.paper_store import PaperStore
        from scholar_agent.engine.scholar_config import get_paper_db_path

        db_path = get_paper_db_path()
        if not db_path.exists():
            return None
        return PaperStore(db_path)
    except Exception:
        logger.debug("paper store unavailable for graph export", exc_info=True)
        return None


def _store_title_map(store: PaperStore | None) -> dict[str, str]:
    """{normalized_title: arxiv_id} over all stored papers with an arXiv id."""
    if store is None:
        return {}
    try:
        pairs = store.get_title_arxiv_map()
    except Exception:
        logger.debug("paper store title scan failed", exc_info=True)
        return {}
    mapping: dict[str, str] = {}
    for title, arxiv_id in pairs.items():
        norm = normalize_title(title)
        if norm and arxiv_id:
            mapping.setdefault(norm, arxiv_id)
    return mapping


def build_graph_export(index_path: Path | None = None, *, include_cloud: bool = True) -> dict[str, Any]:
    """Build the versioned graph export from the local index.

    Args:
        index_path: Path to the local JSON index. Defaults to the configured
            ``index_path``.
        include_cloud: Merge PaperPulse relation edges stored in the paper
            store (only edges whose both ends resolve to local docs).

    Returns:
        The schema_version-1 contract dict (JSON-serializable). Never raises:
        missing/unreadable inputs degrade to an empty or partial graph.
    """
    if index_path is None:
        from scholar_agent.engine.scholar_config import get_index_path

        index_path = get_index_path()
    documents = _load_documents(Path(index_path))
    if not documents:
        return _empty_export()

    all_ids = {str(doc.get("doc_id", "")).strip() for doc in documents}
    all_ids.discard("")

    store = _open_paper_store()
    try:
        store_titles = _store_title_map(store)
        nodes, arxiv_to_doc = _build_nodes(documents, store_titles)
        edges = _build_local_edges(documents, all_ids)
        cloud_edges = 0
        if include_cloud:
            cloud_edges = _merge_cloud_edges(edges, nodes, arxiv_to_doc, store, store_titles)
    finally:
        if store is not None:
            store.close()

    return {
        "schema_version": SCHEMA_VERSION,
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "local_nodes": len(nodes),
            "local_edges": len(edges) - cloud_edges,
            "cloud_edges": cloud_edges,
        },
    }


def _build_nodes(
    documents: list[dict[str, Any]],
    store_titles: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Build export nodes plus the {arxiv_id: doc_id} bridge map."""
    nodes: list[dict[str, Any]] = []
    arxiv_to_doc: dict[str, str] = {}

    for doc in documents:
        doc_id = str(doc.get("doc_id", "")).strip()
        if not doc_id:
            continue
        raw_tags = doc.get("tags") or []
        tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else [str(raw_tags)]
        node_type = _classify_node(doc, tags)
        title = str(doc.get("title") or doc_id)
        domain = str(doc.get("domain") or "")

        arxiv_id: str | None = None
        venue: str | None = None
        year: int | None = None
        if node_type == "paper-note":
            raw_path = str(doc.get("path") or "")
            meta = read_note_frontmatter(Path(raw_path)) if raw_path else {}
            arxiv_id = extract_arxiv_id(meta)
            raw_venue = str(meta.get("conference") or "").strip()
            venue = raw_venue or None
            year = _parse_year(meta.get("date"))
            if arxiv_id is None:
                # Fallback: normalized title match against the paper store.
                arxiv_id = store_titles.get(normalize_title(title))
        if year is None:
            year = _parse_year(doc.get("updated_at"))

        if arxiv_id:
            arxiv_to_doc[arxiv_id] = doc_id

        nodes.append(
            {
                "id": doc_id,
                "title": title,
                "node_type": node_type,
                "topic": str(doc.get("topic") or ""),
                "domain": domain,
                "tags": tags,
                "year": year,
                "arxiv_id": arxiv_id,
                "venue": venue,
                "domains": [domain] if domain else tags,
                "is_local": True,
            }
        )
    return nodes, arxiv_to_doc


def _build_local_edges(documents: list[dict[str, Any]], all_ids: set[str]) -> list[dict[str, Any]]:
    """Wiki-link edges with resolve_link_target semantics; dangling/self links skipped."""
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for doc in documents:
        doc_id = str(doc.get("doc_id", "")).strip()
        if not doc_id:
            continue
        raw_links = doc.get("links") or []
        links = raw_links if isinstance(raw_links, list) else [raw_links]
        for link in links:
            target = resolve_link_target(str(link), all_ids)
            if target is None or target == doc_id:
                continue
            key = (doc_id, target)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "source": doc_id,
                    "target": target,
                    "rel_type": "references",
                    "confidence": 1.0,
                    "origin": "local",
                }
            )
    return edges


def _merge_cloud_edges(
    edges: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    arxiv_to_doc: dict[str, str],
    store: PaperStore | None,
    store_titles: dict[str, str],
) -> int:
    """Append PaperPulse relation edges whose both ends resolve to local docs.

    Resolution order per relation key: (1) the arXiv bridge built from local
    paper-notes, (2) PaperStore arXiv → title → normalized local doc title.
    Returns the number of cloud edges appended.
    """
    if store is None:
        return 0
    try:
        relations = store.get_relations()
    except Exception:
        # e.g. older DB without the paper_relations table — no cloud edges yet.
        logger.debug("paper_relations unavailable; skipping cloud edges", exc_info=True)
        return 0

    norm_title_to_doc = {normalize_title(node["title"]): node["id"] for node in nodes}
    # arXiv → normalized store title, for resolution path (2).
    arxiv_to_norm_title: dict[str, str] = {}
    for norm_title, arxiv_id in store_titles.items():
        arxiv_to_norm_title.setdefault(arxiv_id, norm_title)

    def _resolve_key(key: str) -> str | None:
        if key in arxiv_to_doc:
            return arxiv_to_doc[key]
        norm = arxiv_to_norm_title.get(key)
        if norm:
            return norm_title_to_doc.get(norm)
        return None

    appended = 0
    for rel in relations:
        source = _resolve_key(str(rel.get("source_key", "")))
        target = _resolve_key(str(rel.get("target_key", "")))
        if source is None or target is None or source == target:
            continue
        try:
            confidence = float(rel.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        edges.append(
            {
                "source": source,
                "target": target,
                "rel_type": str(rel.get("rel_type") or "cites"),
                "confidence": confidence,
                "reason": rel.get("reason"),
                "origin": "paperpulse",
            }
        )
        appended += 1
    return appended
