"""Tests for pure formatting functions from scholar_agent.cli."""

import unittest

from scholar_agent.cli import (
    _append_text_lines,
    _format_doctor_text,
    _format_mapping_text,
    build_parser,
)


class TestAppendTextLines(unittest.TestCase):
    """Tests for _append_text_lines recursive formatting."""

    def test_string_value(self) -> None:
        lines: list[str] = []
        _append_text_lines(lines, "name", "Alice")
        self.assertEqual(["name: Alice"], lines)

    def test_integer_value(self) -> None:
        lines: list[str] = []
        _append_text_lines(lines, "count", 42)
        self.assertEqual(["count: 42"], lines)

    def test_boolean_value(self) -> None:
        lines: list[str] = []
        _append_text_lines(lines, "active", True)
        self.assertEqual(["active: True"], lines)

    def test_none_value(self) -> None:
        lines: list[str] = []
        _append_text_lines(lines, "value", None)
        self.assertEqual(["value: None"], lines)

    def test_nested_dict(self) -> None:
        lines: list[str] = []
        _append_text_lines(lines, "config", {"host": "localhost", "port": 8080})
        self.assertEqual(
            [
                "config:",
                "  host: localhost",
                "  port: 8080",
            ],
            lines,
        )

    def test_deeply_nested_dict(self) -> None:
        lines: list[str] = []
        _append_text_lines(
            lines,
            "outer",
            {"mid": {"inner": "value"}},
        )
        self.assertEqual(
            [
                "outer:",
                "  mid:",
                "    inner: value",
            ],
            lines,
        )

    def test_empty_dict(self) -> None:
        lines: list[str] = []
        _append_text_lines(lines, "empty", {})
        self.assertEqual(["empty:", "  {}"], lines)

    def test_list_of_strings(self) -> None:
        lines: list[str] = []
        _append_text_lines(lines, "items", ["alpha", "beta", "gamma"])
        self.assertEqual(
            [
                "items:",
                "  - alpha",
                "  - beta",
                "  - gamma",
            ],
            lines,
        )

    def test_list_of_numbers(self) -> None:
        lines: list[str] = []
        _append_text_lines(lines, "scores", [1, 2, 3])
        self.assertEqual(
            [
                "scores:",
                "  - 1",
                "  - 2",
                "  - 3",
            ],
            lines,
        )

    def test_empty_list(self) -> None:
        lines: list[str] = []
        _append_text_lines(lines, "empty", [])
        self.assertEqual(["empty: []"], lines)

    def test_list_of_dicts(self) -> None:
        lines: list[str] = []
        _append_text_lines(lines, "entries", [{"a": 1}, {"b": 2}])
        self.assertEqual(
            [
                "entries:",
                '  - {"a": 1}',
                '  - {"b": 2}',
            ],
            lines,
        )

    def test_list_of_lists(self) -> None:
        lines: list[str] = []
        _append_text_lines(lines, "nested", [[1, 2], [3, 4]])
        self.assertEqual(
            [
                "nested:",
                "  - [1, 2]",
                "  - [3, 4]",
            ],
            lines,
        )

    def test_indent_parameter(self) -> None:
        lines: list[str] = []
        _append_text_lines(lines, "key", "val", indent="    ")
        self.assertEqual(["    key: val"], lines)

    def test_indent_propagates_to_nested(self) -> None:
        lines: list[str] = []
        _append_text_lines(lines, "root", {"child": "value"}, indent="  ")
        self.assertEqual(
            [
                "  root:",
                "    child: value",
            ],
            lines,
        )

    def test_mixed_values_in_dict(self) -> None:
        lines: list[str] = []
        _append_text_lines(
            lines,
            "data",
            {"name": "test", "items": ["a", "b"], "nested": {"x": 1}},
        )
        self.assertEqual(
            [
                "data:",
                "  name: test",
                "  items:",
                "    - a",
                "    - b",
                "  nested:",
                "    x: 1",
            ],
            lines,
        )


