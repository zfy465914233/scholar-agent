"""Claude Code MCP config generation + skill file installation."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from scholar_agent.installers.common import (
    build_stdio_server,
    get_named_server,
    load_json_file,
    merge_named_server,
    remove_named_server,
    write_json_file,
)

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills" / "scholar-agent"

_SCOPE_LABELS = {
    "user": "User config",
    "project": "Project config",
    "local": "Local config",
}


def _claude_config_path(scope: str, cwd: str | Path | None = None) -> Path:
    """Return the path to the Claude config file for the given scope."""
    if scope == "user":
        return Path.home() / ".claude.json"
    return Path(cwd) if cwd is not None else Path.cwd() / ".claude.json"


def build_user_config_fragment(*, profile: str = "default", toolset: str = "default", academic: bool = True, scholar_home: str | None = None) -> dict[str, object]:
    return {
        "mcpServers": {
            "scholar-agent": build_stdio_server(profile=profile, toolset=toolset, academic=academic, scholar_home=scholar_home),
        }
    }


def install_skill_files() -> dict[str, object]:
    """Copy bundled skill files into ~/.claude/skills/scholar-agent/."""
    target = Path.home() / ".claude" / "skills" / "scholar-agent"
    if not _SKILLS_DIR.exists():
        return {"status": "skipped", "reason": "bundled_skills_not_found"}

    # Copy everything except __pycache__
    copied: list[str] = []
    for src_file in _SKILLS_DIR.rglob("*"):
        if "__pycache__" in src_file.parts:
            continue
        rel = src_file.relative_to(_SKILLS_DIR)
        dst = target / rel
        if src_file.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_file), str(dst))
            copied.append(str(rel))

    return {"status": "ok", "host": "claude", "skill_files": copied, "target": str(target)}


def install_user_config(
    *,
    profile: str = "default",
    toolset: str = "default",
    academic: bool = True,
    scope: str = "user",
    cwd: str | Path | None = None,
    scholar_home: str | None = None,
) -> dict[str, object]:
    server_payload = build_user_config_fragment(
        profile=profile,
        toolset=toolset,
        academic=academic,
        scholar_home=scholar_home,
    )["mcpServers"]["scholar-agent"]

    # Try CLI first
    if shutil.which("claude") is not None:
        try:
            command = [
                "claude",
                "mcp",
                "add-json",
                "--scope",
                scope,
                "scholar-agent",
                json.dumps(server_payload, ensure_ascii=False),
            ]
            completed = _run_claude_command(command, scope=scope, cwd=cwd, check=True)
            skill_result = install_skill_files()
            return {
                "status": "ok",
                "host": "claude",
                "method": "cli",
                "scope": scope,
                "server_name": "scholar-agent",
                "stdout": completed.stdout.strip(),
                "skills": skill_result,
            }
        except Exception as exc:
            logger.info("claude mcp add-json failed (%s), falling back to direct write", exc)

    # Fallback: write .claude.json directly
    config_path = _claude_config_path(scope, cwd)
    existing = load_json_file(config_path)
    merged = merge_named_server(
        existing,
        section_key="mcpServers",
        server_name="scholar-agent",
        server_payload=server_payload,
    )
    write_json_file(config_path, merged)

    skill_result = install_skill_files()
    return {
        "status": "ok",
        "host": "claude",
        "method": "direct-write",
        "scope": scope,
        "server_name": "scholar-agent",
        "config_path": str(config_path),
        "skills": skill_result,
    }


def _command_cwd(scope: str, cwd: str | Path | None = None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if scope == "user":
        tempdir = tempfile.TemporaryDirectory()
        return Path(tempdir.name), tempdir
    return Path(cwd) if cwd is not None else Path.cwd(), None


def _run_claude_command(
    command: list[str],
    *,
    scope: str,
    cwd: str | Path | None = None,
    check: bool,
) -> subprocess.CompletedProcess[str]:
    run_cwd, tempdir = _command_cwd(scope, cwd)
    try:
        return subprocess.run(command, check=check, capture_output=True, text=True, encoding="utf-8", cwd=str(run_cwd))
    finally:
        if tempdir is not None:
            tempdir.cleanup()


def _parse_get_output(output: str) -> dict[str, str]:
    # This parses human-readable `claude mcp get` output, not a stable machine API.
    # If Claude CLI changes its display format, this parser will need updating.
    parsed: dict[str, str] = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("To remove this server") or stripped == 'scholar-agent:':
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        parsed[key.strip().lower().replace(" ", "_")] = value.strip()
    return parsed


def get_install_status(*, scope: str = "user", cwd: str | Path | None = None) -> dict[str, object]:
    # Try CLI first
    if shutil.which("claude") is not None:
        try:
            completed = _run_claude_command(["claude", "mcp", "get", "scholar-agent"], scope=scope, cwd=cwd, check=False)
            parsed = _parse_get_output(completed.stdout)
            installed = completed.returncode == 0 and parsed.get("scope", "").startswith(_SCOPE_LABELS[scope])
            return {
                "status": "ok",
                "host": "claude",
                "method": "cli",
                "scope": scope,
                "server_name": "scholar-agent",
                "installed": installed,
                "details": parsed,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
        except Exception:
            pass  # fallback

    # Fallback: read .claude.json directly
    config_path = _claude_config_path(scope, cwd)
    existing = load_json_file(config_path)
    entry = get_named_server(existing, section_key="mcpServers", server_name="scholar-agent")
    return {
        "status": "ok",
        "host": "claude",
        "method": "direct-read",
        "scope": scope,
        "server_name": "scholar-agent",
        "installed": entry is not None,
        "config_path": str(config_path),
    }


def uninstall_user_config(*, scope: str = "user", cwd: str | Path | None = None) -> dict[str, object]:
    # Try CLI first
    if shutil.which("claude") is not None:
        try:
            completed = _run_claude_command(
                ["claude", "mcp", "remove", "scholar-agent", "-s", scope],
                scope=scope,
                cwd=cwd,
                check=False,
            )
            combined_output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
            removed = completed.returncode == 0
            missing = "No MCP server found" in combined_output
            if removed or missing:
                return {
                    "status": "ok" if removed else "noop",
                    "host": "claude",
                    "method": "cli",
                    "scope": scope,
                    "server_name": "scholar-agent",
                    "removed": removed,
                    "stdout": completed.stdout.strip(),
                    "stderr": completed.stderr.strip(),
                }
        except Exception:
            pass  # fallback

    # Fallback: remove from .claude.json directly
    config_path = _claude_config_path(scope, cwd)
    existing = load_json_file(config_path)
    merged, did_remove = remove_named_server(
        existing,
        section_key="mcpServers",
        server_name="scholar-agent",
    )
    if did_remove:
        write_json_file(config_path, merged)
    return {
        "status": "ok" if did_remove else "noop",
        "host": "claude",
        "method": "direct-write",
        "scope": scope,
        "server_name": "scholar-agent",
        "removed": did_remove,
        "config_path": str(config_path),
    }
