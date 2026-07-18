"""Report payloads and text formatters for the Scholar Agent CLI.

Split out of :mod:`scholar_agent.cli` (pure move, no behavior change):
``doctor`` / ``health`` / ``config show`` payload builders plus the pure
text-formatting helpers shared by their ``--format text`` output. This module
never imports cli or server — the dependency direction stays cli → reports.
"""

from __future__ import annotations

import importlib.util
import json
import locale
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scholar_agent.config.loader import resolve_config
from scholar_agent.config.paths import get_user_config_path, get_user_home
from scholar_agent.engine import scholar_config
from scholar_agent.engine.common import is_reserved_knowledge_path
from scholar_agent.engine.knowledge_lifecycle import scan_stale_card_summaries

if TYPE_CHECKING:
    from collections.abc import Callable


def _append_text_lines(lines: list[str], key: str, value: object, *, indent: str = "") -> None:
    if isinstance(value, dict):
        lines.append(f"{indent}{key}:")
        if not value:
            lines.append(f"{indent}  {{}}")
            return
        for nested_key, nested_value in value.items():
            _append_text_lines(lines, nested_key, nested_value, indent=f"{indent}  ")
        return

    if isinstance(value, list):
        if not value:
            lines.append(f"{indent}{key}: []")
            return
        lines.append(f"{indent}{key}:")
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{indent}  - {json.dumps(item, ensure_ascii=False)}")
            else:
                lines.append(f"{indent}  - {item}")
        return

    lines.append(f"{indent}{key}: {value}")


def _format_mapping_text(payload: dict[str, object]) -> str:
    lines: list[str] = []
    for key, value in payload.items():
        _append_text_lines(lines, key, value)
    return "\n".join(lines)


def _doctor_payload(host: str = "all", *, status_install_payload: Callable[..., dict[str, object]]) -> dict[str, Any]:
    config_file = scholar_config.get_config_file_path()
    knowledge_dir = Path(scholar_config.get_knowledge_dir())
    index_path = Path(scholar_config.get_index_path())
    user_home = get_user_home()

    checks: list[dict[str, object]] = []

    # Directories
    for label, p in [("knowledge_dir", knowledge_dir), ("index_dir", index_path.parent)]:
        exists = p.exists()
        writable = os.access(p if exists else p.parent, os.W_OK)
        checks.append({"check": label, "path": str(p), "exists": exists, "writable": writable})

    # Index validity
    index_exists = index_path.exists()
    index_valid = False
    if index_exists:
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            index_valid = bool(data.get("documents"))
        except Exception:
            pass
    checks.append({"check": "index", "path": str(index_path), "exists": index_exists, "valid": index_valid})

    # Knowledge cards count
    card_count = 0
    if knowledge_dir.exists():
        card_count = sum(1 for path in knowledge_dir.rglob("*.md") if not is_reserved_knowledge_path(path))

    selected_hosts = ["claude", "vscode", "opencode"] if host == "all" else [host]
    mcp_hosts: dict[str, dict[str, object]] = {}
    for selected in selected_hosts:
        try:
            status_payload = status_install_payload(host=selected, path="", scope="user")
            mcp_hosts[selected] = {
                "status": status_payload.get("status", "unknown"),
                "host": selected,
                "installed": bool(status_payload.get("installed", False)),
                "method": status_payload.get("method"),
                "path": status_payload.get("path") or status_payload.get("config_path"),
                "scope": status_payload.get("scope"),
            }
        except Exception as exc:
            mcp_hosts[selected] = {
                "status": "error",
                "host": selected,
                "installed": False,
                "message": str(exc),
            }
    claude_registered = bool(mcp_hosts.get("claude", {}).get("installed", False))

    # Executable resolution — verify scholar-agent module is importable
    module_runnable = importlib.util.find_spec("scholar_agent.cli") is not None
    exe_on_path = shutil.which("scholar-agent")

    # PyMuPDF (PDF image extraction)
    pymupdf_available = importlib.util.find_spec("fitz") is not None

    # fastmcp
    fastmcp_available = importlib.util.find_spec("fastmcp") is not None

    return {
        "status": "ok",
        "mode": scholar_config.detect_runtime_mode(),
        "config_file": str(config_file) if config_file is not None else None,
        "user_home": str(user_home),
        "user_config_path": str(get_user_config_path()),
        "knowledge_dir": str(knowledge_dir),
        "index_path": str(index_path),
        "knowledge_cards": card_count,
        "scholar_dir": str(scholar_config.get_scholar_dir()),
        "checks": checks,
        "dependencies": {
            "fastmcp": fastmcp_available,
            "PyMuPDF": pymupdf_available,
        },
        "mcp": {
            "claude_registered": claude_registered,
            "requested_host": host,
            "hosts": mcp_hosts,
        },
        "executable": {
            "scholar_agent_on_path": exe_on_path is not None,
            "scholar_agent_path": exe_on_path,
            "module_runnable": module_runnable,
            "python_executable": sys.executable,
        },
        "environment": {
            "SCHOLAR_HOME": os.environ.get("SCHOLAR_HOME"),
            "SCHOLAR_PROFILE": os.environ.get("SCHOLAR_PROFILE"),
            "SCHOLAR_TOOLSET": os.environ.get("SCHOLAR_TOOLSET"),
            "SCHOLAR_ACADEMIC": os.environ.get("SCHOLAR_ACADEMIC"),
            "locale_encoding": locale.getpreferredencoding(False),
            "PYTHONUTF8": os.environ.get("PYTHONUTF8"),
        },
    }


