"""CLI entrypoints for Scholar Agent."""

from __future__ import annotations

import argparse
import importlib.util
import hashlib
import json
import locale
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scholar_agent import runtime as runtime_manager
from scholar_agent.adapters import mcp_server as mcp_adapter
from scholar_agent.config.loader import resolve_config
from scholar_agent.config.manager import initialize_user_home, migrate_to_user_home
from scholar_agent.config.paths import get_user_config_path, get_user_home
from scholar_agent.engine import scholar_config
from scholar_agent.installers import claude as claude_installer
from scholar_agent.installers import opencode as opencode_installer
from scholar_agent.installers import vscode as vscode_installer

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


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


def _print_payload(
    payload: dict[str, object],
    output_format: str,
    *,
    text_formatter: Callable[[dict[str, object]], str] | None = None,
) -> None:
    if output_format == "text":
        formatter = text_formatter or _format_mapping_text
        print(formatter(payload))
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scholar-agent",
        description="Scholar Agent local application and MCP entrypoint.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("serve-mcp", help="Start the Scholar Agent MCP server.")
    subparsers.add_parser("serve-http", help="Start the standalone HTTP sync server for PaperPulse import.")

    init_parser = subparsers.add_parser(
        "init",
        help="One-command setup: create data dirs, write config, register MCP.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing config if it already exists.",
    )
    init_parser.add_argument(
        "--host",
        choices=("claude", "vscode", "opencode", "all"),
        default="claude",
        help="Which host to register MCP with (default: claude).",
    )
    init_parser.add_argument(
        "--skip-register",
        action="store_true",
        help="Skip MCP host registration (only create data dirs and config).",
    )
    init_parser.add_argument(
        "--academic",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable academic tools in the MCP server config.",
    )
    init_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format.",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Show a lightweight environment and configuration report.",
    )
    doctor_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format for the report.",
    )

    config_parser = subparsers.add_parser(
        "config",
        help="Inspect or initialize Scholar Agent configuration.",
    )
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)

    config_show_parser = config_subparsers.add_parser(
        "show",
        help="Show the resolved Scholar Agent configuration.",
    )
    config_show_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format for the resolved config.",
    )

    config_init_parser = config_subparsers.add_parser(
        "init",
        help="Create the user-level Scholar Agent home and default config file.",
    )
    config_init_parser.add_argument(
        "--force",
        action="store_true",
        help="Rewrite the default user config file if it already exists.",
    )
    config_init_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format for the initialization result.",
    )

    config_migrate_parser = config_subparsers.add_parser(
        "migrate",
        help="Migrate the current resolved config into the user-level config file.",
    )
    config_migrate_parser.add_argument(
        "--to",
        choices=("user-home",),
        default="user-home",
        help="Migration target.",
    )
    config_migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the migration result without writing the user config file.",
    )
    config_migrate_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the user config file if it already exists.",
    )
    config_migrate_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format for the migration result.",
    )

    install_parser = subparsers.add_parser(
        "install",
        help="Generate host-specific MCP configuration fragments.",
    )
    install_parser.add_argument(
        "host",
        choices=("claude", "vscode", "opencode"),
        help="The host for which to generate a configuration fragment.",
    )
    install_mode_group = install_parser.add_mutually_exclusive_group()
    install_parser.add_argument(
        "--profile",
        default="default",
        help="Scholar profile to encode into the generated fragment.",
    )
    install_parser.add_argument(
        "--toolset",
        default="default",
        help="Toolset profile to encode into the generated fragment.",
    )
    install_parser.add_argument(
        "--academic",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable academic tools in the generated fragment.",
    )
    install_mode_group.add_argument(
        "--write",
        action="store_true",
        help="Write or install the generated configuration into the target host.",
    )
    install_mode_group.add_argument(
        "--status",
        action="store_true",
        help="Show the currently installed configuration state for the target host.",
    )
    install_mode_group.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove scholar-agent from the target host configuration.",
    )
    install_parser.add_argument(
        "--path",
        default="",
        help="Override the target config path for file-backed hosts.",
    )
    install_parser.add_argument(
        "--scope",
        choices=("user", "project", "local"),
        default="user",
        help="Claude MCP scope to use when --write is enabled for Claude.",
    )
    install_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format for the fragment.",
    )

    runtime_parser = subparsers.add_parser(
        "runtime",
        help="Inspect or convert the current Scholar Agent installation mode.",
    )
    runtime_subparsers = runtime_parser.add_subparsers(dest="runtime_command", required=True)

    runtime_status_parser = runtime_subparsers.add_parser(
        "status",
        help="Show whether Scholar Agent is installed as editable or standalone.",
    )
    runtime_status_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format for the runtime status.",
    )

    runtime_build_wheel_parser = runtime_subparsers.add_parser(
        "build-wheel",
        help="Build a wheel artifact for Scholar Agent.",
    )
    runtime_build_wheel_parser.add_argument(
        "--source",
        default="",
        help="Source directory to build from. Defaults to the editable source path when available.",
    )
    runtime_build_wheel_parser.add_argument(
        "--output-dir",
        default="",
        help="Directory where the built wheel should be written. Defaults to <source>/dist.",
    )
    runtime_build_wheel_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format for the build result.",
    )

    runtime_install_parser = runtime_subparsers.add_parser(
        "install-standalone",
        help="Reinstall as a standalone package (development tool; not needed for normal usage).",
    )
    runtime_install_parser.add_argument(
        "--source",
        default="",
        help="Source directory to install from. Defaults to the editable source path when available.",
    )
    runtime_install_parser.add_argument(
        "--with-deps",
        action="store_true",
        help="Allow pip to resolve and reinstall dependencies during the standalone install.",
    )
    runtime_install_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format for the installation result.",
    )

    runtime_install_pipx_parser = runtime_subparsers.add_parser(
        "install-pipx",
        help="Install Scholar Agent into a dedicated pipx environment for global usage.",
    )
    runtime_install_pipx_source_group = runtime_install_pipx_parser.add_mutually_exclusive_group()
    runtime_install_pipx_source_group.add_argument(
        "--source",
        default="",
        help="Source directory to build from. Defaults to the editable source path when available.",
    )
    runtime_install_pipx_source_group.add_argument(
        "--wheel",
        default="",
        help="Prebuilt wheel to install instead of building one from source.",
    )
    runtime_install_pipx_parser.add_argument(
        "--force",
        action="store_true",
        help="Force pipx to reinstall the application if it is already present.",
    )
    runtime_install_pipx_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format for the pipx installation result.",
    )

    import_parser = subparsers.add_parser(
        "import-paper",
        help="Import a distilled paper note from PaperPulse SaaS into local knowledge.",
    )
    import_parser.add_argument(
        "paper_id",
        help="The UUID of the paper to import.",
    )
    import_parser.add_argument(
        "--token",
        help="PaperPulse API token (overrides paperpulse_token in config.json).",
    )
    import_parser.add_argument(
        "--url",
        help="PaperPulse base URL (overrides paperpulse_url in config.json).",
    )

    backfill_parser = subparsers.add_parser(
        "backfill",
        help="Backfill historical papers from arXiv into the local paper store.",
    )
    backfill_parser.add_argument(
        "--years",
        type=int,
        default=3,
        help="Number of years to backfill (default: 3).",
    )
    backfill_parser.add_argument(
        "--categories",
        default="cs.AI,cs.LG,cs.CL,cs.CV",
        help="Comma-separated arXiv categories (default: cs.AI,cs.LG,cs.CL,cs.CV).",
    )
    backfill_parser.add_argument(
        "--max-per-month",
        type=int,
        default=2000,
        help="Maximum papers per category per month (default: 2000).",
    )
    backfill_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format.",
    )

    daily_process_parser = subparsers.add_parser(
        "daily-process",
        help="Run the daily paper recommendation pipeline and store results.",
    )
    daily_process_parser.add_argument(
        "--date",
        default="",
        help="Target date in YYYY-MM-DD format (default: today).",
    )
    daily_process_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without writing notes.",
    )
    daily_process_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format.",
    )

    synonyms_parser = subparsers.add_parser(
        "synonyms",
        help="Manage the synonym dictionary used by query expansion during retrieval.",
    )
    synonyms_subparsers = synonyms_parser.add_subparsers(dest="synonyms_command", required=True)

    synonyms_subparsers.add_parser("list", help="List all synonym groups (project + user).")

    synonyms_search_parser = synonyms_subparsers.add_parser("search", help="Find groups containing a term.")
    synonyms_search_parser.add_argument("term", help="Term to search for.")

    synonyms_add_parser = synonyms_subparsers.add_parser(
        "add", help="Add a synonym group to the user-level dictionary at ~/.scholar/synonyms.json."
    )
    synonyms_add_parser.add_argument("canonical", help="The canonical phrase.")
    synonyms_add_parser.add_argument("aliases", nargs="+", help="One or more alias phrases.")

    synonyms_remove_parser = synonyms_subparsers.add_parser(
        "remove", help="Remove a synonym group from the user-level dictionary."
    )
    synonyms_remove_parser.add_argument("canonical", help="Canonical phrase to remove.")

    status_parser = subparsers.add_parser(
        "status",
        help="Print in-process metrics (LLM token usage, retrieve call counts, "
        "rerank fallback events). For long-running processes (MCP server); "
        "one-shot CLI invocations will show only this run's activity.",
    )
    status_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format.",
    )

    index_parser = subparsers.add_parser(
        "index",
        help="Build or rebuild the local search index. Pass --build-embedding-index "
        "to enable hybrid (BM25 + semantic) retrieval.",
    )
    index_parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Discard the existing index and rebuild from scratch (default: incremental).",
    )
    index_parser.add_argument(
        "--build-embedding-index",
        action="store_true",
        help="Also build the embedding index. Once present, query_knowledge "
        "automatically uses hybrid retrieval and keeps the embedding index fresh.",
    )
    index_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format.",
    )

    scan_stale_parser = subparsers.add_parser(
        "scan-stale",
        help="Scan the knowledge directory for cards whose source_date exceeds "
        "the domain-specific freshness threshold (F4/G3). Reports stale cards; "
        "pass --write to mark them with `stale: true` in frontmatter.",
    )
    scan_stale_parser.add_argument(
        "--knowledge-dir",
        default="",
        help="Directory to scan (defaults to the configured knowledge directory).",
    )
    scan_stale_parser.add_argument(
        "--write",
        action="store_true",
        help="Add `stale: true` to the frontmatter of each stale card (default: report only).",
    )
    scan_stale_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Incrementally refresh stale cards: re-fetch each source_refs URL, "
        "store a snapshot under knowledge/_snapshots/ (guards against link rot), "
        "and update the card's `captured_at` freshness marker. Best-effort per URL. "
        "Does NOT rewrite the answer body. Combinable with --write.",
    )
    scan_stale_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format.",
    )

    dangling_parser = subparsers.add_parser(
        "report-dangling",
        help="Scan note directories for dangling [[wikilinks]] (target notes that "
        "do not exist) and print a grouped report.",
    )
    dangling_parser.add_argument(
        "--notes-dir",
        action="append",
        default=[],
        help="Directory of notes to scan (may be passed multiple times). "
        "Defaults to the configured paper-notes directory if omitted.",
    )
    dangling_parser.add_argument(
        "--knowledge-dir",
        default="",
        help="Optional additional directory (e.g. knowledge cards) also scanned "
        "for both existence and wikilinks. Defaults to the configured knowledge directory.",
    )
    dangling_parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format.",
    )

    return parser


