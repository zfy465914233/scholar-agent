"""Profile helpers for Scholar Agent configuration."""

from __future__ import annotations

import os
from typing import Any, Mapping


def get_active_profile(config: Mapping[str, Any] | None = None, env: Mapping[str, str] | None = None) -> str:
    env_map = os.environ if env is None else env
    env_profile = env_map.get("SCHOLAR_PROFILE", "").strip()
    if env_profile:
        return env_profile
    if config is not None:
        profile = config.get("profile")
        if isinstance(profile, str) and profile.strip():
            return profile.strip()
    return "default"