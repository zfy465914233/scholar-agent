"""Pull paper-relation edges from PaperPulse into the local paper store.

Loopback-pull half of the knowledge-graph sync: fetches the personal graph
overview (``GET /api/v1/graph/overview``), matches cloud nodes to local
papers by normalized title — against PaperStore papers first, then local
paper-note frontmatter titles — and for each matched node fetches its
relation context (``GET /api/v1/graph/papers/{uuid}/context``). Relations
land in the ``paper_relations`` table (schema v3) and are merged into the
graph export/HTML by :mod:`scholar_agent.engine.graph_export`.

Relation direction: outgoing citations and semantic relations are stored as
(local → other); incoming citations are stored flipped (other → local) so a
``cites`` edge always points from the citing paper to the cited one.
Relation keys are arXiv ids when the corresponding paper matched locally,
else the cloud UUID (kept for future use; cloud-only papers do not enter the
graph export this phase).

Auth: the configured ``paperpulse_token`` is a short-lived JWT; a 401 is
reported as an actionable error (re-login), never retried. Transient network
errors are retried with backoff; per-paper failures degrade the run to
``status: "partial"`` instead of aborting it.

HTTP access goes through a single ``_requests.Session`` so tests can patch
``scholar_agent.engine.graph_sync._requests`` (same pattern as
``engine.academic.conf_search``).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from scholar_agent.engine.graph_export import extract_arxiv_id, normalize_title, read_note_frontmatter
from scholar_agent.engine.retry import retry_with_backoff

if TYPE_CHECKING:
    from scholar_agent.engine.paper_store import PaperStore

logger = logging.getLogger(__name__)

try:
    import requests as _requests

    HAS_REQUESTS = True
except ImportError:  # pragma: no cover - requests is a hard dependency
    HAS_REQUESTS = False

_DEFAULT_BASE_URL = "https://mindpulse.top"
_TIMEOUT_S = 15
_RETRY_MAX = 2
_RETRY_BASE_DELAY = 1.0
_POLITE_DELAY_S = 0.2  # pause between per-paper context fetches

# rel_type values kept verbatim from the cloud contract.
_SEMANTIC_REL_TYPES = ("extends", "improves_upon", "baseline_for", "variant_of")

_TOKEN_EXPIRED_MSG = (
    "paperpulse_token expired — re-login to PaperPulse and update paperpulse_token in .scholar.json"
)


class _AuthError(Exception):
    """401 from PaperPulse — surfaced as an actionable error, never retried."""


def _resolve_credentials(token: str | None, base_url: str | None) -> tuple[str, str]:
    from scholar_agent.engine.scholar_config import load_config

    config = load_config()
    effective_token = (token or config.get("paperpulse_token", "")).strip()
    effective_base = (base_url or config.get("paperpulse_url", _DEFAULT_BASE_URL)).rstrip("/")
    return effective_token, effective_base


def _get_json(session: Any, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
    """GET a JSON dict with backoff on transient errors; raises _AuthError on 401."""

    def _once() -> dict[str, Any]:
        resp = session.get(url, params=params, timeout=_TIMEOUT_S)
        if resp.status_code == 401:
            raise _AuthError(url)
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()
        return payload

    return retry_with_backoff(
        _once,
        max_retries=_RETRY_MAX,
        base_delay=_RETRY_BASE_DELAY,
        retry_on=(_requests.exceptions.RequestException,),
    )


def _local_title_map(store: PaperStore | None) -> dict[str, str]:
    """{normalized_title: arxiv_id} from PaperStore papers and paper-note frontmatter."""
    mapping: dict[str, str] = {}
    if store is not None:
        try:
            for title, arxiv_id in store.get_title_arxiv_map().items():
                norm = normalize_title(title)
                if norm and arxiv_id:
                    mapping.setdefault(norm, arxiv_id)
        except Exception:
            logger.debug("paper store title scan failed", exc_info=True)
    try:
        from scholar_agent.engine.scholar_config import get_paper_notes_dir

        notes_dir = get_paper_notes_dir()
        if notes_dir.exists():
            for md in notes_dir.rglob("*.md"):
                meta = read_note_frontmatter(md)
                note_arxiv = extract_arxiv_id(meta)
                norm = normalize_title(str(meta.get("title") or ""))
                if norm and note_arxiv:
                    mapping.setdefault(norm, note_arxiv)
    except Exception:
        logger.debug("paper-note title scan failed", exc_info=True)
    return mapping


def _target_info(item: dict[str, Any]) -> tuple[str | None, str | None, str]:
    """Extract (arxiv_id, cloud_uuid, title) from a relation item, tolerating flat/nested shapes."""
    raw_paper = item.get("paper")
    paper: dict[str, Any] = raw_paper if isinstance(raw_paper, dict) else item
    title = str(paper.get("title") or item.get("title") or "").strip()
    arxiv_id = paper.get("arxiv_id") or item.get("arxiv_id")
    if not arxiv_id and isinstance(paper.get("externalIds"), dict):
        arxiv_id = paper["externalIds"].get("ArXiv")
    uuid = paper.get("id") or paper.get("paper_id") or item.get("paper_id") or item.get("id")
    return (str(arxiv_id) if arxiv_id else None, str(uuid) if uuid else None, title)


def _target_key(
    item: dict[str, Any], title_map: dict[str, str], local_arxivs: set[str]
) -> tuple[str | None, str, str]:
    """Relation key for a target paper + how it was matched.

    Returns ``(key, title, match_method)`` where *match_method* is
    ``arxiv_id_exact`` / ``title_normalized`` / ``cloud_uuid_only`` — the
    provenance consumers need to down-weight fuzzy title matches.
    """
    arxiv_id, uuid, title = _target_info(item)
    norm = normalize_title(title)
    if arxiv_id and arxiv_id in local_arxivs:
        return arxiv_id, title, "arxiv_id_exact"
    if norm and norm in title_map:
        return title_map[norm], title, "title_normalized"
    return (uuid or arxiv_id), title, "cloud_uuid_only"


def _extract_relations(
    context: dict[str, Any],
    source_arxiv: str,
    title_map: dict[str, str],
    local_arxivs: set[str],
) -> list[dict[str, Any]]:
    """Normalize a paper-context response into paper_relations rows."""
    relations: list[dict[str, Any]] = []

    def _confidence(item: dict[str, Any]) -> float:
        try:
            return float(item.get("confidence") or 1.0)
        except (TypeError, ValueError):
            return 1.0

    for item in context.get("citations_outgoing") or []:
        if not isinstance(item, dict):
            continue
        key, title, match_method = _target_key(item, title_map, local_arxivs)
        if key:
            relations.append(
                {
                    "source_key": source_arxiv,
                    "target_key": key,
                    "target_title": title,
                    "rel_type": "cites",
                    "confidence": _confidence(item),
                    "reason": None,
                    "match_method": match_method,
                }
            )
    for item in context.get("citations_incoming") or []:
        if not isinstance(item, dict):
            continue
        # Incoming: the other paper cites the local one — store flipped so
        # the "cites" edge keeps its true direction (citing → cited).
        key, title, match_method = _target_key(item, title_map, local_arxivs)
        if key:
            relations.append(
                {
                    "source_key": key,
                    "target_key": source_arxiv,
                    "target_title": title,
                    "rel_type": "cites",
                    "confidence": _confidence(item),
                    "reason": None,
                    "match_method": match_method,
                }
            )
    for item in context.get("semantic_relations") or []:
        if not isinstance(item, dict):
            continue
        rel_type = str(item.get("rel_type") or "")
        if rel_type not in _SEMANTIC_REL_TYPES:
            continue
        key, title, match_method = _target_key(item, title_map, local_arxivs)
        if key:
            relations.append(
                {
                    "source_key": source_arxiv,
                    "target_key": key,
                    "target_title": title,
                    "rel_type": rel_type,
                    "confidence": _confidence(item),
                    "reason": item.get("reason"),
                    "match_method": match_method,
                }
            )
    return relations


def _error_result(message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": message,
        "matched_papers": 0,
        "relations_upserted": 0,
        "cloud_nodes": 0,
    }


def sync_from_paperpulse(
    *,
    token: str | None = None,
    base_url: str | None = None,
    max_nodes: int = 200,
    min_confidence: float = 0.5,
    store: PaperStore | None = None,
) -> dict[str, Any]:
    """Sync relation edges from PaperPulse into the local paper store.

    Args:
        token: Bearer JWT. Defaults to ``paperpulse_token`` from config.
        base_url: PaperPulse base URL. Defaults to ``paperpulse_url`` from
            config (``https://mindpulse.top``).
        max_nodes: Cap on the personal graph overview size.
        min_confidence: Minimum confidence for semantic relations.
        store: Open (initialized) PaperStore to write into. When omitted, the
            configured database is opened and migrated.

    Returns:
        ``{"status": "ok"|"partial"|"error", "matched_papers": N,
        "relations_upserted": M, "cloud_nodes": K, ...}`` — never raises.
    """
    if not HAS_REQUESTS:
        return _error_result("the 'requests' package is required for graph sync")
    effective_token, effective_base = _resolve_credentials(token, base_url)
    if not effective_token:
        return _error_result(
            "paperpulse_token not configured — log in to PaperPulse and set paperpulse_token in .scholar.json"
        )

    own_store = store is None
    if own_store:
        try:
            from scholar_agent.engine.paper_store import PaperStore
            from scholar_agent.engine.scholar_config import get_paper_db_path

            store = PaperStore(get_paper_db_path())
            store.initialize()
        except Exception as exc:
            return _error_result(f"failed to open the paper store: {exc}")

    session = _requests.Session()
    try:
        assert store is not None  # guaranteed by the own_store branch above
        session.headers.update({"Authorization": f"Bearer {effective_token}"})
        return _sync(session, effective_base, max_nodes, min_confidence, store)
    finally:
        try:
            session.close()
        except Exception:
            logger.debug("session close failed", exc_info=True)
        if own_store and store is not None:
            store.close()


def _sync(
    session: Any,
    base_url: str,
    max_nodes: int,
    min_confidence: float,
    store: PaperStore,
) -> dict[str, Any]:
    try:
        overview = _get_json(session, f"{base_url}/api/v1/graph/overview", params={"max_nodes": max_nodes})
    except _AuthError:
        return _error_result(_TOKEN_EXPIRED_MSG)
    except Exception as exc:
        return _error_result(f"failed to fetch graph overview: {exc}")

    nodes = overview.get("nodes") or []
    cloud_nodes = len(nodes)
    title_map = _local_title_map(store)
    local_arxivs = set(title_map.values())

    matched: list[tuple[str, str]] = []  # (cloud uuid, local arxiv_id)
    for node in nodes:
        if not isinstance(node, dict):
            continue
        uuid = str(node.get("id") or "")
        arxiv_id = title_map.get(normalize_title(str(node.get("title") or "")))
        if uuid and arxiv_id:
            matched.append((uuid, arxiv_id))

    relations: list[dict[str, Any]] = []
    failures = 0
    for i, (uuid, arxiv_id) in enumerate(matched):
        if i:
            time.sleep(_POLITE_DELAY_S)
        try:
            context = _get_json(
                session,
                f"{base_url}/api/v1/graph/papers/{uuid}/context",
                params={"min_confidence": min_confidence},
            )
        except _AuthError:
            return _error_result(_TOKEN_EXPIRED_MSG)
        except Exception as exc:
            failures += 1
            logger.warning("context fetch failed for cloud paper %s: %s", uuid, exc)
            continue
        relations.extend(_extract_relations(context, arxiv_id, title_map, local_arxivs))

    # Reconcile to the cloud snapshot (I4/I5): upsert the edges seen this run,
    # then prune paperpulse edges no longer present. Manual edges are never
    # touched (prune is source-scoped to 'paperpulse'). Pruning ONLY happens on
    # a fully-successful fetch — a partial run is missing edges that still exist
    # in the cloud (their context fetch failed), so pruning would delete valid
    # data. Rerun the full sync to reconcile.
    expected_keys: set[tuple[str | None, str | None, str | None]] = set()
    with store.transaction():
        for relation in relations:
            store.upsert_relation(relation)
            expected_keys.add((relation["source_key"], relation["target_key"], relation["rel_type"]))
        pruned = store.prune_paperpulse_relations(expected_keys) if failures == 0 else 0

    result: dict[str, Any] = {
        "status": "ok" if failures == 0 else "partial",
        "matched_papers": len(matched),
        "relations_upserted": len(expected_keys),
        "relations_pruned": pruned,
        "cloud_nodes": cloud_nodes,
    }
    if failures:
        result["warnings"] = [
            f"context fetch failed for {failures} of {len(matched)} matched paper(s)",
            "reconcile skipped — rerun to prune edges removed from the cloud",
        ]
    return result