def _doctor_payload() -> dict[str, Any]:
    config_file = scholar_config.get_config_file_path()
    knowledge_dir = Path(scholar_config.get_knowledge_dir())
    index_path = Path(scholar_config.get_index_path())
    user_home = get_user_home()

    checks: list[dict[str, object]] = []

    # Directories
    for label, p in [("knowledge_dir", knowledge_dir), ("index_dir", index_path.parent)]:
        exists = p.exists()
        writable = os.access(p if exists else p.parent, os.W_OK) if exists else False
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
        card_count = sum(1 for _ in knowledge_dir.rglob("*.md"))

    # MCP registration (Claude) — try CLI first, then direct-read fallback
    claude_registered = False
    try:
        result = claude_installer.get_install_status()
        claude_registered = bool(result.get("installed", False))
    except Exception:
        pass

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
    lines.append(f"data directory:  {payload['user_home']}")
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


def _run_doctor(output_format: str) -> int:
    payload = _doctor_payload()
    _print_payload(payload, output_format, text_formatter=_format_doctor_text)
    checks = payload.get("checks", [])
    has_problem = any(
        not isinstance(c, dict) or (not c.get("exists", True) and c.get("check") != "index") for c in checks
    )
    deps = payload.get("dependencies", {})
    if isinstance(deps, dict) and not all(deps.values()):
        has_problem = True
    return 1 if has_problem else 0


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


