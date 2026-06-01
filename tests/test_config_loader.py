"""Tests for scholar_agent.config.loader module."""

import json
import tempfile
import unittest
from pathlib import Path

from scholar_agent.config.loader import (
    _deep_merge,
    _find_workspace_config,
    _load_json,
    resolve_config,
)


class DeepMergeTest(unittest.TestCase):
    def test_flat_merge(self) -> None:
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        self.assertEqual(result, {"a": 1, "b": 3, "c": 4})

    def test_nested_merge(self) -> None:
        base = {"outer": {"a": 1, "b": 2}}
        override = {"outer": {"b": 3, "c": 4}}
        result = _deep_merge(base, override)
        self.assertEqual(result, {"outer": {"a": 1, "b": 3, "c": 4}})

    def test_does_not_mutate_base(self) -> None:
        base = {"a": 1, "nested": {"x": 10}}
        override = {"a": 2, "nested": {"y": 20}}
        original_base = {"a": 1, "nested": {"x": 10}}
        _deep_merge(base, override)
        self.assertEqual(base, original_base)

    def test_override_replaces_non_dict_with_dict(self) -> None:
        base = {"key": "string_value"}
        override = {"key": {"nested": True}}
        result = _deep_merge(base, override)
        self.assertEqual(result, {"key": {"nested": True}})

    def test_override_replaces_dict_with_non_dict(self) -> None:
        base = {"key": {"nested": True}}
        override = {"key": "string_value"}
        result = _deep_merge(base, override)
        self.assertEqual(result, {"key": "string_value"})

    def test_empty_override_returns_copy(self) -> None:
        base = {"a": 1}
        result = _deep_merge(base, {})
        self.assertEqual(result, base)
        self.assertIsNot(result, base)

    def test_empty_base(self) -> None:
        result = _deep_merge({}, {"a": 1})
        self.assertEqual(result, {"a": 1})

    def test_both_empty(self) -> None:
        result = _deep_merge({}, {})
        self.assertEqual(result, {})

    def test_deeply_nested(self) -> None:
        base = {"l1": {"l2": {"l3": {"val": "old"}}}}
        override = {"l1": {"l2": {"l3": {"val": "new", "extra": 1}}}}
        result = _deep_merge(base, override)
        self.assertEqual(result["l1"]["l2"]["l3"]["val"], "new")
        self.assertEqual(result["l1"]["l2"]["l3"]["extra"], 1)

    def test_override_with_list_value(self) -> None:
        base = {"key": [1, 2]}
        override = {"key": [3, 4]}
        result = _deep_merge(base, override)
        self.assertEqual(result["key"], [3, 4])

    def test_none_value_in_override(self) -> None:
        base = {"a": 1, "b": 2}
        override = {"a": None}
        result = _deep_merge(base, override)
        self.assertIsNone(result["a"])
        self.assertEqual(result["b"], 2)


