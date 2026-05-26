"""Shared config helpers for host-specific MCP installers."""

from __future__ import annotations

import json
from pathlib import Path


def build_shared_env(*, profile: str, toolset: str, academic: bool, scholar_home: str | None = None) -> dict[str, str]:
    env = {
        "SCHOLAR_PROFILE": profile,
        "SCHOLAR_TOOLSET": toolset,
    }
    if academic:
        env["SCHOLAR_ACADEMIC"] = "1"
    if scholar_home:
        env["SCHOLAR_HOME"] = scholar_home
    return env


def build_stdio_server(*, profile: str, toolset: str, academic: bool, scholar_home: str | None = None) -> dict[str, object]:
    return {
        "type": "stdio",
        "command": "scholar-agent",
        "args": ["serve-mcp"],
        "env": build_shared_env(profile=profile, toolset=toolset, academic=academic, scholar_home=scholar_home),
    }


def build_local_server(*, profile: str, toolset: str, academic: bool, scholar_home: str | None = None) -> dict[str, object]:
    return {
        "type": "local",
        "command": ["scholar-agent", "serve-mcp"],
        "enabled": True,
        "environment": build_shared_env(profile=profile, toolset=toolset, academic=academic, scholar_home=scholar_home),
    }


def load_json_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def write_json_file(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_named_server(
    existing: dict[str, object],
    *,
    section_key: str,
    server_name: str,
    server_payload: dict[str, object],
    default_top_level: dict[str, object] | None = None,
) -> dict[str, object]:
    merged = dict(existing)
    if default_top_level:
        for key, value in default_top_level.items():
            merged.setdefault(key, value)

    section = merged.get(section_key, {})
    if not isinstance(section, dict):
        section = {}
    next_section = dict(section)
    next_section[server_name] = server_payload
    merged[section_key] = next_section
    return merged


def get_named_server(existing: dict[str, object], *, section_key: str, server_name: str) -> object | None:
    section = existing.get(section_key, {})
    if not isinstance(section, dict):
        return None
    return section.get(server_name)


def remove_named_server(
    existing: dict[str, object],
    *,
    section_key: str,
    server_name: str,
) -> tuple[dict[str, object], bool]:
    merged = dict(existing)
    section = merged.get(section_key, {})
    if not isinstance(section, dict) or server_name not in section:
        return merged, False

    next_section = dict(section)
    next_section.pop(server_name, None)
    merged[section_key] = next_section
    return merged, True