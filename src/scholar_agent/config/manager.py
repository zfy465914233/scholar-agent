"""Management helpers for Scholar Agent user-level configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from scholar_agent.config.loader import resolve_config
from scholar_agent.config.paths import build_default_config, get_user_config_path, get_user_home
from scholar_agent.engine.common import atomic_write_text

if TYPE_CHECKING:
    from collections.abc import Mapping


def _user_home_directories(user_home: Path, env: Mapping[str, str] | None = None) -> list[Path]:
    """Build the list of directories that ``init`` should create.

    Infrastructure dirs (config, indexes, cache, logs) go under *user_home*
    (``~/.scholar/`` by default).  Data dirs (knowledge, paper-notes,
    daily-notes) are resolved from :func:`build_default_config` so they end up
    in the correct ``data_home`` (``~/scholar/`` by default) rather than
    alongside infrastructure files.
    """
    defaults = build_default_config(env=env)

    # Infrastructure (under user_home)
    infra = [
        user_home,
        user_home / "config",
        user_home / "config" / "profiles",
        user_home / "indexes" / "local",
        user_home / "cache",
        user_home / "logs",
        user_home / "outputs",
    ]

    # Data (resolved from config defaults — ~/scholar/ by default)
    data = [
        Path(defaults["knowledge_dir"]),
        Path(defaults["academic"]["paper_notes_dir"]),
        Path(defaults["academic"]["daily_notes_dir"]),
    ]

    return infra + data


def initialize_user_home(
    *, force: bool = False, write_config: bool = True, env: Mapping[str, str] | None = None
) -> dict[str, object]:
    user_home = get_user_home(env)
    user_config_path = get_user_config_path(env)

    directories = _user_home_directories(user_home, env=env)

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    wrote_config = False
    if write_config and (force or not user_config_path.exists()):
        user_config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = build_default_config(env=env)
        atomic_write_text(user_config_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        wrote_config = True

    return {
        "status": "ok",
        "user_home": str(user_home),
        "user_config_path": str(user_config_path),
        "config_written": wrote_config,
        "directories_created": [str(directory) for directory in directories],
    }


def migrate_to_user_home(
    *,
    force: bool = False,
    dry_run: bool = False,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    scholar_root: Path | None = None,
) -> dict[str, object]:
    init_result = initialize_user_home(force=False, write_config=False, env=env)
    resolution = resolve_config(cwd=cwd, env=env, scholar_root=scholar_root)
    target_path = get_user_config_path(env)
    target_exists = target_path.exists()

    if resolution.config_file is not None and resolution.config_file.resolve() == target_path.resolve():
        return {
            "status": "noop",
            "reason": "resolved config already points at the user config file",
            "source_mode": resolution.mode,
            "source_config_file": str(resolution.config_file),
            "target_config_file": str(target_path),
            "dry_run": dry_run,
        }

    if target_exists and not force:
        return {
            "status": "blocked",
            "reason": "target user config already exists; rerun with --force to overwrite",
            "source_mode": resolution.mode,
            "source_config_file": str(resolution.config_file) if resolution.config_file is not None else None,
            "target_config_file": str(target_path),
            "dry_run": dry_run,
        }

    if not dry_run:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            target_path, json.dumps(resolution.config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    return {
        "status": "planned" if dry_run else "ok",
        "source_mode": resolution.mode,
        "source_config_file": str(resolution.config_file) if resolution.config_file is not None else None,
        "target_config_file": str(target_path),
        "dry_run": dry_run,
        "target_preexisted": target_exists,
        "directories_created": init_result["directories_created"],
        "resolved": resolution.config,
    }
