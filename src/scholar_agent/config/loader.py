"""Config resolution for Scholar Agent."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from scholar_agent.config.paths import build_default_config, get_scholar_root, get_user_config_path
from scholar_agent.config.profiles import get_active_profile


logger = logging.getLogger(__name__)
_PATH_KEYS = ("knowledge_dir", "index_path", "scholar_dir", "paper_notes_dir", "daily_notes_dir")


@dataclass(frozen=True)
class ConfigResolution:
    mode: str
    config_file: Path | None
    config: dict[str, Any]


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to parse %s: %s — skipping", path, exc)
        return None


def _resolve_runtime_config_path(raw_path: str, cwd: Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    return candidate.resolve()


def _find_workspace_config(cwd: Path) -> Path | None:
    current = cwd.resolve()
    for _ in range(10):
        candidate = current / ".scholar.json"
        if candidate.exists():
            return candidate.resolve()
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _find_repo_embedded_config(scholar_root: Path) -> Path | None:
    candidate = (scholar_root / ".scholar.json").resolve()
    if candidate.exists():
        return candidate
    return None


def _cwd_is_within_scholar_root(cwd: Path, scholar_root: Path) -> bool:
    try:
        cwd.resolve().relative_to(scholar_root.resolve())
        return True
    except ValueError:
        return False


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = value
    return result


def _merge_config(config: dict[str, Any], overrides: Mapping[str, Any], config_base: Path) -> None:
    for key in _PATH_KEYS:
        if key not in overrides:
            continue
        val = overrides[key]
        if val is None:
            continue
        resolved = Path(str(val)).expanduser()
        if not resolved.is_absolute():
            resolved = config_base / resolved
        config[key] = str(resolved.resolve())

    for key, val in overrides.items():
        if key not in _PATH_KEYS:
            existing = config.get(key)
            if isinstance(existing, dict) and isinstance(val, Mapping):
                config[key] = _deep_merge(existing, val)
            else:
                config[key] = val


def resolve_config(
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    scholar_root: Path | None = None,
) -> ConfigResolution:
    effective_cwd = (cwd or Path.cwd()).resolve()
    env_map = os.environ if env is None else env
    resolved_scholar_root = (scholar_root or get_scholar_root()).resolve()

    config: dict[str, Any] = build_default_config(env=env_map, scholar_root=resolved_scholar_root)
    mode = "user-default"
    active_config_file: Path | None = None

    user_config_path = get_user_config_path(env_map)
    if user_config_path.exists():
        user_config = _load_json(user_config_path)
        if user_config is not None:
            _merge_config(config, user_config, user_config_path.parent)
            mode = "user-config"
            active_config_file = user_config_path

    workspace_config_path = _find_workspace_config(effective_cwd)
    repo_config_path = _find_repo_embedded_config(resolved_scholar_root)

    selected_local_config: tuple[str, Path] | None = None
    if workspace_config_path is not None:
        if repo_config_path is not None and workspace_config_path == repo_config_path:
            selected_local_config = ("repo-embedded", repo_config_path)
        else:
            selected_local_config = ("workspace", workspace_config_path)
    elif repo_config_path is not None and _cwd_is_within_scholar_root(effective_cwd, resolved_scholar_root):
        selected_local_config = ("repo-embedded", repo_config_path)

    if selected_local_config is not None:
        local_mode, local_path = selected_local_config
        local_config = _load_json(local_path)
        if local_config is not None:
            _merge_config(config, local_config, local_path.parent)
            mode = local_mode
            active_config_file = local_path

    explicit_path = env_map.get("SCHOLAR_CONFIG", "").strip()
    if explicit_path:
        runtime_config_path = _resolve_runtime_config_path(explicit_path, effective_cwd)
        if runtime_config_path.exists():
            runtime_config = _load_json(runtime_config_path)
            if runtime_config is not None:
                _merge_config(config, runtime_config, runtime_config_path.parent)
                mode = "runtime-config"
                active_config_file = runtime_config_path
        else:
            logger.warning("SCHOLAR_CONFIG points to a missing file: %s", runtime_config_path)

    config["profile"] = get_active_profile(config=config, env=env_map)

    return ConfigResolution(mode=mode, config_file=active_config_file, config=config)