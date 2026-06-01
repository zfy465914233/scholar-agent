"""Tests for installer modules — pure functions and tmpdir-based operations."""

import json
import tempfile
import unittest
from pathlib import Path

from scholar_agent.installers.claude import (
    _claude_config_path,
    build_user_config_fragment as claude_fragment,
)
from scholar_agent.installers.common import (
    build_local_server,
    build_shared_env,
    build_stdio_server,
    load_json_file,
    merge_named_server,
    remove_named_server,
    write_json_file,
)
from scholar_agent.installers.opencode import (
    build_user_config_fragment as opencode_fragment,
    get_default_user_config_path as opencode_config_path,
)
from scholar_agent.installers.vscode import (
    build_user_config_fragment as vscode_fragment,
    get_default_user_config_path as vscode_config_path,
    get_user_config_status as vscode_status,
    uninstall_user_config as vscode_uninstall,
    write_user_config as vscode_write,
)


class TestClaudeConfigPath(unittest.TestCase):
    def test_user_scope(self) -> None:
        path = _claude_config_path("user")
        self.assertEqual(path.name, ".claude.json")

    def test_project_scope_with_cwd(self) -> None:
        path = _claude_config_path("project", cwd="/tmp/project")
        self.assertEqual(Path(path), Path("/tmp/project"))

    def test_local_scope_default(self) -> None:
        path = _claude_config_path("local")
        self.assertEqual(path.name, ".claude.json")


class TestClaudeFragment(unittest.TestCase):
    def test_has_mcp_servers(self) -> None:
        frag = claude_fragment(academic=False)
        self.assertIn("mcpServers", frag)
        self.assertIn("scholar-agent", frag["mcpServers"])

    def test_server_type_stdio(self) -> None:
        frag = claude_fragment()
        server = frag["mcpServers"]["scholar-agent"]
        self.assertEqual(server["type"], "stdio")


class TestVscodeFragment(unittest.TestCase):
    def test_has_servers(self) -> None:
        frag = vscode_fragment(academic=False)
        self.assertIn("servers", frag)
        self.assertIn("scholar-agent", frag["servers"])

    def test_default_path_mac(self) -> None:
        path = vscode_config_path()
        self.assertTrue(str(path).endswith("mcp.json"))


class TestOpencodeFragment(unittest.TestCase):
    def test_has_mcp(self) -> None:
        frag = opencode_fragment(academic=False)
        self.assertIn("mcp", frag)
        self.assertIn("$schema", frag)

    def test_default_path(self) -> None:
        path = opencode_config_path()
        self.assertTrue(str(path).endswith("opencode.json"))


class TestVscodeWriteAndStatus(unittest.TestCase):
    def test_write_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "mcp.json"
            result = vscode_write(path=target, academic=False)
            self.assertEqual(result["status"], "ok")
            self.assertTrue(target.exists())
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn("servers", data)
            self.assertIn("scholar-agent", data["servers"])

    def test_status_detects_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "mcp.json"
            vscode_write(path=target, academic=False)
            result = vscode_status(path=target)
            self.assertTrue(result["installed"])

    def test_status_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "mcp.json"
            result = vscode_status(path=target)
            self.assertFalse(result["installed"])

    def test_uninstall_removes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "mcp.json"
            vscode_write(path=target, academic=False)
            result = vscode_uninstall(path=target)
            self.assertTrue(result["removed"])
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertNotIn("scholar-agent", data.get("servers", {}))

    def test_uninstall_noop_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "mcp.json"
            result = vscode_uninstall(path=target)
            self.assertEqual(result["status"], "noop")


if __name__ == "__main__":
    unittest.main()