def _format_doctor_text(payload: dict[str, object]) -> str:
    lines: list[str] = []
    problems: list[str] = []

    lines.append(f"mode:            {payload['mode']}")
    lines.append(f"config_file:     {payload['config_file']}")
    lines.append(f"user_home:       {payload['user_home']}")
    lines.append(f"knowledge_dir:   {payload['knowledge_dir']}")
    lines.append(f"index_path:      {payload['index_path']}")
    lines.append(f"knowledge cards: {payload['knowledge_cards']}")
    lines.append("")

    # Dependencies
    deps = payload.get("dependencies", {})
    if isinstance(deps, dict):
        lines.append("Dependencies:")
        for name, ok in deps.items():
            icon = "ok" if ok else "MISSING"
            lines.append(f"  {name}: {icon}")
            if not ok and name == "PyMuPDF":
                problems.append(
                    "PyMuPDF not installed — PDF image extraction will not work. Install with: pip install PyMuPDF"
                )
            if not ok and name == "fastmcp":
                problems.append("fastmcp not found — MCP server will not start. Install with: pip install -e .")

    # MCP registration
    mcp = payload.get("mcp", {})
    if isinstance(mcp, dict):
        lines.append("")
        lines.append("MCP Registration:")
        hosts = mcp.get("hosts", {})
        requested_host = str(mcp.get("requested_host") or "claude")
        if isinstance(hosts, dict) and hosts:
            for host_name in ("claude", "vscode", "opencode"):
                host_info = hosts.get(host_name)
                if not isinstance(host_info, dict):
                    continue
                installed = bool(host_info.get("installed", False))
                if host_info.get("status") == "error":
                    state = f"ERROR ({host_info.get('message', 'unknown error')})"
                else:
                    state = "registered" if installed else "not registered"
                detail = host_info.get("path") or host_info.get("scope") or host_info.get("method")
                suffix = f" [{detail}]" if detail else ""
                lines.append(f"  {host_name}: {state}{suffix}")
                if requested_host != "all" and not installed:
                    problems.append(f"{host_name} MCP not registered. Run: scholar-agent install {host_name} --write")
        else:
            claude_ok = mcp.get("claude_registered", False)
            icon = "registered" if claude_ok else "NOT registered"
            lines.append(f"  claude: {icon}")
            if not claude_ok:
                problems.append("Claude Code MCP not registered. Run: scholar-agent init")

    # Executable resolution
    exe_info = payload.get("executable", {})
    if isinstance(exe_info, dict):
        lines.append("")
        lines.append("Executable:")
        on_path = exe_info.get("scholar_agent_on_path", False)
        module_ok = exe_info.get("module_runnable", False)
        lines.append(f"  on PATH: {'yes' if on_path else 'no'}")
        lines.append(f"  python -m scholar_agent.cli: {'ok' if module_ok else 'BROKEN'}")
        lines.append(f"  python: {exe_info.get('python_executable', '?')}")
        if not module_ok:
            problems.append(
                "scholar_agent.cli module not importable — MCP server will not start. Reinstall with: pip install -e ."
            )

    # Directory checks
    checks = payload.get("checks", [])
    if isinstance(checks, list) and checks:
        lines.append("")
        lines.append("Directories:")
        for c in checks:
            if not isinstance(c, dict):
                continue
            name = c.get("check", "")
            exists = c.get("exists", False)
            if name == "index":
                valid = c.get("valid", False)
                if not exists:
                    lines.append("  index: not found (will build on first query)")
                elif not valid:
                    lines.append("  index: empty (will rebuild on first query)")
                else:
                    lines.append("  index: ok")
            else:
                writable = c.get("writable", False)
                icon = "ok" if exists and writable else "MISSING" if not exists else "NOT WRITABLE"
                lines.append(f"  {name}: {icon}")
                if not exists:
                    problems.append(f"{name} does not exist: {c.get('path', '?')}")
                elif not writable:
                    problems.append(f"{name} is not writable: {c.get('path', '?')}")

    # Environment
    environment = payload.get("environment", {})
    if isinstance(environment, dict):
        env_set = {k: v for k, v in environment.items() if v is not None}
        if env_set:
            lines.append("")
            lines.append("Environment:")
            for key, value in env_set.items():
                lines.append(f"  {key}: {value}")

    # Problems summary
    if problems:
        lines.append("")
        lines.append(f"Problems ({len(problems)}):")
        for p in problems:
            lines.append(f"  - {p}")
    else:
        lines.append("")
        lines.append("All checks passed.")

    return "\n".join(lines)