class LoadJsonTest(unittest.TestCase):
    def test_valid_json_dict(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"key": "value"}, f)
            f.flush()
            result = _load_json(Path(f.name))
        self.assertEqual(result, {"key": "value"})
        Path(f.name).unlink()

    def test_non_dict_json_returns_none(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump([1, 2, 3], f)
            f.flush()
            result = _load_json(Path(f.name))
        self.assertIsNone(result)
        Path(f.name).unlink()

    def test_json_string_returns_none(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump("just a string", f)
            f.flush()
            result = _load_json(Path(f.name))
        self.assertIsNone(result)
        Path(f.name).unlink()

    def test_invalid_json_returns_none(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            f.flush()
            result = _load_json(Path(f.name))
        self.assertIsNone(result)
        Path(f.name).unlink()

    def test_missing_file_returns_none(self) -> None:
        result = _load_json(Path("/tmp/__nonexistent_scholar_test_12345__.json"))
        self.assertIsNone(result)

    def test_empty_dict(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({}, f)
            f.flush()
            result = _load_json(Path(f.name))
        self.assertEqual(result, {})
        Path(f.name).unlink()

    def test_nested_json(self) -> None:
        data = {"level1": {"level2": [1, 2, 3], "key": "val"}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            result = _load_json(Path(f.name))
        self.assertEqual(result, data)
        Path(f.name).unlink()

    def test_json_number_returns_none(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(42, f)
            f.flush()
            result = _load_json(Path(f.name))
        self.assertIsNone(result)
        Path(f.name).unlink()

    def test_json_null_returns_none(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(None, f)
            f.flush()
            result = _load_json(Path(f.name))
        self.assertIsNone(result)
        Path(f.name).unlink()


class FindWorkspaceConfigTest(unittest.TestCase):
    def test_finds_in_current_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / ".scholar.json"
            config_file.write_text("{}", encoding="utf-8")
            result = _find_workspace_config(Path(tmp))
            self.assertIsNotNone(result)
            self.assertEqual(result, config_file.resolve())

    def test_finds_in_parent_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / ".scholar.json"
            config_file.write_text("{}", encoding="utf-8")
            child = Path(tmp) / "subdir"
            child.mkdir()
            result = _find_workspace_config(child)
            self.assertIsNotNone(result)
            self.assertEqual(result, config_file.resolve())

    def test_finds_in_grandparent_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / ".scholar.json"
            config_file.write_text("{}", encoding="utf-8")
            grandchild = Path(tmp) / "a" / "b"
            grandchild.mkdir(parents=True)
            result = _find_workspace_config(grandchild)
            self.assertIsNotNone(result)
            self.assertEqual(result, config_file.resolve())

    def test_returns_none_when_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _find_workspace_config(Path(tmp))
            self.assertIsNone(result)

    def test_stops_at_filesystem_root(self) -> None:
        # Walks up at most 10 levels, won't infinite loop
        with tempfile.TemporaryDirectory() as tmp:
            # Create a deep path but no .scholar.json anywhere
            deep = Path(tmp)
            for i in range(15):
                deep = deep / f"level{i}"
            deep.mkdir(parents=True, exist_ok=True)
            result = _find_workspace_config(deep)
            # Should either find nothing or stop after 10 levels
            # Either way, it must not crash or infinite loop
            self.assertIsInstance(result, (Path, type(None)))

    def test_prefers_closest_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent_config = Path(tmp) / ".scholar.json"
            parent_config.write_text('{"level": "parent"}', encoding="utf-8")
            child_dir = Path(tmp) / "child"
            child_dir.mkdir()
            child_config = child_dir / ".scholar.json"
            child_config.write_text('{"level": "child"}', encoding="utf-8")
            grandchild = child_dir / "grandchild"
            grandchild.mkdir()
            result = _find_workspace_config(grandchild)
            self.assertIsNotNone(result)
            self.assertEqual(result, child_config.resolve())


class ResolveConfigTest(unittest.TestCase):
    """All tests set SCHOLAR_HOME to an isolated tmpdir so the real
    ~/scholar/config/config.json (if present on the developer's machine)
    does not leak into test results."""

    def _make_env(self, tmp_path: Path, **extra: str) -> dict[str, str]:
        env: dict[str, str] = {"SCHOLAR_HOME": str(tmp_path)}
        env.update(extra)
        return env

    def test_default_mode_with_no_config_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env = self._make_env(tmp_path)
            result = resolve_config(cwd=tmp_path, env=env, scholar_root=tmp_path)
            self.assertEqual(result.mode, "user-default")
            self.assertIsNone(result.config_file)
            self.assertIsInstance(result.config, dict)

    def test_config_has_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env = self._make_env(tmp_path)
            result = resolve_config(cwd=tmp_path, env=env, scholar_root=tmp_path)
            config = result.config
            for key in ("knowledge_dir", "index_path", "scholar_dir", "profile", "academic"):
                self.assertIn(key, config, f"Missing key: {key}")

    def test_user_config_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_dir = tmp_path / "config"
            config_dir.mkdir()
            user_config = config_dir / "config.json"
            user_config.write_text(json.dumps({"profile": "custom-user"}), encoding="utf-8")
            env = self._make_env(tmp_path)
            result = resolve_config(cwd=tmp_path, env=env, scholar_root=tmp_path)
            self.assertEqual(result.mode, "user-config")
            self.assertIsNotNone(result.config_file)
            self.assertEqual(result.config["profile"], "custom-user")

    def test_workspace_config_mode(self) -> None:
        # When cwd != scholar_root, .scholar.json in cwd is "workspace" mode
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ws_dir = tmp_path / "workspace"
            ws_dir.mkdir()
            root_dir = tmp_path / "scholar-root"
            root_dir.mkdir()
            ws_config = ws_dir / ".scholar.json"
            ws_config.write_text(json.dumps({"profile": "workspace-test"}), encoding="utf-8")
            env = self._make_env(tmp_path)
            result = resolve_config(cwd=ws_dir, env=env, scholar_root=root_dir)
            self.assertEqual(result.mode, "workspace")
            self.assertEqual(result.config["profile"], "workspace-test")

    def test_repo_embedded_config_mode(self) -> None:
        # When cwd == scholar_root, .scholar.json is "repo-embedded" mode
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ws_config = tmp_path / ".scholar.json"
            ws_config.write_text(json.dumps({"profile": "repo-test"}), encoding="utf-8")
            env = self._make_env(tmp_path)
            result = resolve_config(cwd=tmp_path, env=env, scholar_root=tmp_path)
            self.assertEqual(result.mode, "repo-embedded")
            self.assertEqual(result.config["profile"], "repo-test")

    def test_runtime_config_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rt_config = tmp_path / "runtime.json"
            rt_config.write_text(json.dumps({"profile": "runtime-test"}), encoding="utf-8")
            env = self._make_env(tmp_path, SCHOLAR_CONFIG=str(rt_config))
            result = resolve_config(cwd=tmp_path, env=env, scholar_root=tmp_path)
            self.assertEqual(result.mode, "runtime-config")
            self.assertEqual(result.config["profile"], "runtime-test")

    def test_runtime_config_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rt_config = tmp_path / "my-config.json"
            rt_config.write_text(json.dumps({"profile": "relative-test"}), encoding="utf-8")
            env = self._make_env(tmp_path, SCHOLAR_CONFIG="my-config.json")
            result = resolve_config(cwd=tmp_path, env=env, scholar_root=tmp_path)
            self.assertEqual(result.mode, "runtime-config")
            self.assertEqual(result.config["profile"], "relative-test")

    def test_runtime_config_missing_file_stays_at_previous_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env = self._make_env(tmp_path, SCHOLAR_CONFIG=str(tmp_path / "nonexistent.json"))
            result = resolve_config(cwd=tmp_path, env=env, scholar_root=tmp_path)
            # Should stay at user-default since no other config found
            self.assertEqual(result.mode, "user-default")

    def test_scholar_dir_set_from_scholar_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root_dir = tmp_path / "my-root"
            root_dir.mkdir()
            env = self._make_env(tmp_path)
            result = resolve_config(cwd=tmp_path, env=env, scholar_root=root_dir)
            self.assertEqual(result.config["scholar_dir"], str(root_dir.resolve()))

    def test_workspace_config_merges_into_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ws_dir = tmp_path / "workspace"
            ws_dir.mkdir()
            root_dir = tmp_path / "scholar-root"
            root_dir.mkdir()
            ws_config = ws_dir / ".scholar.json"
            ws_config.write_text(
                json.dumps({"academic": {"search": {"max_results": 50}}}),
                encoding="utf-8",
            )
            env = self._make_env(tmp_path)
            result = resolve_config(cwd=ws_dir, env=env, scholar_root=root_dir)
            self.assertEqual(result.config["academic"]["search"]["max_results"], 50)
            # Other defaults should still be present
            self.assertIn("sources", result.config["academic"]["search"])

    def test_returns_config_resolution(self) -> None:
        from scholar_agent.config.loader import ConfigResolution

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env = self._make_env(tmp_path)
            result = resolve_config(cwd=tmp_path, env=env, scholar_root=tmp_path)
            self.assertIsInstance(result, ConfigResolution)

    def test_profile_from_env_in_final_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env = self._make_env(tmp_path, SCHOLAR_PROFILE="test-profile")
            result = resolve_config(cwd=tmp_path, env=env, scholar_root=tmp_path)
            self.assertEqual(result.config["profile"], "test-profile")

    def test_none_cwd_uses_path_cwd(self) -> None:
        # Should not crash when cwd=None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env = self._make_env(tmp_path)
            result = resolve_config(cwd=None, env=env, scholar_root=tmp_path)
            self.assertIsInstance(result.config, dict)


if __name__ == "__main__":
    unittest.main()