class TestFormatMappingText(unittest.TestCase):
    """Tests for _format_mapping_text wrapper."""

    def test_simple_payload(self) -> None:
        result = _format_mapping_text({"key": "value"})
        self.assertEqual("key: value", result)

    def test_multiple_keys(self) -> None:
        result = _format_mapping_text({"a": 1, "b": 2})
        self.assertIn("a: 1", result)
        self.assertIn("b: 2", result)

    def test_empty_dict(self) -> None:
        result = _format_mapping_text({})
        self.assertEqual("", result)

    def test_nested_mapping(self) -> None:
        result = _format_mapping_text({"outer": {"inner": "val"}})
        self.assertEqual("outer:\n  inner: val", result)

    def test_list_value_in_mapping(self) -> None:
        result = _format_mapping_text({"items": ["x", "y"]})
        self.assertEqual("items:\n  - x\n  - y", result)


class TestFormatDoctorText(unittest.TestCase):
    """Tests for _format_doctor_text with various payload structures."""

    def _base_payload(self) -> dict:
        return {
            "mode": "editable",
            "config_file": "/home/user/.scholar-agent/config/config.json",
            "user_home": "/home/user/.scholar-agent",
            "knowledge_cards": 5,
            "dependencies": {"fastmcp": True, "PyMuPDF": True},
            "mcp": {"claude_registered": True},
            "executable": {
                "scholar_agent_on_path": True,
                "module_runnable": True,
                "python_executable": "/usr/bin/python3",
            },
            "checks": [
                {
                    "check": "knowledge_dir",
                    "path": "/home/user/.scholar-agent/knowledge",
                    "exists": True,
                    "writable": True,
                },
                {
                    "check": "index_dir",
                    "path": "/home/user/.scholar-agent/indexes",
                    "exists": True,
                    "writable": True,
                },
                {
                    "check": "index",
                    "path": "/home/user/.scholar-agent/indexes/local/index.json",
                    "exists": True,
                    "valid": True,
                },
            ],
            "environment": {
                "SCHOLAR_HOME": None,
                "SCHOLAR_PROFILE": None,
                "PYTHONUTF8": "1",
            },
        }

    def test_all_checks_passed(self) -> None:
        text = _format_doctor_text(self._base_payload())
        self.assertIn("All checks passed.", text)
        self.assertNotIn("Problems", text)

    def test_missing_pymupdf(self) -> None:
        payload = self._base_payload()
        payload["dependencies"]["PyMuPDF"] = False
        text = _format_doctor_text(payload)
        self.assertIn("PyMuPDF: MISSING", text)
        self.assertIn("PyMuPDF not installed", text)

    def test_missing_fastmcp(self) -> None:
        payload = self._base_payload()
        payload["dependencies"]["fastmcp"] = False
        text = _format_doctor_text(payload)
        self.assertIn("fastmcp: MISSING", text)
        self.assertIn("fastmcp not found", text)

    def test_unregistered_mcp(self) -> None:
        payload = self._base_payload()
        payload["mcp"]["claude_registered"] = False
        text = _format_doctor_text(payload)
        self.assertIn("claude: NOT registered", text)
        self.assertIn("Claude Code MCP not registered", text)

    def test_broken_module(self) -> None:
        payload = self._base_payload()
        payload["executable"]["module_runnable"] = False
        text = _format_doctor_text(payload)
        self.assertIn("python -m scholar_agent.cli: BROKEN", text)
        self.assertIn("scholar_agent.cli module not importable", text)

    def test_missing_knowledge_dir(self) -> None:
        payload = self._base_payload()
        payload["checks"][0]["exists"] = False
        text = _format_doctor_text(payload)
        self.assertIn("knowledge_dir: MISSING", text)
        self.assertIn("knowledge_dir does not exist", text)

    def test_non_writable_dir(self) -> None:
        payload = self._base_payload()
        payload["checks"][1]["exists"] = True
        payload["checks"][1]["writable"] = False
        text = _format_doctor_text(payload)
        self.assertIn("index_dir: NOT WRITABLE", text)
        self.assertIn("index_dir is not writable", text)

    def test_index_not_found(self) -> None:
        payload = self._base_payload()
        payload["checks"][2]["exists"] = False
        text = _format_doctor_text(payload)
        self.assertIn("index: not found", text)

    def test_index_empty(self) -> None:
        payload = self._base_payload()
        payload["checks"][2]["valid"] = False
        text = _format_doctor_text(payload)
        self.assertIn("index: empty", text)

    def test_index_ok(self) -> None:
        text = _format_doctor_text(self._base_payload())
        self.assertIn("index: ok", text)

    def test_environment_set(self) -> None:
        text = _format_doctor_text(self._base_payload())
        self.assertIn("Environment:", text)
        self.assertIn("PYTHONUTF8: 1", text)

    def test_no_environment_set(self) -> None:
        payload = self._base_payload()
        payload["environment"] = {
            "SCHOLAR_HOME": None,
            "SCHOLAR_PROFILE": None,
            "PYTHONUTF8": None,
        }
        text = _format_doctor_text(payload)
        self.assertNotIn("Environment:", text)

    def test_multiple_problems_count(self) -> None:
        payload = self._base_payload()
        payload["dependencies"]["PyMuPDF"] = False
        payload["dependencies"]["fastmcp"] = False
        payload["mcp"]["claude_registered"] = False
        text = _format_doctor_text(payload)
        self.assertIn("Problems (3):", text)

    def test_no_checks_list(self) -> None:
        payload = self._base_payload()
        payload["checks"] = []
        text = _format_doctor_text(payload)
        self.assertNotIn("Directories:", text)

    def test_dependencies_is_not_dict(self) -> None:
        payload = self._base_payload()
        payload["dependencies"] = None
        text = _format_doctor_text(payload)
        self.assertNotIn("Dependencies:", text)

    def test_exe_not_on_path(self) -> None:
        payload = self._base_payload()
        payload["executable"]["scholar_agent_on_path"] = False
        text = _format_doctor_text(payload)
        self.assertIn("on PATH: no", text)

    def test_exe_on_path(self) -> None:
        text = _format_doctor_text(self._base_payload())
        self.assertIn("on PATH: yes", text)


