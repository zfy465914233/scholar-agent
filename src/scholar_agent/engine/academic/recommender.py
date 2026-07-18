"""Public, MCP-free entry point for the paper recommendation engine.

Both the local shells (the MCP ``daily_recommend`` tool and the
``scholar-agent daily-process`` CLI) and external library consumers call
:func:`generate_recommendations` with the same ``.scholar.json`` config
semantics and receive the same versioned output schema — this module owns
the config glue that used to be duplicated across the shells:

  load .scholar.json → resolve research interests → merge
  academic.daily_recommend + academic.unified_pipeline → run the
  pipeline → normalize the result.

The engine returns data only; file-writing side effects (paper notes,
daily digest notes, wiki-linking) stay in the shells.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

#: Version of the :func:`generate_recommendations` output schema. Bump when
#: the normalized top-level or per-paper keys change incompatibly.
SCHEMA_VERSION = 1


def generate_recommendations(
    config: dict[str, Any] | None = None,
    *,
    date: str | datetime | None = None,
    top_n: int = 10,
    skip_existing: bool = True,
    dual_track: bool = True,
    config_path: str = "",
    paper_notes_dir: str | None = None,
) -> dict[str, Any]:
    """Generate daily paper recommendations and return a stable schema dict.

    Args:
        config: Full ``.scholar.json`` config dict. When None, it is loaded
            via :func:`scholar_config.load_config` (process-wide cache) —
            pass an explicit dict to run the engine as a library with your
            own configuration.
        date: Target date (``datetime`` or ``"YYYY-MM-DD"``); default today.
        top_n: Max papers for the legacy single-track path only.
        skip_existing: Skip papers already recommended/analyzed.
        dual_track: Allow the legacy dual-track fallback path.
        config_path: Optional YAML research-interests file; overrides the
            ``academic.research_interests`` from *config* when non-empty.
        paper_notes_dir: Directory of existing paper notes, used for
            already-analyzed dedup. Defaults to the configured dir.

    Returns:
        Normalized dict (see :data:`SCHEMA_VERSION`) with keys:
        ``schema_version``, ``date``, ``papers`` (normalized per-paper
        dicts), ``stats``, ``warnings``, plus pass-through pipeline fields
        (``skipped``, ``total_found``, ``tracks``, ``dual_track``,
        ``unified_pipeline``).
        The result is JSON-serializable.
    """
    from scholar_agent.engine.academic.daily_workflow import generate_daily_recommendations
    from scholar_agent.engine.scholar_config import get_paper_notes_dir, load_config

    full_config = config if config is not None else load_config()
    academic = full_config.get("academic", {}) if isinstance(full_config, dict) else {}

    research_config = _resolve_research_config(academic, config_path)

    # Merge daily_recommend + unified_pipeline configs (unified_pipeline may
    # live under either key; daily_recommend.unified_pipeline wins).
    daily_config = dict(academic.get("daily_recommend", {}))
    if "unified_pipeline" not in daily_config:
        unified_cfg = academic.get("unified_pipeline", {})
        if unified_cfg:
            daily_config["unified_pipeline"] = unified_cfg

    target_date = _parse_date(date)
    notes_dir = paper_notes_dir or str(get_paper_notes_dir())

    result = generate_daily_recommendations(
        config=research_config,
        paper_notes_dir=notes_dir,
        target_date=target_date,
        top_n=top_n,
        skip_existing=skip_existing,
        dual_track=dual_track,
        daily_config=daily_config,
    )
    return _normalize_result(result, target_date)


def _parse_date(date: str | datetime | None) -> datetime:
    """Normalize the *date* argument to a ``datetime`` (default: now)."""
    if isinstance(date, datetime):
        return date
    if isinstance(date, str) and date.strip():
        return datetime.strptime(date.strip(), "%Y-%m-%d")
    return datetime.now()


def resolve_research_interests(
    *,
    config_path: str = "",
    interests: dict[str, Any] | None = None,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shared research-interests ladder: YAML config → interests → default.

    Single source of truth for the config-resolution ladder used by both the
    library entry point (this module) and the MCP academic tools
    (:mod:`scholar_agent.adapters.mcp_academic`). Path validation and error
    handling stay at the callers' boundaries — this core only resolves the
    ladder and never touches the filesystem beyond ``load_research_config``.
    """
    if config_path:
        from scholar_agent.engine.academic.arxiv_search import load_research_config

        loaded = load_research_config(config_path)
        if loaded:
            return loaded
    if interests and isinstance(interests, dict) and interests.get("research_domains"):
        return {
            "research_domains": interests["research_domains"],
            "excluded_keywords": interests.get("excluded_keywords", []),
        }
    return default if default is not None else {"research_domains": {}, "excluded_keywords": []}


