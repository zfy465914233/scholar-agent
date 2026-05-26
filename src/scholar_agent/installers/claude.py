"""Claude Code MCP config generation + skill file installation."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from scholar_agent.installers.common import build_stdio_server

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills" / "scholar-agent"


_SCOPE_LABELS = {
    "user": "User config",
    "project": "Project config",
    "local": "Local config",
}


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
    if shutil.which("claude") is None:
        raise RuntimeError("Claude CLI not found in PATH")

    server_payload = build_user_config_fragment(
        profile=profile,
        toolset=toolset,
        academic=academic,
        scholar_home=scholar_home,
    )["mcpServers"]["scholar-agent"]

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

    # Also install skill files
    skill_result = install_skill_files()

    return {
        "status": "ok",
        "host": "claude",
        "scope": scope,
        "server_name": "scholar-agent",
        "stdout": completed.stdout.strip(),
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
        return subprocess.run(command, check=check, capture_output=True, text=True, cwd=str(run_cwd))
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
    if shutil.which("claude") is None:
        raise RuntimeError("Claude CLI not found in PATH")

    completed = _run_claude_command(["claude", "mcp", "get", "scholar-agent"], scope=scope, cwd=cwd, check=False)
    parsed = _parse_get_output(completed.stdout)
    installed = completed.returncode == 0 and parsed.get("scope", "").startswith(_SCOPE_LABELS[scope])
    return {
        "status": "ok",
        "host": "claude",
        "scope": scope,
        "server_name": "scholar-agent",
        "installed": installed,
        "details": parsed,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def uninstall_user_config(*, scope: str = "user", cwd: str | Path | None = None) -> dict[str, object]:
    if shutil.which("claude") is None:
        raise RuntimeError("Claude CLI not found in PATH")

    completed = _run_claude_command(
        ["claude", "mcp", "remove", "scholar-agent", "-s", scope],
        scope=scope,
        cwd=cwd,
        check=False,
    )
    combined_output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    removed = completed.returncode == 0
    missing = "No MCP server found" in combined_output
    return {
        "status": "ok" if removed else "noop" if missing else "error",
        "host": "claude",
        "scope": scope,
        "server_name": "scholar-agent",
        "removed": removed,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }