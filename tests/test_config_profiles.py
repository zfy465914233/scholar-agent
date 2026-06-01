"""Tests for scholar_agent.config.profiles module."""

import os
import unittest

from scholar_agent.config.profiles import get_active_profile


class GetActiveProfileEnvPriorityTest(unittest.TestCase):
    """SCHOLAR_PROFILE env var takes highest priority."""

    def test_env_overrides_config(self) -> None:
        result = get_active_profile(config={"profile": "from-config"}, env={"SCHOLAR_PROFILE": "from-env"})
        self.assertEqual(result, "from-env")

    def test_env_overrides_even_if_config_set(self) -> None:
        result = get_active_profile(config={"profile": "research"}, env={"SCHOLAR_PROFILE": "production"})
        self.assertEqual(result, "production")


class GetActiveProfileConfigTest(unittest.TestCase):
    """When no env var, fall back to config['profile']."""

    def test_config_profile_used_when_no_env(self) -> None:
        result = get_active_profile(config={"profile": "research"}, env={})
        self.assertEqual(result, "research")

    def test_config_profile_stripped(self) -> None:
        result = get_active_profile(config={"profile": "  research  "}, env={})
        self.assertEqual(result, "research")

    def test_config_profile_empty_string_falls_back(self) -> None:
        result = get_active_profile(config={"profile": ""}, env={})
        self.assertEqual(result, "default")

    def test_config_profile_whitespace_only_falls_back(self) -> None:
        result = get_active_profile(config={"profile": "   "}, env={})
        self.assertEqual(result, "default")

    def test_config_profile_non_string_ignored(self) -> None:
        result = get_active_profile(config={"profile": 123}, env={})
        self.assertEqual(result, "default")

    def test_config_without_profile_key(self) -> None:
        result = get_active_profile(config={"other_key": "value"}, env={})
        self.assertEqual(result, "default")


class GetActiveProfileDefaultTest(unittest.TestCase):
    """When neither env nor config provides a profile, return 'default'."""

    def test_no_env_no_config(self) -> None:
        result = get_active_profile(config=None, env={})
        self.assertEqual(result, "default")

    def test_empty_everything(self) -> None:
        result = get_active_profile(config={}, env={})
        self.assertEqual(result, "default")


class GetActiveProfileNoneHandlingTest(unittest.TestCase):
    """None arguments should fall back to os.environ gracefully."""

    def test_config_none_env_none(self) -> None:
        # env=None falls back to os.environ; config=None is skipped
        result = get_active_profile(config=None, env=None)
        self.assertIsInstance(result, str)

    def test_config_none_env_empty(self) -> None:
        result = get_active_profile(config=None, env={})
        self.assertEqual(result, "default")


class GetActiveProfileEdgeCasesTest(unittest.TestCase):
    def test_env_var_with_leading_trailing_whitespace(self) -> None:
        result = get_active_profile(env={"SCHOLAR_PROFILE": "  my-profile  "})
        self.assertEqual(result, "my-profile")

    def test_env_var_whitespace_only_falls_back(self) -> None:
        result = get_active_profile(env={"SCHOLAR_PROFILE": "   "})
        # Empty after strip, falls back to config then default
        self.assertEqual(result, "default")

    def test_env_var_empty_string_falls_back(self) -> None:
        result = get_active_profile(env={"SCHOLAR_PROFILE": ""})
        self.assertEqual(result, "default")

    def test_config_and_env_both_empty(self) -> None:
        result = get_active_profile(config={"profile": ""}, env={"SCHOLAR_PROFILE": ""})
        self.assertEqual(result, "default")

    def test_profile_with_hyphens_and_underscores(self) -> None:
        result = get_active_profile(env={"SCHOLAR_PROFILE": "my_custom-profile"})
        self.assertEqual(result, "my_custom-profile")

    def test_profile_with_digits(self) -> None:
        result = get_active_profile(env={"SCHOLAR_PROFILE": "profile123"})
        self.assertEqual(result, "profile123")


if __name__ == "__main__":
    unittest.main()