def _health_payload() -> dict[str, Any]:
    from scholar_agent.engine.academic.note_linker import find_dangling_links
    from scholar_agent.engine.knowledge_lifecycle import detect_duplicates, scan_knowledge_dir

    knowledge_dir = Path(scholar_config.get_knowledge_dir())
    index_path = Path(scholar_config.get_index_path())
    embedding_path = index_path.parent / "embeddings.json"

    index_exists = index_path.exists()
    index_valid = False
    index_documents = 0
    if index_exists:
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
            documents = index_data.get("documents", [])
            index_documents = len(documents) if isinstance(documents, list) else 0
            index_valid = index_documents > 0
        except Exception:
            index_valid = False

    cards = scan_knowledge_dir(knowledge_dir) if knowledge_dir.exists() else []
    duplicates = detect_duplicates(cards) if len(cards) >= 2 else []
    stale_cards = scan_stale_card_summaries(knowledge_dir) if knowledge_dir.exists() else []

    dangling: list[dict[str, Any]] = []
    try:
        notes_dirs = [str(scholar_config.get_paper_notes_dir())]
        dangling = find_dangling_links(notes_dirs, knowledge_dir=str(knowledge_dir))
    except Exception:
        dangling = []

    warnings: list[str] = []
    if not knowledge_dir.exists():
        warnings.append("knowledge_dir_missing")
    if not index_exists:
        warnings.append("index_missing")
    elif not index_valid:
        warnings.append("index_empty_or_invalid")
    if stale_cards:
        warnings.append("stale_cards_present")
    if duplicates:
        warnings.append("possible_duplicates_present")
    if dangling:
        warnings.append("dangling_links_present")

    return {
        "status": "ok" if not warnings else "warn",
        "warnings": warnings,
        "config": {
            "mode": scholar_config.detect_runtime_mode(),
            "config_file": str(scholar_config.get_config_file_path())
            if scholar_config.get_config_file_path() is not None
            else None,
            "knowledge_dir": str(knowledge_dir),
            "index_path": str(index_path),
        },
        "index": {
            "exists": index_exists,
            "valid": index_valid,
            "documents": index_documents,
            "embedding_index_exists": embedding_path.exists(),
            "embedding_index_path": str(embedding_path),
        },
        "knowledge": {
            "cards": len(cards),
            "stale_count": len(stale_cards),
            "duplicate_count": len(duplicates),
            "dangling_count": len(dangling),
        },
        "samples": {
            "stale": stale_cards[:10],
            "duplicates": [
                {
                    "left": cards[a].get("id", f"card_{a}") if a < len(cards) else f"card_{a}",
                    "right": cards[b].get("id", f"card_{b}") if b < len(cards) else f"card_{b}",
                    "score": score,
                    "reason": reason,
                }
                for a, b, score, reason in duplicates[:10]
            ],
            "dangling": dangling[:10],
        },
    }


