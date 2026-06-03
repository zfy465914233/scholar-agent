"""Tests for scholar_agent.config.paths module."""

import unittest
from pathlib import Path

from scholar_agent.config.paths import (
    APP_NAME,
    build_default_config,
    get_scholar_root,
    get_user_config_path,
    get_user_home,
    get_user_profile_path,
)


class GetScholarRootTest(unittest.TestCase):
    def test_returns_path(self) -> None:
        root = get_scholar_root()
        self.assertIsInstance(root, Path)

    def test_resolved_is_absolute(self) -> None:
        root = get_scholar_root().resolve()
        self.assertTrue(root.is_absolute())

    def test_contains_pyproject_toml(self) -> None:
        root = get_scholar_root()
        self.assertTrue((root / "pyproject.toml").exists(), f"pyproject.toml not found at {root}")


class GetUserHomeTest(unittest.TestCase):
    def test_default_is_home_scholar(self) -> None:
        result = get_user_home(env={})
        expected = (Path.home() / ".scholar").resolve()
        self.assertEqual(result, expected)

    def test_override_via_env(self) -> None:
        custom = "/tmp/my-scholar-home"
        result = get_user_home(env={"SCHOLAR_HOME": custom})
        self.assertEqual(result, Path(custom).resolve())

    def test_override_with_tilde(self) -> None:
        result = get_user_home(env={"SCHOLAR_HOME": "~/custom-scholar"})
        self.assertEqual(result, Path("~/custom-scholar").expanduser().resolve())

    def test_none_env_uses_os_environ(self) -> None:
        # Calling with env=None should not crash; it falls back to os.environ
        result = get_user_home(env=None)
        self.assertIsInstance(result, Path)

    def test_empty_string_env_uses_default(self) -> None:
        result = get_user_home(env={"SCHOLAR_HOME": ""})
        expected = (Path.home() / ".scholar").resolve()
        self.assertEqual(result, expected)

    def test_whitespace_only_env_uses_default(self) -> None:
        result = get_user_home(env={"SCHOLAR_HOME": "   "})
        expected = (Path.home() / ".scholar").resolve()
        self.assertEqual(result, expected)

    def test_returns_resolved_path(self) -> None:
        result = get_user_home(env={})
        self.assertEqual(result, result.resolve())


class GetUserConfigPathTest(unittest.TestCase):
    def test_default_location(self) -> None:
        result = get_user_config_path(env={})
        expected = (Path.home() / ".scholar" / "config" / "config.json").resolve()
        self.assertEqual(result, expected)

    def test_respects_scholar_home(self) -> None:
        result = get_user_config_path(env={"SCHOLAR_HOME": "/opt/scholar"})
        expected = Path("/opt/scholar/config/config.json").resolve()
        self.assertEqual(result, expected)

    def test_is_under_user_home(self) -> None:
        home = get_user_home(env={})
        config_path = get_user_config_path(env={})
        self.assertTrue(str(config_path).startswith(str(home)))


class GetUserProfilePathTest(unittest.TestCase):
    def test_default_profile_path(self) -> None:
        result = get_user_profile_path("research", env={})
        expected = (Path.home() / ".scholar" / "config" / "profiles" / "research.json").resolve()
        self.assertEqual(result, expected)

    def test_respects_scholar_home(self) -> None:
        result = get_user_profile_path("default", env={"SCHOLAR_HOME": "/data/scholar"})
        expected = Path("/data/scholar/config/profiles/default.json").resolve()
        self.assertEqual(result, expected)

    def test_profile_name_in_filename(self) -> None:
        result = get_user_profile_path("my-profile", env={"SCHOLAR_HOME": "/tmp/s"})
        self.assertTrue(result.name == "my-profile.json")


class BuildDefaultConfigTest(unittest.TestCase):
    def test_returns_dict(self) -> None:
        config = build_default_config(env={})
        self.assertIsInstance(config, dict)

    def test_has_required_top_level_keys(self) -> None:
        config = build_default_config(env={})
        for key in ("knowledge_dir", "index_path", "scholar_dir", "profile", "academic"):
            self.assertIn(key, config, f"Missing key: {key}")

    def test_default_profile_is_default(self) -> None:
        config = build_default_config(env={})
        self.assertEqual(config["profile"], "default")

    def test_profile_from_env(self) -> None:
        config = build_default_config(env={"SCHOLAR_PROFILE": "research"})
        self.assertEqual(config["profile"], "research")

    def test_empty_profile_env_falls_back(self) -> None:
        config = build_default_config(env={"SCHOLAR_PROFILE": "  "})
        self.assertEqual(config["profile"], "default")

    def test_custom_scholar_root(self) -> None:
        custom_root = Path("/tmp/custom-root")
        config = build_default_config(env={}, scholar_root=custom_root)
        self.assertEqual(config["scholar_dir"], str(custom_root.resolve()))

    def test_knowledge_dir_under_user_home(self) -> None:
        env = {"SCHOLAR_HOME": "/tmp/test-home"}
        config = build_default_config(env=env)
        self.assertTrue(config["knowledge_dir"].startswith(str(Path("/tmp/test-home").resolve())))

    def test_academic_section_structure(self) -> None:
        config = build_default_config(env={})
        academic = config["academic"]
        self.assertIn("paper_notes_dir", academic)
        self.assertIn("daily_notes_dir", academic)
        self.assertIn("search", academic)
        self.assertIn("scoring", academic)
        self.assertIn("research_interests", academic)

    def test_search_sources(self) -> None:
        config = build_default_config(env={})
        sources = config["academic"]["search"]["sources"]
        self.assertIn("arxiv", sources)
        self.assertIn("semantic_scholar", sources)

    def test_default_conferences_populated(self) -> None:
        config = build_default_config(env={})
        conferences = config["academic"]["search"]["default_conferences"]
        self.assertIn("NeurIPS", conferences)
        self.assertIn("ICML", conferences)
        self.assertTrue(len(conferences) >= 5)

    def test_none_env_uses_os_environ(self) -> None:
        # Should not crash when env=None (falls back to os.environ)
        config = build_default_config(env=None)
        self.assertIsInstance(config, dict)

    def test_none_scholar_root_uses_detected_root(self) -> None:
        config = build_default_config(env={}, scholar_root=None)
        self.assertEqual(config["scholar_dir"], str(get_scholar_root().resolve()))


class ConstantsTest(unittest.TestCase):
    def test_app_name(self) -> None:
        self.assertEqual(APP_NAME, "scholar-agent")


if __name__ == "__main__":
    unittest.main()
