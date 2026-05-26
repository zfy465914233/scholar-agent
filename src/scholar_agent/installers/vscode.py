"""VS Code Copilot MCP config generation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from scholar_agent.installers.common import (
    build_stdio_server,
    get_named_server,
    load_json_file,
    merge_named_server,
    remove_named_server,
    write_json_file,
)


def build_user_config_fragment(*, profile: str = "default", toolset: str = "default", academic: bool = True, scholar_home: str | None = None) -> dict[str, object]:
    return {
        "servers": {
            "scholar-agent": build_stdio_server(profile=profile, toolset=toolset, academic=academic, scholar_home=scholar_home),
        }
    }


def get_default_user_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Code" / "User" / "mcp.json"
    return Path.home() / ".config" / "Code" / "User" / "mcp.json"


def write_user_config(
    *,
    profile: str = "default",
    toolset: str = "default",
    academic: bool = True,
    path: str | Path | None = None,
    scholar_home: str | None = None,
) -> dict[str, object]:
    target_path = Path(path) if path is not None else get_default_user_config_path()
    payload = build_user_config_fragment(profile=profile, toolset=toolset, academic=academic, scholar_home=scholar_home)
    server_payload = payload["servers"]["scholar-agent"]
    existing = load_json_file(target_path)
    merged = merge_named_server(
        existing,
        section_key="servers",
        server_name="scholar-agent",
        server_payload=server_payload,
    )
    write_json_file(target_path, merged)
    return {
        "status": "ok",
        "host": "vscode",
        "path": str(target_path),
        "server_name": "scholar-agent",
    }


def get_user_config_status(*, path: str | Path | None = None) -> dict[str, object]:
    target_path = Path(path) if path is not None else get_default_user_config_path()
    existing = load_json_file(target_path)
    server_payload = get_named_server(existing, section_key="servers", server_name="scholar-agent")
    return {
        "status": "ok",
        "host": "vscode",
        "path": str(target_path),
        "server_name": "scholar-agent",
        "installed": server_payload is not None,
        "server": server_payload,
    }


def uninstall_user_config(*, path: str | Path | None = None) -> dict[str, object]:
    target_path = Path(path) if path is not None else get_default_user_config_path()
    existing = load_json_file(target_path)
    merged, removed = remove_named_server(existing, section_key="servers", server_name="scholar-agent")
    if removed:
        write_json_file(target_path, merged)
    return {
        "status": "ok" if removed else "noop",
        "host": "vscode",
        "path": str(target_path),
        "server_name": "scholar-agent",
        "removed": removed,
    }