"""Tests for SCHOLAR_TOOLSET — the startup-time tool surface filter in server.py.

Tools register at import time via @tool, so the filter can only run in main()
just before mcp.run(). These tests pin the pure resolver (syntax + group
membership) and drive apply_toolset on the real ``server.mcp`` through an
in-process fastmcp Client, restoring the full tool set after every test.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from scholar_agent import server
from scholar_agent.server import (
    ACADEMIC_TOOL_NAMES,
    TOOLSET_GROUPS,
    ToolsetError,
    apply_toolset,
    resolve_toolset,
)

try:
    from fastmcp import Client
except ImportError:  # pragma: no cover - fastmcp is a hard dependency
    Client = None  # type: ignore[assignment,misc]

_ROOT = Path(__file__).resolve().parents[1]

# The 13 tools server.py registers by itself (SCHOLAR_ACADEMIC unset) — the
# default surface that an unset / "default" toolset must reproduce exactly.
BUILTIN_TOOLS = frozenset(
    {
        "query_knowledge",
        "list_knowledge",
        "save_research",
        "capture_answer",
        "review_card",
        "ingest_source",
        "fetch_url",
        "build_graph",
        "import_paperpulse_note",
        "validate_knowledge",
        "lint_knowledge",
        "scan_stale_knowledge",
        "scan_dead_links",
    }
)


async def _registered() -> set[str]:
    return set(await server._registered_tool_names(server.mcp))


async def _restore_all() -> None:
    """Re-register any built-in tool missing from server.mcp (after main() ran)."""
    for name in sorted(BUILTIN_TOOLS - await _registered()):
        server.mcp.add_tool(getattr(server, name))


class ResolveToolsetTest(unittest.TestCase):
    """resolve_toolset is pure: syntax, case, separators, group membership."""

    def test_unset_empty_default_all_expose_everything(self) -> None:
        for value in (None, "", "   ", "default", "DEFAULT", "all", "All"):
            with self.subTest(value=value):
                self.assertEqual(set(BUILTIN_TOOLS), resolve_toolset(value, BUILTIN_TOOLS))

    def test_core_is_seven_tools(self) -> None:
        self.assertEqual(TOOLSET_GROUPS["core"], resolve_toolset("core", BUILTIN_TOOLS))
        self.assertEqual(7, len(resolve_toolset("core", BUILTIN_TOOLS)))

    def test_group_list_accepts_comma_space_plus_and_case(self) -> None:
        expected = TOOLSET_GROUPS["core"] | TOOLSET_GROUPS["maintenance"]
        self.assertEqual(11, len(expected))
        for value in ("core,maintenance", "core maintenance", "Core+MAINTENANCE", " core , maintenance "):
            with self.subTest(value=value):
                self.assertEqual(expected, resolve_toolset(value, BUILTIN_TOOLS))

    def test_paper_follows_scholar_academic_registration(self) -> None:
        # Only registered tools can be kept: the 8 academic tools are absent
        # unless SCHOLAR_ACADEMIC=1 registered them at import time.
        self.assertEqual({"build_graph", "import_paperpulse_note"}, resolve_toolset("paper", BUILTIN_TOOLS))
        self.assertEqual(10, len(resolve_toolset("paper", BUILTIN_TOOLS | ACADEMIC_TOOL_NAMES)))

    def test_default_anywhere_in_the_list_exposes_everything(self) -> None:
        self.assertEqual(set(BUILTIN_TOOLS), resolve_toolset("core,default", BUILTIN_TOOLS))

    def test_unknown_group_raises_naming_the_legal_values(self) -> None:
        for value in ("bogus", "core,bogus", "papers"):
            with self.subTest(value=value), self.assertRaises(ToolsetError) as ctx:
                resolve_toolset(value, BUILTIN_TOOLS)
            message = str(ctx.exception)
            for legal in ("default", "all", "core", "paper", "maintenance"):
                self.assertIn(legal, message)

    def test_only_registered_tools_are_kept(self) -> None:
        # Group members that are not registered stay absent; ungrouped registered
        # tools are not invented into a group.
        self.assertEqual(TOOLSET_GROUPS["core"], resolve_toolset("core", BUILTIN_TOOLS | {"third_party"}))
        self.assertEqual(set(), resolve_toolset("core", {"third_party"}))


class ToolsetGroupsTest(unittest.TestCase):
    """Group tables must stay in lockstep with what server.py actually registers."""

    def test_groups_are_disjoint_and_cover_every_builtin_tool(self) -> None:
        core, paper, maintenance = (TOOLSET_GROUPS[name] for name in ("core", "paper", "maintenance"))
        self.assertFalse(core & paper)
        self.assertFalse(core & maintenance)
        self.assertFalse(paper & maintenance)
        self.assertEqual(BUILTIN_TOOLS, core | (paper - ACADEMIC_TOOL_NAMES) | maintenance)
        # No group may name a tool that is neither built-in nor academic (typos).
        self.assertEqual(set(), (core | paper | maintenance) - BUILTIN_TOOLS - ACADEMIC_TOOL_NAMES)

    def test_academic_tool_names_match_scholar_academic_registration(self) -> None:
        """With SCHOLAR_ACADEMIC=1 the server must register exactly built-ins + ACADEMIC_TOOL_NAMES."""
        code = (
            "import asyncio, json; from scholar_agent import server as s; "
            "print(json.dumps(sorted(asyncio.run(s._registered_tool_names(s.mcp)))))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=dict(os.environ, SCHOLAR_ACADEMIC="1"),
            cwd=_ROOT,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(sorted(BUILTIN_TOOLS | ACADEMIC_TOOL_NAMES), json.loads(result.stdout))


@unittest.skipIf(Client is None or server.mcp is None, "fastmcp not installed")
class ApplyToolsetOnServerTest(unittest.TestCase):
    """apply_toolset on the real server.mcp, observed through an in-process Client."""

    def setUp(self) -> None:
        # Guard against leakage from other tests: the module must still expose everything.
        self.assertEqual(BUILTIN_TOOLS, asyncio.run(_registered()))

    def _exposed(self, toolset: str | None) -> set[str]:
        """Apply *toolset* to server.mcp, list tools via Client, then restore."""

        async def run() -> set[str]:
            before = {tool.name: tool for tool in await server.mcp.list_tools()}
            kept = set(before)
            try:
                kept = apply_toolset(server.mcp, toolset, before)
                async with Client(server.mcp) as client:
                    exposed = {tool.name for tool in await client.list_tools()}
                self.assertEqual(kept, exposed)
                return exposed
            finally:
                for name in before.keys() - kept:
                    server.mcp.add_tool(before[name])

        return asyncio.run(run())

    def test_unset_exposes_all_builtin_tools(self) -> None:
        self.assertEqual(BUILTIN_TOOLS, self._exposed(None))

    def test_default_exposes_all_builtin_tools(self) -> None:
        self.assertEqual(BUILTIN_TOOLS, self._exposed("default"))

    def test_core_exposes_seven_tools(self) -> None:
        self.assertEqual(TOOLSET_GROUPS["core"], self._exposed("core"))

    def test_core_and_maintenance_expose_eleven_tools(self) -> None:
        exposed = self._exposed("core,maintenance")
        self.assertEqual(TOOLSET_GROUPS["core"] | TOOLSET_GROUPS["maintenance"], exposed)
        self.assertEqual(11, len(exposed))

    def test_paper_exposes_only_registered_paper_tools(self) -> None:
        self.assertEqual({"build_graph", "import_paperpulse_note"}, self._exposed("paper"))

    def test_unknown_group_raises_before_touching_the_server(self) -> None:
        with self.assertRaises(ToolsetError):
            self._exposed("core,bogus")
        self.assertEqual(BUILTIN_TOOLS, self._exposed("default"))


@unittest.skipIf(Client is None or server.mcp is None, "fastmcp not installed")
class MainToolsetTest(unittest.TestCase):
    """main() applies SCHOLAR_TOOLSET before mcp.run(); bad values exit non-zero."""

    def setUp(self) -> None:
        self.assertEqual(BUILTIN_TOOLS, asyncio.run(_registered()))

    def test_unknown_toolset_exits_with_legal_values(self) -> None:
        stderr = io.StringIO()
        with patch.dict(os.environ, {"SCHOLAR_TOOLSET": "core,bogus"}), contextlib.redirect_stderr(stderr):
            code = server.main()
        self.assertEqual(2, code)
        self.assertIn("SCHOLAR_TOOLSET", stderr.getvalue())
        self.assertIn("'bogus'", stderr.getvalue())
        self.assertIn("default, all, core, paper, maintenance", stderr.getvalue())
        self.assertEqual(BUILTIN_TOOLS, asyncio.run(_registered()))

    def test_main_applies_toolset_before_run(self) -> None:
        with (
            patch.dict(os.environ, {"SCHOLAR_TOOLSET": "core"}),
            patch.object(server.mcp, "run") as run,
            patch("scholar_agent.server.start_local_server"),
            patch("scholar_agent.server.atexit.register"),
        ):
            code = server.main()
        self.assertEqual(0, code)
        run.assert_called_once()
        try:
            self.assertEqual(TOOLSET_GROUPS["core"], asyncio.run(_registered()))
        finally:
            asyncio.run(_restore_all())


if __name__ == "__main__":
    unittest.main()