def _run_config_show(output_format: str) -> int:
    payload = _config_show_payload()
    _print_payload(payload, output_format, text_formatter=_format_config_show_text)
    return 0


def _run_config_init(force: bool, output_format: str) -> int:
    payload = initialize_user_home(force=force)
    _print_payload(payload, output_format)
    return 0


def _run_config_migrate(target: str, dry_run: bool, force: bool, output_format: str) -> int:
    if target != "user-home":
        raise ValueError(f"unsupported migration target: {target}")
    payload = migrate_to_user_home(dry_run=dry_run, force=force)
    _print_payload(payload, output_format)
    return 0


def _build_install_payload(host: str, profile: str, toolset: str, academic: bool) -> dict[str, object]:
    if host == "claude":
        return claude_installer.build_user_config_fragment(profile=profile, toolset=toolset, academic=academic)
    if host == "vscode":
        return vscode_installer.build_user_config_fragment(profile=profile, toolset=toolset, academic=academic)
    if host == "opencode":
        return opencode_installer.build_user_config_fragment(profile=profile, toolset=toolset, academic=academic)
    raise ValueError(f"unsupported install host: {host}")


def _write_install_payload(
    host: str,
    profile: str,
    toolset: str,
    academic: bool,
    path: str,
    scope: str,
) -> dict[str, object]:
    if host == "claude":
        return claude_installer.install_user_config(
            profile=profile,
            toolset=toolset,
            academic=academic,
            scope=scope,
        )
    if host == "vscode":
        return vscode_installer.write_user_config(
            profile=profile,
            toolset=toolset,
            academic=academic,
            path=Path(path) if path else None,
        )
    if host == "opencode":
        return opencode_installer.write_user_config(
            profile=profile,
            toolset=toolset,
            academic=academic,
            path=Path(path) if path else None,
        )
    raise ValueError(f"unsupported install host: {host}")


def _status_install_payload(host: str, path: str, scope: str) -> dict[str, object]:
    if host == "claude":
        return claude_installer.get_install_status(scope=scope, cwd=Path.cwd())
    if host == "vscode":
        return vscode_installer.get_user_config_status(path=Path(path) if path else None)
    if host == "opencode":
        return opencode_installer.get_user_config_status(path=Path(path) if path else None)
    raise ValueError(f"unsupported install host: {host}")


def _uninstall_install_payload(host: str, path: str, scope: str) -> dict[str, object]:
    if host == "claude":
        return claude_installer.uninstall_user_config(scope=scope, cwd=Path.cwd())
    if host == "vscode":
        return vscode_installer.uninstall_user_config(path=Path(path) if path else None)
    if host == "opencode":
        return opencode_installer.uninstall_user_config(path=Path(path) if path else None)
    raise ValueError(f"unsupported install host: {host}")


def _run_install(
    host: str,
    profile: str,
    toolset: str,
    academic: bool,
    output_format: str,
    write: bool,
    status: bool,
    uninstall: bool,
    path: str,
    scope: str,
) -> int:
    if status:
        payload = _status_install_payload(host=host, path=path, scope=scope)
    elif uninstall:
        payload = _uninstall_install_payload(host=host, path=path, scope=scope)
    elif write:
        payload = _write_install_payload(
            host=host,
            profile=profile,
            toolset=toolset,
            academic=academic,
            path=path,
            scope=scope,
        )
    else:
        payload = _build_install_payload(host=host, profile=profile, toolset=toolset, academic=academic)
    _print_payload(payload, output_format)
    return 0


def _run_runtime_status(output_format: str) -> int:
    payload = runtime_manager.get_installation_state()
    _print_payload(payload, output_format)
    return 0


def _run_runtime_build_wheel(source: str, output_dir: str, output_format: str) -> int:
    payload = runtime_manager.build_wheel(source_path=source or None, output_dir=output_dir or None)
    _print_payload(payload, output_format)
    return 0