def _resolve_research_config(academic: dict[str, Any], config_path: str) -> dict[str, Any]:
    """Resolve the research-interests ladder for the library entry point."""
    return resolve_research_interests(
        config_path=config_path,
        interests=academic.get("research_interests", {}),
    )


def _normalize_result(result: dict[str, Any], target_date: datetime) -> dict[str, Any]:
    """Normalize a raw pipeline result into the stable versioned schema.

    Papers are augmented in place (the shells still need the pipeline's
    internal fields); every schema key is guaranteed present afterwards.
    """
    papers = [_normalize_paper(p) for p in result.get("papers", [])]
    normalized: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "date": result.get("date") or target_date.strftime("%Y-%m-%d"),
        "papers": papers,
        "stats": result.get("stats", {}),
        "warnings": list(result.get("warnings", [])),
        "skipped": result.get("skipped", 0),
        "total_found": result.get("total_found", 0),
        "dual_track": result.get("dual_track", False),
    }
    for key in ("tracks", "track_errors", "unified_pipeline"):
        if key in result:
            normalized[key] = result[key]
    return normalized


def _normalize_paper(p: dict[str, Any]) -> dict[str, Any]:
    """Guarantee the stable per-paper schema keys on *p* (mutates in place).

    Schema keys: ``arxiv_id``, ``title``, ``abstract``, ``authors``,
    ``url``, ``published_date``, ``categories``, ``scores`` (``fit``,
    ``recommendation``, optional ``llm_novelty``/``llm_credibility``),
    ``recommendation_reason``, ``track``, ``domain``. Pipeline-internal
    fields (``_heuristic_score``, ``best_domain``, …) are preserved.
    """
    arxiv_id = p.get("arxiv_id") or p.get("paper_id") or ""
    if arxiv_id and not p.get("arxiv_id"):
        p["arxiv_id"] = arxiv_id
    p.setdefault("title", "")
    if not p.get("abstract"):
        p["abstract"] = p.get("summary", "") or ""
    if not p.get("url"):
        p["url"] = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""
    p.setdefault("authors", [])
    p.setdefault("categories", [])
    if not p.get("published_date"):
        p["published_date"] = p.get("published") or p.get("publicationDate") or ""
    p.setdefault("recommendation_reason", "")
    p.setdefault("track", "")
    p.setdefault("domain", p.get("best_domain", "") or "")

    scores = p.setdefault("scores", {})
    if "fit" not in scores:
        scores["fit"] = round(p.get("relevance_score", 0) or 0, 2)
    if "recommendation" not in scores:
        scores["recommendation"] = p.get("_heuristic_score", 0) or 0
    for key in ("llm_novelty", "llm_credibility"):
        if key not in scores and p.get(key) is not None:
            scores[key] = p[key]

    # JSON-safety: pipeline sources may carry datetime values (e.g. arXiv
    # published_date); the public schema is plain JSON types only.
    for key, value in list(p.items()):
        if isinstance(value, datetime):
            p[key] = value.isoformat()
    return p
