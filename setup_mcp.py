#!/usr/bin/env python3
"""Inject Lore Agent MCP configuration into the parent project.

Usage:
  # From the parent project root:
  python lore-agent/setup_mcp.py

This will:
  1. Create .lore.json config pointing knowledge to the parent project
  2. Create knowledge/ and indexes/ directories in the parent project
  3. Add Lore MCP server to .mcp.json (Claude Code)
  4. Add Lore MCP server to .vscode/mcp.json (VS Code Copilot)
  5. Add a CLAUDE.md snippet instructing the AI to use Lore tools
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


LORE_DIR_NAME = "lore-agent"


def get_lore_dir() -> Path:
    """Find the lore-agent directory relative to cwd."""
    # If cwd is inside lore-agent itself
    cwd = Path.cwd()
    if (cwd / "mcp_server.py").exists() and (cwd / "scripts").is_dir():
        return cwd

    # If lore-agent is a subdirectory of cwd
    candidate = cwd / LORE_DIR_NAME
    if candidate.is_dir() and (candidate / "mcp_server.py").exists():
        return candidate

    print("Error: run this script from the parent project root or the lore-agent directory.", file=sys.stderr)
    sys.exit(1)


def setup_claude_code(parent_root: Path, lore_dir: Path) -> None:
    """Inject MCP config into .mcp.json for Claude Code."""
    mcp_path = parent_root / ".mcp.json"
    lore_relative = lore_dir.relative_to(parent_root)

    if mcp_path.exists():
        config = json.loads(mcp_path.read_text(encoding="utf-8"))
    else:
        config = {}

    if "mcpServers" not in config:
        config["mcpServers"] = {}

    config["mcpServers"]["lore"] = {
        "command": "uv",
        "args": [
            "run", "--with", "fastmcp", "fastmcp", "run",
            f"{lore_relative}/mcp_server.py",
        ],
    }

    mcp_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  Updated {mcp_path.relative_to(parent_root)}")


def setup_vscode(parent_root: Path, lore_dir: Path) -> None:
    """Inject MCP config into .vscode/mcp.json for VS Code Copilot."""
    vscode_dir = parent_root / ".vscode"
    vscode_dir.mkdir(exist_ok=True)
    mcp_path = vscode_dir / "mcp.json"
    lore_relative = lore_dir.relative_to(parent_root)

    if mcp_path.exists():
        config = json.loads(mcp_path.read_text(encoding="utf-8"))
    else:
        config = {}

    if "servers" not in config:
        config["servers"] = {}

    config["servers"]["lore"] = {
        "type": "stdio",
        "command": "uv",
        "args": [
            "run", "--with", "fastmcp", "fastmcp", "run",
            f"{lore_relative}/mcp_server.py",
        ],
    }

    mcp_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  Updated {mcp_path.relative_to(parent_root)}")


def setup_claude_md(parent_root: Path, lore_dir: Path) -> None:
    """Add a CLAUDE.md snippet instructing the AI to prioritize Lore tools."""
    claude_md_path = parent_root / "CLAUDE.md"
    snippet = (
        "# Lore Agent\n"
        "\n"
        "This project has Lore Agent for domain knowledge retrieval and research.\n"
        "When the user asks domain-specific questions or needs research:\n"
        "\n"
        "1. **First** use the `query_knowledge` MCP tool to check local knowledge.\n"
        "2. If local knowledge is insufficient, use `save_research` to save findings.\n"
        "3. Use `list_knowledge` to browse available knowledge cards.\n"
    )

    if claude_md_path.exists():
        content = claude_md_path.read_text(encoding="utf-8")
        if "# Lore Agent" in content or "query_knowledge" in content:
            print(f"  CLAUDE.md already contains Lore instructions, skipping")
            return
        content = content.rstrip() + "\n\n" + snippet
    else:
        content = snippet

    claude_md_path.write_text(content, encoding="utf-8")
    print(f"  Updated {claude_md_path.relative_to(parent_root)}")


def setup_lore_config(parent_root: Path, lore_dir: Path) -> None:
    """Create .lore.json in the parent project pointing knowledge to parent."""
    config_path = parent_root / ".lore.json"

    config = {
        "knowledge_dir": "./knowledge",
        "index_path": "./indexes/local/index.json",
        "lore_dir": f"./{lore_dir.relative_to(parent_root)}",
    }

    if config_path.exists():
        existing = json.loads(config_path.read_text(encoding="utf-8"))
        existing.update(config)
        config = existing

    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  Updated {config_path.relative_to(parent_root)}")

    # Create knowledge and indexes directories
    (parent_root / "knowledge").mkdir(exist_ok=True)
    (parent_root / "indexes" / "local").mkdir(parents=True, exist_ok=True)

    # Copy templates if knowledge dir is empty
    knowledge_dir = parent_root / "knowledge"
    templates_src = lore_dir / "knowledge" / "templates"
    templates_dst = knowledge_dir / "templates"
    if templates_src.exists() and not templates_dst.exists():
        import shutil
        shutil.copytree(templates_src, templates_dst)
        print(f"  Copied templates to knowledge/templates/")

    # Copy example card if knowledge dir has no cards
    has_cards = any(
        p.is_file() and p.suffix == ".md" and "templates" not in p.parts
        for p in knowledge_dir.rglob("*.md")
    )
    if not has_cards:
        examples_src = lore_dir / "knowledge" / "examples"
        examples_dst = knowledge_dir / "examples"
        if examples_src.exists():
            import shutil
            if not examples_dst.exists():
                shutil.copytree(examples_src, examples_dst)
            else:
                for f in examples_src.glob("*.md"):
                    shutil.copy2(f, examples_dst / f.name)
            print(f"  Copied example cards to knowledge/examples/")


def main() -> int:
    lore_dir = get_lore_dir()
    if lore_dir == Path.cwd():
        parent_root = lore_dir.parent
    else:
        parent_root = Path.cwd()

    print(f"Setting up Lore Agent for: {parent_root}")
    print(f"Lore directory: {lore_dir}")
    print()

    setup_lore_config(parent_root, lore_dir)
    setup_claude_code(parent_root, lore_dir)
    setup_vscode(parent_root, lore_dir)
    setup_claude_md(parent_root, lore_dir)

    print()
    print("Done! Restart Claude Code or VS Code to activate the MCP server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
