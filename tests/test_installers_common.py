"""Tests for scholar_agent.installers.common module."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from scholar_agent.installers.common import (
    build_local_server,
    build_shared_env,
    build_stdio_server,
    get_named_server,
    load_json_file,
    merge_named_server,
    remove_named_server,
    write_json_file,
)


class BuildSharedEnvTest(unittest.TestCase):
    def test_basic_profile_and_toolset(self) -> None:
        env = build_shared_env(profile="default", toolset="full", academic=False)
        self.assertEqual(env["SCHOLAR_PROFILE"], "default")
        self.assertEqual(env["SCHOLAR_TOOLSET"], "full")

    def test_academic_true_adds_env_var(self) -> None:
        env = build_shared_env(profile="research", toolset="core", academic=True)
        self.assertEqual(env["SCHOLAR_ACADEMIC"], "1")

    def test_academic_false_no_env_var(self) -> None:
        env = build_shared_env(profile="default", toolset="full", academic=False)
        self.assertNotIn("SCHOLAR_ACADEMIC", env)

    def test_scholar_home_set(self) -> None:
        env = build_shared_env(profile="p", toolset="t", academic=False, scholar_home="/data/scholar")
        self.assertEqual(env["SCHOLAR_HOME"], "/data/scholar")

    def test_scholar_home_none_not_set(self) -> None:
        env = build_shared_env(profile="p", toolset="t", academic=False, scholar_home=None)
        self.assertNotIn("SCHOLAR_HOME", env)

    def test_scholar_home_empty_string_not_set(self) -> None:
        env = build_shared_env(profile="p", toolset="t", academic=False, scholar_home="")
        self.assertNotIn("SCHOLAR_HOME", env)

    def test_returns_dict_with_string_values(self) -> None:
        env = build_shared_env(profile="p", toolset="t", academic=True, scholar_home="/tmp")
        for key, value in env.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(value, str)


class BuildStdioServerTest(unittest.TestCase):
    def test_type_is_stdio(self) -> None:
        server = build_stdio_server(profile="default", toolset="full", academic=False)
        self.assertEqual(server["type"], "stdio")

    def test_command_is_python(self) -> None:
        server = build_stdio_server(profile="default", toolset="full", academic=False)
        self.assertEqual(server["command"], sys.executable)

    def test_args_contains_serve_mcp(self) -> None:
        server = build_stdio_server(profile="default", toolset="full", academic=False)
        self.assertIn("serve-mcp", server["args"])
        self.assertEqual(server["args"][0], "-m")

    def test_env_included(self) -> None:
        server = build_stdio_server(profile="p", toolset="t", academic=True)
        self.assertIn("SCHOLAR_PROFILE", server["env"])
        self.assertEqual(server["env"]["SCHOLAR_PROFILE"], "p")

    def test_scholar_home_forwarded(self) -> None:
        server = build_stdio_server(profile="p", toolset="t", academic=False, scholar_home="/custom")
        self.assertEqual(server["env"]["SCHOLAR_HOME"], "/custom")

    def test_academic_env_forwarded(self) -> None:
        server = build_stdio_server(profile="p", toolset="t", academic=True)
        self.assertEqual(server["env"]["SCHOLAR_ACADEMIC"], "1")

    def test_no_extra_keys(self) -> None:
        server = build_stdio_server(profile="p", toolset="t", academic=False)
        self.assertEqual(set(server.keys()), {"type", "command", "args", "env"})


class BuildLocalServerTest(unittest.TestCase):
    def test_type_is_local(self) -> None:
        server = build_local_server(profile="default", toolset="full", academic=False)
        self.assertEqual(server["type"], "local")

    def test_command_is_list(self) -> None:
        server = build_local_server(profile="default", toolset="full", academic=False)
        self.assertIsInstance(server["command"], list)
        self.assertIn(sys.executable, server["command"])

    def test_enabled_is_true(self) -> None:
        server = build_local_server(profile="default", toolset="full", academic=False)
        self.assertTrue(server["enabled"])

    def test_environment_key(self) -> None:
        server = build_local_server(profile="p", toolset="t", academic=True)
        self.assertIn("SCHOLAR_PROFILE", server["environment"])
        self.assertEqual(server["environment"]["SCHOLAR_PROFILE"], "p")

    def test_scholar_home_forwarded(self) -> None:
        server = build_local_server(profile="p", toolset="t", academic=False, scholar_home="/data")
        self.assertEqual(server["environment"]["SCHOLAR_HOME"], "/data")

    def test_no_extra_keys(self) -> None:
        server = build_local_server(profile="p", toolset="t", academic=False)
        self.assertEqual(set(server.keys()), {"type", "command", "enabled", "environment"})

    def test_command_contains_serve_mcp(self) -> None:
        server = build_local_server(profile="p", toolset="t", academic=False)
        self.assertIn("serve-mcp", server["command"])


class MergeNamedServerTest(unittest.TestCase):
    def test_adds_server_to_empty_config(self) -> None:
        result = merge_named_server(
            {},
            section_key="mcpServers",
            server_name="scholar",
            server_payload={"type": "stdio"},
        )
        self.assertIn("mcpServers", result)
        self.assertIn("scholar", result["mcpServers"])
        self.assertEqual(result["mcpServers"]["scholar"]["type"], "stdio")

    def test_adds_to_existing_section(self) -> None:
        existing = {"mcpServers": {"other": {"type": "other"}}}
        result = merge_named_server(
            existing,
            section_key="mcpServers",
            server_name="scholar",
            server_payload={"type": "stdio"},
        )
        self.assertIn("other", result["mcpServers"])
        self.assertIn("scholar", result["mcpServers"])

    def test_overwrites_existing_server(self) -> None:
        existing = {"mcpServers": {"scholar": {"type": "old"}}}
        result = merge_named_server(
            existing,
            section_key="mcpServers",
            server_name="scholar",
            server_payload={"type": "new"},
        )
        self.assertEqual(result["mcpServers"]["scholar"]["type"], "new")

    def test_does_not_mutate_original(self) -> None:
        existing = {"mcpServers": {"old": {"type": "a"}}}
        original = json.loads(json.dumps(existing))
        merge_named_server(
            existing,
            section_key="mcpServers",
            server_name="new",
            server_payload={"type": "b"},
        )
        self.assertEqual(existing, original)

    def test_default_top_level_setdefault(self) -> None:
        result = merge_named_server(
            {},
            section_key="mcpServers",
            server_name="scholar",
            server_payload={"type": "stdio"},
            default_top_level={"version": "1.0"},
        )
        self.assertEqual(result["version"], "1.0")

    def test_default_top_level_does_not_overwrite(self) -> None:
        result = merge_named_server(
            {"version": "2.0"},
            section_key="mcpServers",
            server_name="scholar",
            server_payload={"type": "stdio"},
            default_top_level={"version": "1.0"},
        )
        self.assertEqual(result["version"], "2.0")

    def test_non_dict_section_replaced(self) -> None:
        existing = {"mcpServers": "not a dict"}
        result = merge_named_server(
            existing,
            section_key="mcpServers",
            server_name="scholar",
            server_payload={"type": "stdio"},
        )
        self.assertIsInstance(result["mcpServers"], dict)
        self.assertIn("scholar", result["mcpServers"])

    def test_none_default_top_level(self) -> None:
        result = merge_named_server(
            {},
            section_key="mcpServers",
            server_name="scholar",
            server_payload={"type": "stdio"},
            default_top_level=None,
        )
        self.assertIn("mcpServers", result)

    def test_empty_default_top_level(self) -> None:
        result = merge_named_server(
            {},
            section_key="mcpServers",
            server_name="scholar",
            server_payload={"type": "stdio"},
            default_top_level={},
        )
        self.assertIn("mcpServers", result)


class GetNamedServerTest(unittest.TestCase):
    def test_retrieves_existing_server(self) -> None:
        config = {"mcpServers": {"scholar": {"type": "stdio"}}}
        result = get_named_server(config, section_key="mcpServers", server_name="scholar")
        self.assertEqual(result, {"type": "stdio"})

    def test_returns_none_for_missing_server(self) -> None:
        config = {"mcpServers": {"other": {"type": "stdio"}}}
        result = get_named_server(config, section_key="mcpServers", server_name="scholar")
        self.assertIsNone(result)

    def test_returns_none_for_missing_section(self) -> None:
        result = get_named_server({}, section_key="mcpServers", server_name="scholar")
        self.assertIsNone(result)

    def test_returns_none_for_non_dict_section(self) -> None:
        config = {"mcpServers": "not a dict"}
        result = get_named_server(config, section_key="mcpServers", server_name="scholar")
        self.assertIsNone(result)

    def test_returns_none_for_none_section_value(self) -> None:
        config = {"mcpServers": None}
        result = get_named_server(config, section_key="mcpServers", server_name="scholar")
        self.assertIsNone(result)


class RemoveNamedServerTest(unittest.TestCase):
    def test_removes_existing_server(self) -> None:
        config = {"mcpServers": {"scholar": {"type": "stdio"}, "other": {"type": "other"}}}
        result, removed = remove_named_server(config, section_key="mcpServers", server_name="scholar")
        self.assertTrue(removed)
        self.assertNotIn("scholar", result["mcpServers"])
        self.assertIn("other", result["mcpServers"])

    def test_returns_false_for_missing_server(self) -> None:
        config = {"mcpServers": {"other": {"type": "other"}}}
        result, removed = remove_named_server(config, section_key="mcpServers", server_name="scholar")
        self.assertFalse(removed)
        self.assertIn("other", result["mcpServers"])

    def test_returns_false_for_missing_section(self) -> None:
        result, removed = remove_named_server({}, section_key="mcpServers", server_name="scholar")
        self.assertFalse(removed)

    def test_returns_false_for_non_dict_section(self) -> None:
        config = {"mcpServers": "not a dict"}
        result, removed = remove_named_server(config, section_key="mcpServers", server_name="scholar")
        self.assertFalse(removed)

    def test_does_not_mutate_original(self) -> None:
        config = {"mcpServers": {"scholar": {"type": "stdio"}}}
        original = json.loads(json.dumps(config))
        remove_named_server(config, section_key="mcpServers", server_name="scholar")
        self.assertEqual(config, original)

    def test_removes_last_server_leaves_empty_section(self) -> None:
        config = {"mcpServers": {"scholar": {"type": "stdio"}}}
        result, removed = remove_named_server(config, section_key="mcpServers", server_name="scholar")
        self.assertTrue(removed)
        self.assertEqual(result["mcpServers"], {})


class LoadJsonFileTest(unittest.TestCase):
    def test_valid_file(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"key": "value"}, f)
            f.flush()
            result = load_json_file(Path(f.name))
        self.assertEqual(result, {"key": "value"})
        Path(f.name).unlink()

    def test_missing_file_returns_empty(self) -> None:
        result = load_json_file(Path("/tmp/__nonexistent_scholar_test_99999__.json"))
        self.assertEqual(result, {})

    def test_invalid_json_raises_value_error(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("not json{{{")
            f.flush()
            with self.assertRaises(ValueError):
                load_json_file(Path(f.name))
        Path(f.name).unlink()

    def test_non_dict_raises_value_error(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump([1, 2, 3], f)
            f.flush()
            with self.assertRaises(ValueError):
                load_json_file(Path(f.name))
        Path(f.name).unlink()


class WriteJsonFileTest(unittest.TestCase):
    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep" / "nested" / "config.json"
            write_json_file(path, {"a": 1})
            self.assertTrue(path.exists())

    def test_writes_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.json"
            write_json_file(path, {"key": "value"})
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded, {"key": "value"})

    def test_unicode_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.json"
            write_json_file(path, {"text": "中文测试"})
            content = path.read_text(encoding="utf-8")
            self.assertIn("中文测试", content)

    def test_overwrites_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.json"
            write_json_file(path, {"v": 1})
            write_json_file(path, {"v": 2})
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["v"], 2)


if __name__ == "__main__":
    unittest.main()