def _run_runtime_install_standalone(source: str, with_deps: bool, output_format: str) -> int:
    payload = runtime_manager.install_standalone(source_path=source or None, with_deps=with_deps)
    _print_payload(payload, output_format)
    return 0


def _run_runtime_install_pipx(source: str, wheel: str, force: bool, output_format: str) -> int:
    payload = runtime_manager.install_with_pipx(
        source_path=source or None,
        wheel_path=wheel or None,
        force=force,
    )
    _print_payload(payload, output_format)
    return 0


def _run_init(
    *,
    force: bool,
    host: str,
    skip_register: bool,
    academic: bool,
    output_format: str,
) -> int:
    # Step 1: Create data directories and write config
    init_result = initialize_user_home(force=force)
    user_home = Path(str(init_result["user_home"]))

    if output_format == "text" and not init_result.get("config_written", False):
        print(f"(Config already exists at {init_result['user_config_path']}. Use --force to overwrite.)")

    # Detect old data directory and suggest migration
    if output_format == "text":
        old_home = Path.home() / "scholar-agent"
        if (
            old_home.exists()
            and old_home != user_home
            and not (old_home / ".git").exists()
            and not (old_home / "pyproject.toml").exists()
        ):
            print()
            print(f"Note: Found old data directory at {old_home}/")
            print(f"  New data directory is {user_home}/")
            print(f"  To migrate: mv {old_home}/* {user_home}/")
            print()

    # Step 2: Build initial BM25 index (non-fatal)
    index_built = False
    try:
        from scholar_agent.engine.local_index import write_index
        from scholar_agent.engine.scholar_config import load_config

        knowledge_dir = Path(load_config()["knowledge_dir"])
        index_path = Path(load_config()["index_path"])
        write_index(knowledge_dir, index_path)
        index_built = True
    except Exception as exc:
        print(f"  Warning: index build skipped ({exc})")

    # Step 3: Register MCP with host(s)
    register_results: list[dict[str, object]] = []
    if not skip_register:
        # Detect project-local mode: SCHOLAR_HOME is set and differs from default
        scholar_home_env = os.environ.get("SCHOLAR_HOME", "").strip()
        default_home = str(get_user_home(env={}))
        is_project_local = bool(scholar_home_env) and Path(scholar_home_env).resolve() != Path(default_home).resolve()
        scope = "project" if is_project_local else "user"

        hosts = ["claude", "vscode", "opencode"] if host == "all" else [host]
        for h in hosts:
            try:
                if h == "claude":
                    result = claude_installer.install_user_config(
                        academic=academic,
                        scope=scope,
                        scholar_home=scholar_home_env or None,
                    )
                elif h == "vscode":
                    result = vscode_installer.write_user_config(
                        academic=academic, scholar_home=scholar_home_env or None
                    )
                elif h == "opencode":
                    result = opencode_installer.write_user_config(
                        academic=academic, scholar_home=scholar_home_env or None
                    )
                else:
                    continue
                register_results.append(result)
            except RuntimeError as exc:
                register_results.append({"status": "error", "host": h, "message": str(exc)})
            except Exception as exc:
                register_results.append({"status": "error", "host": h, "message": f"Unexpected error: {exc}"})

    if output_format == "json":
        payload: dict[str, object] = {
            **init_result,
            "index_built": index_built,
            "registration": register_results,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print()
        print("=== Scholar Agent Setup Complete ===")
        print()
        print(f"Data directory: {user_home}")
        print("  config/        - Configuration files")
        print("  knowledge/     - Knowledge cards")
        print("  paper-notes/   - Paper analysis notes")
        print("  daily-notes/   - Daily paper recommendations")
        print("  indexes/       - BM25 search index")
        if index_built:
            print("  (Search index initialized)")
        else:
            print("  (Index will be built on first query)")
        print()
        if register_results:
            has_error = False
            for r in register_results:
                if r.get("status") == "ok":
                    print(f"MCP registered: {r.get('host', 'unknown')} ({r.get('scope', 'user')} scope)")
                elif r.get("status") == "error":
                    has_error = True
                    host_name = r.get("host", "unknown")
                    msg = r.get("message", "unknown error")
                    print(f"MCP registration ({host_name}): {msg}")
            if has_error:
                print()
                print("Hint: You can register manually later:")
                print("  scholar-agent install claude --write   # Claude Code")
                print("  scholar-agent install vscode --write   # VS Code Copilot")
        elif skip_register:
            print("(MCP registration skipped. Run 'scholar-agent install claude --write' to register later.)")
        print()
        print("Quick start:")
        print("  1. Restart Claude Code (or VS Code)")
        print('  2. Ask Claude to search papers: "search for papers about LLM reasoning"')
        print("  3. Save research: use the save_research or capture_answer tools")
        print()
        print("Next steps:")
        print(f"  Edit {user_home / 'config' / 'config.json'} to add your research interests")
        print("  scholar-agent doctor          - Check your setup")
        print("  scholar-agent config show     - Show resolved config")
        print()

    return 0


def _run_serve_mcp() -> int:
    from scholar_agent import __version__

    sys.stderr.write(f"\nScholar Agent v{__version__} — MCP Server\n\n")
    sys.stderr.flush()
    return mcp_adapter.main()


def _run_serve_http() -> int:
    from scholar_agent import __version__
    from scholar_agent.server import start_local_server

    sys.stderr.write(f"\nScholar Agent v{__version__} — HTTP Sync Server\n\n")
    sys.stderr.flush()
    return start_local_server()


def _run_import_paper(paper_id: str, token: str | None, url: str | None) -> int:
    from pathlib import Path

    from scholar_agent.engine.import_service import import_from_url
    from scholar_agent.engine.scholar_config import get_knowledge_dir, load_config

    config = load_config()
    effective_token = token or config.get("paperpulse_token", "")
    base_url = url or config.get("paperpulse_url", "https://mindpulse.top").rstrip("/")

    msg, filename = import_from_url(paper_id, effective_token, base_url)
    if filename is None:
        sys.stderr.write(f"{msg}\n")
        return 1

    # Reindex synchronously for short-lived CLI command
    try:
        from scholar_agent.engine.close_knowledge_loop import reindex

        knowledge_dir = Path(get_knowledge_dir())
        index_path = Path(config["index_path"])
        reindex(knowledge_dir, index_path)
    except Exception:
        sys.stderr.write("Warning: Reindexing failed\n")

    sys.stdout.write(f"{msg}\n")
    return 0


def _run_backfill(years: int, categories: str, max_per_month: int, output_format: str) -> int:
    from datetime import datetime, timedelta

    def _month_range(year: int, month: int) -> tuple[datetime, datetime]:
        """Return (start, end) datetime for a calendar month."""
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
        else:
            end = datetime(year, month + 1, 1) - timedelta(seconds=1)
        return start, end

    from scholar_agent.engine.academic.arxiv_search import query_arxiv_paginated
    from scholar_agent.engine.paper_store import PaperStore
    from scholar_agent.engine.scholar_config import get_paper_db_path

    cats = [c.strip() for c in categories.split(",") if c.strip()]

    db_path = get_paper_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with PaperStore(db_path) as store:
        store.initialize()

        now = datetime.now()
        total_upserted = 0
        total_months = years * 12

        for month_offset in range(total_months):
            # Iterate from oldest to newest
            steps_back = total_months - 1 - month_offset
            abs_month = now.year * 12 + (now.month - 1) - steps_back
            year = abs_month // 12
            month = abs_month % 12 + 1

            from_dt, to_dt = _month_range(year, month)

            if output_format == "text":
                sys.stdout.write(f"  {year}-{month:02d}: fetching... ")
                sys.stdout.flush()

            papers = query_arxiv_paginated(
                categories=cats,
                from_dt=from_dt,
                to_dt=to_dt,
                max_total=max_per_month,
            )

            for p in papers:
                p["is_historical"] = True
            count = store.upsert_papers(papers)
            total_upserted += count

            if output_format == "text":
                sys.stdout.write(f"{len(papers)} fetched, {count} upserted\n")
            else:
                sys.stdout.write(
                    json.dumps(
                        {
                            "month": f"{year}-{month:02d}",
                            "fetched": len(papers),
                            "upserted": count,
                        }
                    )
                    + "\n"
                )
            sys.stdout.flush()

        counts = store.count_by_status()

    payload = {
        "status": "ok",
        "years": years,
        "categories": cats,
        "total_upserted": total_upserted,
        "status_counts": counts,
    }
    _print_payload(payload, output_format)
    return 0


def _run_daily_process(date_str: str, dry_run: bool, output_format: str) -> int:
    from datetime import datetime

    from scholar_agent.engine.academic.daily_workflow import (
        build_daily_note,
        generate_daily_recommendations,
        generate_paper_notes_for_daily,
    )
    from scholar_agent.engine.scholar_config import (
        get_daily_notes_dir,
        get_paper_notes_dir,
        get_research_interests,
        load_config,
    )

    target_date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.now()
    date_str_out = target_date.strftime("%Y-%m-%d")

    config = load_config()
    interests = get_research_interests()
    search_config = {
        "research_domains": interests.get("research_domains", {}),
        "excluded_keywords": interests.get("excluded_keywords", []),
    }
    precision_config = config.get("academic", {}).get("precision_funnel", {})
    daily_config = dict(config.get("academic", {}).get("daily_recommend", {}))
    if "unified_pipeline" not in daily_config:
        uc = config.get("academic", {}).get("unified_pipeline", {})
        if uc:
            daily_config["unified_pipeline"] = uc

    paper_notes_dir = str(get_paper_notes_dir())

    result = generate_daily_recommendations(
        config=search_config,
        paper_notes_dir=paper_notes_dir,
        target_date=target_date,
        precision_config=precision_config,
        daily_config=daily_config,
    )

    papers = result.get("papers", [])
    funnel_stats = result.get("funnel_stats")
    pipeline_stats = result.get("stats") if result.get("unified_pipeline") else None

    if dry_run:
        payload = {
            "status": "dry_run",
            "date": date_str_out,
            "papers_found": len(papers),
            "papers": [{"title": p.get("title", ""), "arxiv_id": p.get("arxiv_id", "")} for p in papers],
            "funnel_stats": funnel_stats,
            "pipeline_stats": pipeline_stats,
        }
        _print_payload(payload, output_format)
        return 0

    # Generate per-paper notes
    paper_note_stems = generate_paper_notes_for_daily(papers, paper_notes_dir)

    # Build daily note
    output_dir = str(get_daily_notes_dir())
    note_path = build_daily_note(
        date_str_out,
        papers,
        output_dir,
        tracks=result.get("tracks"),
        paper_note_stems=paper_note_stems or None,
        funnel_stats=funnel_stats,
        pipeline_stats=pipeline_stats,
        language="en",
    )

    payload = {
        "status": "ok",
        "date": date_str_out,
        "daily_note_path": note_path,
        "recommended": len(papers),
        "total_found": result.get("total_found", 0),
        "funnel_stats": funnel_stats,
        "pipeline_stats": pipeline_stats,
    }
    _print_payload(payload, output_format)
    return 0


def _run_synonyms(sub: str, canonical: str, aliases: list[str], term: str) -> int:
    """Dispatch for the `scholar-agent synonyms` subcommand family."""
    from scholar_agent.engine import synonyms as syn

    if sub == "list":
        merged = syn.load_synonyms()
        if not merged:
            print("No synonym groups configured.")
            return 0
        print(f"{len(merged)} synonym group(s):")
        for canon, alias_list in sorted(merged.items()):
            print(f"  • {canon}")
            if alias_list:
                print(f"      aliases: {', '.join(alias_list)}")
        return 0

    if sub == "search":
        merged = syn.load_synonyms()
        needle = term.strip().lower()
        hits = [
            (canon, aliases)
            for canon, aliases in merged.items()
            if needle == canon or needle in aliases or any(needle in a for a in aliases)
        ]
        if not hits:
            print(f"No synonym group matches '{term}'.")
            return 1
        for canon, alias_list in hits:
            print(f"  • {canon}")
            if alias_list:
                print(f"      aliases: {', '.join(alias_list)}")
        return 0

    if sub == "add":
        if not canonical or not aliases:
            print("Usage: synonyms add <canonical> <alias1> [alias2 ...]")
            return 2
        path = syn.add_user_group(canonical, aliases)
        print(f"Added '{canonical}' with {len(aliases)} alias(es) → {path}")
        return 0

    if sub == "remove":
        if not canonical:
            print("Usage: synonyms remove <canonical>")
            return 2
        if syn.remove_user_group(canonical):
            print(f"Removed '{canonical}' from user-level synonyms.")
            return 0
        print(f"'{canonical}' not found in user-level synonyms.")
        return 1

    print(f"Unknown synonyms subcommand: {sub}")
    return 2


def _run_status(output_format: str) -> int:
    """Print metrics — prefers the persisted snapshot so a separate `status`
    invocation can observe a running MCP server, falling back to this
    process's own in-memory counters."""
    from scholar_agent.engine import metrics

    snapshot = metrics.load_persisted() or metrics.get_metrics()

    if output_format == "json":
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0

    llm = snapshot["llm"]
    retrieve = snapshot["retrieve"]
    print("Scholar Agent in-process metrics")
    print("================================")
    print()
    print("LLM:")
    print(f"  calls            : {llm['calls']}")
    print(f"  failures         : {llm['failures']}")
    print(f"  prompt_tokens    : {llm['prompt_tokens']:,}")
    print(f"  completion_tokens: {llm['completion_tokens']:,}")
    print(f"  total_tokens     : {llm['total_tokens']:,}")
    print()
    print("Retrieve:")
    print(f"  calls            : {retrieve['calls']}")
    print(f"  expansions_used  : {retrieve['expansions_used']}")
    print(f"  rerank_calls     : {retrieve['rerank_calls']}")
    print(f"  rerank_fallbacks : {retrieve['rerank_fallbacks']}")
    return 0


def _run_index(full_rebuild: bool, build_embedding_index: bool, output_format: str) -> int:
    """Build or rebuild the local index (BM25, optionally embedding)."""
    from scholar_agent.engine.local_index import write_index

    knowledge_dir = scholar_config.get_knowledge_dir()
    index_path = scholar_config.get_index_path()
    embedding_path = index_path.parent / "embeddings.json"

    try:
        payload = write_index(
            knowledge_dir,
            index_path,
            full_rebuild=full_rebuild,
            build_embedding_index=build_embedding_index,
            embedding_output=embedding_path,
        )
    except Exception as exc:
        sys.stderr.write(f"Index build failed: {exc}\n")
        return 1

    docs = payload.get("documents", []) if isinstance(payload, dict) else []
    result: dict[str, object] = {
        "knowledge_dir": str(knowledge_dir),
        "index_path": str(index_path),
        "documents": len(docs) if isinstance(docs, list) else 0,
        "full_rebuild": full_rebuild,
        "embedding_index": str(embedding_path) if build_embedding_index else None,
        "embedding_index_built": embedding_path.exists() if build_embedding_index else None,
    }

    if output_format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"Indexed {result['documents']} document(s) → {index_path}")
    if build_embedding_index:
        if embedding_path.exists():
            print(f"Embedding index built → {embedding_path}")
            print("query_knowledge will now use hybrid (BM25 + semantic) retrieval.")
        else:
            print("Embedding index build was skipped (see logs); staying BM25-only.")
    elif embedding_path.exists():
        print("Note: an embedding index exists but was not refreshed. Pass --build-embedding-index to update it.")
    return 0


