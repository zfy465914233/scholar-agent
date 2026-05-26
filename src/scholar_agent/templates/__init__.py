"""Template loader for paper note sections."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

_SECTION_RE = re.compile(r"<!-- section:(\w+) -->\n(.*?)(?=<!-- section:\w+ -->|\Z)", re.DOTALL)


def _load_template(filename: str) -> dict[str, str]:
    """Load a template file and parse it into named sections."""
    templates_dir = Path(__file__).resolve().parent
    text = (templates_dir / filename).read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    for m in _SECTION_RE.finditer(text):
        name = m.group(1)
        content = m.group(2).strip()
        if content:
            sections[name] = content + "\n"
    return sections


def load_zh_sections() -> dict[str, str]:
    return _load_template("paper-zh.md")


def load_en_sections() -> dict[str, str]:
    return _load_template("paper-en.md")