def _format_health_text(payload: dict[str, object]) -> str:
    lines = ["Scholar Agent Health", "====================", ""]

    status = payload.get("status", "unknown")
    warnings = payload.get("warnings", [])
    lines.append(f"status: {status}")
    if isinstance(warnings, list) and warnings:
        lines.append("warnings:")
        for warning in warnings:
            lines.append(f"  - {warning}")
    else:
        lines.append("warnings: []")

    config = payload.get("config", {})
    if isinstance(config, dict):
        lines.append("")
        lines.append("Config:")
        lines.append(f"  mode: {config.get('mode')}")
        lines.append(f"  config_file: {config.get('config_file')}")
        lines.append(f"  knowledge_dir: {config.get('knowledge_dir')}")
        lines.append(f"  index_path: {config.get('index_path')}")

    index = payload.get("index", {})
    if isinstance(index, dict):
        lines.append("")
        lines.append("Index:")
        lines.append(f"  exists: {index.get('exists')}")
        lines.append(f"  valid: {index.get('valid')}")
        lines.append(f"  documents: {index.get('documents')}")
        lines.append(f"  embedding_index_exists: {index.get('embedding_index_exists')}")

    knowledge = payload.get("knowledge", {})
    if isinstance(knowledge, dict):
        lines.append("")
        lines.append("Knowledge:")
        lines.append(f"  cards: {knowledge.get('cards')}")
        lines.append(f"  stale: {knowledge.get('stale_count')}")
        lines.append(f"  possible duplicates: {knowledge.get('duplicate_count')}")
        lines.append(f"  dangling links: {knowledge.get('dangling_count')}")

    samples = payload.get("samples", {})
    if isinstance(samples, dict):
        stale = samples.get("stale", [])
        duplicates = samples.get("duplicates", [])
        dangling = samples.get("dangling", [])
        if stale:
            lines.append("")
            lines.append("Stale Samples:")
            for item in stale[:5] if isinstance(stale, list) else []:
                if isinstance(item, dict):
                    lines.append(f"  - {item.get('path')} ({item.get('days_stale')} days)")
        if duplicates:
            lines.append("")
            lines.append("Duplicate Samples:")
            for item in duplicates[:5] if isinstance(duplicates, list) else []:
                if isinstance(item, dict):
                    lines.append(f"  - {item.get('left')} <-> {item.get('right')} ({item.get('reason')})")
        if dangling:
            lines.append("")
            lines.append("Dangling Samples:")
            for item in dangling[:5] if isinstance(dangling, list) else []:
                if isinstance(item, dict):
                    lines.append(f"  - {item.get('file')}: {item.get('link')}")

    return "\n".join(lines)


def _config_show_payload() -> dict[str, Any]:
    resolution = resolve_config()
    return {
        "mode": resolution.mode,
        "config_file": str(resolution.config_file) if resolution.config_file is not None else None,
        "user_home": str(get_user_home()),
        "user_config_path": str(get_user_config_path()),
        "resolved": resolution.config,
    }


def _format_config_show_text(payload: dict[str, object]) -> str:
    lines = [
        f"mode: {payload['mode']}",
        f"config_file: {payload['config_file']}",
        f"user_home: {payload['user_home']}",
        f"user_config_path: {payload['user_config_path']}",
        "resolved:",
    ]
    resolved = payload.get("resolved", {})
    if isinstance(resolved, dict):
        for key, value in resolved.items():
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)