class TestBuildParser(unittest.TestCase):
    """Tests for build_parser argument parsing."""

    def test_serve_mcp(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["serve-mcp"])
        self.assertEqual(args.command, "serve-mcp")

    def test_doctor_default_format(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["doctor"])
        self.assertEqual(args.command, "doctor")
        self.assertEqual(args.format, "json")

    def test_doctor_text_format(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["doctor", "--format", "text"])
        self.assertEqual(args.format, "text")

    def test_config_show(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["config", "show"])
        self.assertEqual(args.command, "config")
        self.assertEqual(args.config_command, "show")
        self.assertEqual(args.format, "json")

    def test_config_show_text(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["config", "show", "--format", "text"])
        self.assertEqual(args.format, "text")

    def test_config_init(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["config", "init"])
        self.assertEqual(args.command, "config")
        self.assertEqual(args.config_command, "init")
        self.assertFalse(args.force)

    def test_config_init_force(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["config", "init", "--force"])
        self.assertTrue(args.force)

    def test_config_migrate(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["config", "migrate"])
        self.assertEqual(args.config_command, "migrate")
        self.assertFalse(args.dry_run)
        self.assertFalse(args.force)

    def test_config_migrate_dry_run(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["config", "migrate", "--dry-run"])
        self.assertTrue(args.dry_run)

    def test_init_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["init"])
        self.assertEqual(args.command, "init")
        self.assertFalse(args.force)
        self.assertEqual(args.host, "claude")
        self.assertFalse(args.skip_register)
        self.assertTrue(args.academic)

    def test_init_all_hosts(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["init", "--host", "all"])
        self.assertEqual(args.host, "all")

    def test_init_skip_register(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["init", "--skip-register"])
        self.assertTrue(args.skip_register)

    def test_init_no_academic(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["init", "--no-academic"])
        self.assertFalse(args.academic)

    def test_install_claude(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["install", "claude"])
        self.assertEqual(args.command, "install")
        self.assertEqual(args.host, "claude")
        self.assertFalse(args.write)
        self.assertFalse(args.status)
        self.assertFalse(args.uninstall)

    def test_install_with_write(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["install", "vscode", "--write"])
        self.assertTrue(args.write)

    def test_install_with_status(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["install", "opencode", "--status"])
        self.assertTrue(args.status)

    def test_install_with_uninstall(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["install", "claude", "--uninstall"])
        self.assertTrue(args.uninstall)

    def test_install_with_scope(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["install", "claude", "--scope", "project"])
        self.assertEqual(args.scope, "project")

    def test_runtime_status(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["runtime", "status"])
        self.assertEqual(args.command, "runtime")
        self.assertEqual(args.runtime_command, "status")

    def test_runtime_build_wheel(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["runtime", "build-wheel"])
        self.assertEqual(args.runtime_command, "build-wheel")

    def test_no_command_defaults_to_none(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        self.assertIsNone(args.command)


if __name__ == "__main__":
    unittest.main()