def _scan_stale_cards(
    knowledge_root: Path,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """F4/G3: scan a knowledge directory for stale cards.

    Reuses :func:`knowledge_lifecycle._freshness_years_for` for the per-domain
    threshold and the same logic as ``validate_card_quality`` (derive the year
    from ``source_date``, falling back to ``updated_at``; flag when
    ``now_year - source_year > threshold``).

    Returns a list of dicts ``{"path", "domain", "source_year", "threshold_years",
    "days_stale"}`` for every stale card. Advisory; never raises for a single
    unreadable card (it is skipped).
    """
    from scholar_agent.engine.common import parse_frontmatter
    from scholar_agent.engine.knowledge_lifecycle import _freshness_years_for

    current = now or datetime.now()
    current_year = current.year

    stale: list[dict[str, Any]] = []
    for path in sorted(knowledge_root.rglob("*.md")):
        if "templates" in path.parts or path.name.lower() == "readme.md":
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not raw.startswith("---\n"):
            continue
        meta, _body = parse_frontmatter(raw)

        # Resolve the source year: prefer source_date, fall back to updated_at.
        source_date = meta.get("source_date") or meta.get("updated_at")
        if not source_date:
            continue
        m = re.search(r"\d{4}", str(source_date))
        if not m:
            continue
        source_year = int(m.group())

        domain = meta.get("domain")
        threshold = _freshness_years_for(domain)

        # years elapsed (float, fractional), compare against threshold exactly
        # as validate_card_quality does (integer year difference > threshold).
        years_elapsed = current_year - source_year
        if years_elapsed > threshold:
            # days past the freshness horizon, for the report.
            # 365.25 to stay close to calendar years.
            days_stale = round((years_elapsed - threshold) * 365.25)
            stale.append(
                {
                    "path": str(path),
                    "domain": domain or "",
                    "source_year": source_year,
                    "threshold_years": threshold,
                    "days_stale": days_stale,
                }
            )
    return stale


def _mark_card_stale(card_path: Path) -> bool:
    """Add `stale: true` to a card's frontmatter in place.

    Inserts the key right after the opening ``---`` line if absent. Returns
    True if the file was written, False if it already had the flag.
    """
    raw = card_path.read_text(encoding="utf-8")
    lines = raw.split("\n")
    if not lines or lines[0].strip() != "---":
        return False
    # Walk to the closing frontmatter delimiter.
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return False
    # Already present?
    for line in lines[1:end_idx]:
        if line.strip().startswith("stale:"):
            return False
    lines.insert(1, "stale: true")
    card_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def _extract_card_urls(card_path: Path) -> list[str]:
    """Return the http(s) URLs from a card's frontmatter ``source_refs``.

    ``source_refs`` is a YAML list of URLs. Falls back to an inline ``sources``
    list if present. Non-http entries and duplicates are skipped.
    """
    from scholar_agent.engine.common import parse_frontmatter

    try:
        raw = card_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not raw.startswith("---\n"):
        return []
    meta, _body = parse_frontmatter(raw)

    urls: list[str] = []
    seen: set[str] = set()
    for key in ("source_refs", "sources"):
        val = meta.get(key)
        if isinstance(val, list):
            candidates = val
        elif isinstance(val, str) and val:
            candidates = [val]
        else:
            candidates = []
        for entry in candidates:
            url = str(entry).strip().strip("'\"")
            if url.startswith(("http://", "https://")) and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def _refresh_card_sources(
    card_path: Path,
    knowledge_root: Path,
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    """G3: best-effort refresh of one card's source URLs.

    Re-fetches each ``source_refs`` URL via ``fetch_content``, stores a snapshot
    under ``knowledge_root/_snapshots/<sha1(url)[:16]>.md`` on success, and
    stamps the card's ``captured_at`` with today's date.

    Returns ``(refreshed, total)`` — the count of URLs whose snapshot was
    written and the total number of source URLs considered. Does NOT modify the
    answer body. Per-URL failures are logged as warnings and never raise.
    """
    from scholar_agent.engine.research_harness import fetch_content

    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")

    urls = _extract_card_urls(card_path)
    if not urls:
        return (0, 0)

    snapshots_dir = knowledge_root / "_snapshots"

    refreshed = 0
    any_success = False
    for url in urls:
        try:
            result = fetch_content(url)
        except Exception as exc:  # best-effort: never abort the whole sweep
            sys.stderr.write(f"[scan-stale --refresh] {url} raised {exc}\n")
            continue

        status = result.get("retrieval_status", "")
        content_md = result.get("content_md", "") or ""
        if status in ("succeeded", "cached") and content_md.strip():
            snapshots_dir.mkdir(parents=True, exist_ok=True)
            slug = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
            snap_path = snapshots_dir / f"{slug}.md"
            title = result.get("title", "") or url
            snap_lines = [
                "---",
                f"url: {url}",
                f"captured_at: {today}",
                f"title: {title}",
                f"retrieval_status: {status}",
                "---",
                "",
                content_md.strip(),
                "",
            ]
            snap_path.write_text("\n".join(snap_lines), encoding="utf-8")
            refreshed += 1
            any_success = True
        else:
            reason = result.get("failure_reason", "")
            sys.stderr.write(
                f"[scan-stale --refresh] {url} not snapshotted "
                f"(status={status}{f': {reason}' if reason else ''})\n"
            )

    if any_success:
        _stamp_captured_at(card_path, today)
    return (refreshed, len(urls))


def _stamp_captured_at(card_path: Path, today: str) -> bool:
    """Set/replace ``captured_at`` in a card's frontmatter.

    Returns True if the file was written.
    """
    raw = card_path.read_text(encoding="utf-8")
    lines = raw.split("\n")
    if not lines or lines[0].strip() != "---":
        return False
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return False

    for i in range(1, end_idx):
        if lines[i].strip().startswith("captured_at:"):
            lines[i] = f"captured_at: {today}"
            card_path.write_text("\n".join(lines), encoding="utf-8")
            return True

    # Insert right after opening delimiter.
    lines.insert(1, f"captured_at: {today}")
    card_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def _run_scan_stale(
    knowledge_dir: str,
    write: bool,
    output_format: str,
    refresh: bool = False,
) -> int:
    from scholar_agent.engine import scholar_config as _scholar_config

    root = Path(knowledge_dir) if knowledge_dir else Path(_scholar_config.get_knowledge_dir())

    stale = _scan_stale_cards(root)

    if write:
        written = 0
        for item in stale:
            if _mark_card_stale(Path(item["path"])):
                written += 1
    else:
        written = None

    # G3: incrementally refresh stale cards' source snapshots + captured_at.
    refresh_report: list[dict[str, object]] | None = None
    if refresh:
        refresh_report = []
        for item in stale:
            card = Path(item["path"])
            refreshed, total = _refresh_card_sources(card, root)
            refresh_report.append(
                {
                    "path": str(card),
                    "refreshed": refreshed,
                    "total": total,
                }
            )

    if output_format == "json":
        payload: dict[str, object] = {
            "status": "ok",
            "knowledge_dir": str(root),
            "stale_count": len(stale),
            "marked": written,
            "stale": stale,
        }
        if refresh_report is not None:
            payload["refreshed"] = refresh_report
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not stale:
        print("no stale cards")
        return 0

    if refresh:
        # Under --refresh, lead with the per-card refresh report so link-rot
        # remediation is the focus; freshness detail stays below it.
        for r in refresh_report or []:
            total = r["total"]
            if total == 0:
                print(f"{r['path']}  no sources to refresh")
            else:
                print(f"{r['path']}  refreshed {r['refreshed']}/{total} sources")
        print()

    for item in stale:
        print(
            f"{item['path']}  domain={item['domain'] or '(none)'}  "
            f"source={item['source_year']}  超期{item['days_stale']}天 "
            f"(阈值{item['threshold_years']}年)"
        )
    print()
    suffix = f"  (marked {written} card(s) with stale: true)" if write else ""
    print(f"{len(stale)} stale card(s){suffix}")
    return 0


def _run_report_dangling(notes_dirs: list[str], knowledge_dir: str, output_format: str) -> int:
    """Scan note directories for dangling [[wikilinks]] and print a grouped report."""
    from scholar_agent.engine import scholar_config as _scholar_config
    from scholar_agent.engine.academic.note_linker import find_dangling_links

    # Fall back to configured defaults when nothing is passed.
    if not notes_dirs:
        notes_dirs = [str(_scholar_config.get_paper_notes_dir())]
    if not knowledge_dir:
        try:
            knowledge_dir = str(_scholar_config.get_knowledge_dir())
        except Exception:
            knowledge_dir = ""

    dangling = find_dangling_links(notes_dirs, knowledge_dir=knowledge_dir or None)

    if output_format == "json":
        payload = {
            "status": "ok",
            "notes_dirs": notes_dirs,
            "knowledge_dir": knowledge_dir or None,
            "dangling_count": len(dangling),
            "dangling": dangling,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not dangling:
        print("no dangling links")
        return 0

    # Group by file for readability.
    grouped: dict[str, list[dict]] = {}
    for item in dangling:
        grouped.setdefault(item["file"], []).append(item)

    print(f"Found {len(dangling)} dangling link(s) across {len(grouped)} file(s):")
    print()
    for file_path in sorted(grouped):
        items = grouped[file_path]
        print(f"{file_path}  ({len(items)})")
        for it in items:
            print(f"  {it['link']}  → target '{it['target']}' not found")
        print()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    command = args.command
    if command is None:
        sys.stderr.write(
            "Warning: 'scholar-agent' without arguments defaults to 'serve-mcp'. "
            "Specify 'scholar-agent serve-mcp' explicitly.\n"
        )
        command = "serve-mcp"

    if command == "serve-mcp":
        return _run_serve_mcp()
    if command == "serve-http":
        return _run_serve_http()
    if command == "init":
        return _run_init(
            force=args.force,
            host=args.host,
            skip_register=args.skip_register,
            academic=args.academic,
            output_format=args.format,
        )
    if command == "doctor":
        return _run_doctor(args.format)
    if command == "config":
        if args.config_command == "show":
            return _run_config_show(args.format)
        if args.config_command == "init":
            return _run_config_init(force=args.force, output_format=args.format)
        if args.config_command == "migrate":
            return _run_config_migrate(
                target=args.to,
                dry_run=args.dry_run,
                force=args.force,
                output_format=args.format,
            )
    if command == "synonyms":
        return _run_synonyms(
            sub=args.synonyms_command,
            canonical=getattr(args, "canonical", ""),
            aliases=getattr(args, "aliases", []),
            term=getattr(args, "term", ""),
        )
    if command == "status":
        return _run_status(output_format=args.format)
    if command == "index":
        return _run_index(
            full_rebuild=args.full_rebuild,
            build_embedding_index=args.build_embedding_index,
            output_format=args.format,
        )
    if command == "install":
        return _run_install(
            host=args.host,
            profile=args.profile,
            toolset=args.toolset,
            academic=args.academic,
            output_format=args.format,
            write=args.write,
            status=args.status,
            uninstall=args.uninstall,
            path=args.path,
            scope=args.scope,
        )
    if command == "runtime":
        if args.runtime_command == "status":
            return _run_runtime_status(args.format)
        if args.runtime_command == "build-wheel":
            return _run_runtime_build_wheel(source=args.source, output_dir=args.output_dir, output_format=args.format)
        if args.runtime_command == "install-standalone":
            return _run_runtime_install_standalone(
                source=args.source, with_deps=args.with_deps, output_format=args.format
            )
        if args.runtime_command == "install-pipx":
            return _run_runtime_install_pipx(
                source=args.source,
                wheel=args.wheel,
                force=args.force,
                output_format=args.format,
            )

    if command == "import-paper":
        return _run_import_paper(
            paper_id=args.paper_id,
            token=args.token,
            url=args.url,
        )

    if command == "backfill":
        return _run_backfill(
            years=args.years,
            categories=args.categories,
            max_per_month=args.max_per_month,
            output_format=args.format,
        )

    if command == "daily-process":
        return _run_daily_process(
            date_str=args.date,
            dry_run=args.dry_run,
            output_format=args.format,
        )

    if command == "report-dangling":
        return _run_report_dangling(
            notes_dirs=args.notes_dir,
            knowledge_dir=args.knowledge_dir,
            output_format=args.format,
        )

    if command == "scan-stale":
        return _run_scan_stale(
            knowledge_dir=args.knowledge_dir,
            write=args.write,
            output_format=args.format,
            refresh=args.refresh,
        )

    parser.error(f"unknown command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
