"""Tests for scholar_agent.config.manager — initialize_user_home and migrate_to_user_home."""

import json
import tempfile
import unittest
from pathlib import Path

from scholar_agent.config.manager import initialize_user_home, migrate_to_user_home


class TestInitializeUserHome(unittest.TestCase):
    """Tests for initialize_user_home."""

    def test_creates_directories(self) -> None:
        """initialize_user_home creates all expected directories."""
        with tempfile.TemporaryDirectory() as tmp:
            env = {"SCHOLAR_HOME": tmp}
            result = initialize_user_home(env=env, write_config=False)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["config_written"], False)

            home = Path(tmp)
            expected_dirs = [
                home,
                home / "config",
                home / "config" / "profiles",
                home / "knowledge",
                home / "paper-notes",
                home / "daily-notes",
                home / "indexes" / "local",
                home / "cache",
                home / "logs",
                home / "outputs",
            ]
            for d in expected_dirs:
                self.assertTrue(d.exists(), f"Expected directory {d} to exist")
                self.assertTrue(d.is_dir(), f"Expected {d} to be a directory")

    def test_creates_config_file_by_default(self) -> None:
        """With write_config=True (default), a config file is written."""
        with tempfile.TemporaryDirectory() as tmp:
            env = {"SCHOLAR_HOME": tmp}
            result = initialize_user_home(env=env)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["config_written"], True)

            config_path = Path(tmp) / "config" / "config.json"
            self.assertTrue(config_path.exists())

            config_data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("knowledge_dir", config_data)
            self.assertIn("index_path", config_data)
            self.assertIn("profile", config_data)
            self.assertIn("academic", config_data)

    def test_skips_config_when_write_config_false(self) -> None:
        """With write_config=False, no config file is created."""
        with tempfile.TemporaryDirectory() as tmp:
            env = {"SCHOLAR_HOME": tmp}
            result = initialize_user_home(env=env, write_config=False)

            self.assertEqual(result["config_written"], False)
            config_path = Path(tmp) / "config" / "config.json"
            self.assertFalse(config_path.exists())

    def test_skips_existing_config_without_force(self) -> None:
        """When config already exists and force=False, config is NOT overwritten."""
        with tempfile.TemporaryDirectory() as tmp:
            env = {"SCHOLAR_HOME": tmp}
            config_path = Path(tmp) / "config" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            original_content = '{"original": true}'
            config_path.write_text(original_content, encoding="utf-8")

            result = initialize_user_home(env=env, force=False, write_config=True)

            self.assertEqual(result["config_written"], False)
            self.assertEqual(config_path.read_text(encoding="utf-8"), original_content)

    def test_overwrites_with_force(self) -> None:
        """When force=True, existing config is overwritten."""
        with tempfile.TemporaryDirectory() as tmp:
            env = {"SCHOLAR_HOME": tmp}
            config_path = Path(tmp) / "config" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text('{"original": true}', encoding="utf-8")

            result = initialize_user_home(env=env, force=True, write_config=True)

            self.assertEqual(result["config_written"], True)
            content = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("knowledge_dir", content)
            self.assertNotIn("original", content)

    def test_directories_created_list(self) -> None:
        """Result includes list of all created directories."""
        with tempfile.TemporaryDirectory() as tmp:
            env = {"SCHOLAR_HOME": tmp}
            result = initialize_user_home(env=env, write_config=False)

            dirs = result["directories_created"]
            self.assertIsInstance(dirs, list)
            self.assertGreater(len(dirs), 5)
            # All entries should be strings
            for d in dirs:
                self.assertIsInstance(d, str)

    def test_user_config_path_in_result(self) -> None:
        """Result includes user_home and user_config_path."""
        with tempfile.TemporaryDirectory() as tmp:
            env = {"SCHOLAR_HOME": tmp}
            result = initialize_user_home(env=env, write_config=False)

            self.assertEqual(result["user_home"], str(Path(tmp).resolve()))
            expected_config = str(Path(tmp).resolve() / "config" / "config.json")
            self.assertEqual(result["user_config_path"], expected_config)

    def test_existing_directories_not_recreated(self) -> None:
        """Calling initialize_user_home twice on the same dir is safe (idempotent)."""
        with tempfile.TemporaryDirectory() as tmp:
            env = {"SCHOLAR_HOME": tmp}
            result1 = initialize_user_home(env=env, write_config=False)
            result2 = initialize_user_home(env=env, write_config=False)

            self.assertEqual(result1["status"], "ok")
            self.assertEqual(result2["status"], "ok")


class TestMigrateToUserHome(unittest.TestCase):
    """Tests for migrate_to_user_home."""

    def test_migrates_from_cwd_config(self) -> None:
        """Migrate copies config from a .scholar.json in cwd to user home."""
        with tempfile.TemporaryDirectory() as tmp_cwd, tempfile.TemporaryDirectory() as tmp_home:
            env = {"SCHOLAR_HOME": tmp_home}

            # Create a .scholar.json in the cwd
            source_config = {"knowledge_dir": "/tmp/knowledge", "custom_key": "value"}
            config_file = Path(tmp_cwd) / ".scholar.json"
            config_file.write_text(json.dumps(source_config), encoding="utf-8")

            result = migrate_to_user_home(
                cwd=Path(tmp_cwd),
                env=env,
                scholar_root=Path(tmp_cwd),
            )

            self.assertIn(result["status"], ("ok", "planned"))
            target_config = Path(tmp_home) / "config" / "config.json"
            self.assertTrue(target_config.exists())

            migrated = json.loads(target_config.read_text(encoding="utf-8"))
            self.assertEqual(migrated["custom_key"], "value")

    def test_dry_run_does_not_write(self) -> None:
        """With dry_run=True, no config file is written."""
        with tempfile.TemporaryDirectory() as tmp_cwd, tempfile.TemporaryDirectory() as tmp_home:
            env = {"SCHOLAR_HOME": tmp_home}

            source_config = {"knowledge_dir": "/tmp/knowledge"}
            config_file = Path(tmp_cwd) / ".scholar.json"
            config_file.write_text(json.dumps(source_config), encoding="utf-8")

            result = migrate_to_user_home(
                dry_run=True,
                cwd=Path(tmp_cwd),
                env=env,
                scholar_root=Path(tmp_cwd),
            )

            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["dry_run"], True)
            target_config = Path(tmp_home) / "config" / "config.json"
            self.assertFalse(target_config.exists())

    def test_skips_when_target_exists_without_force(self) -> None:
        """If target config exists and force=False, migration is blocked."""
        with tempfile.TemporaryDirectory() as tmp_cwd, tempfile.TemporaryDirectory() as tmp_home:
            env = {"SCHOLAR_HOME": tmp_home}

            # Source config
            config_file = Path(tmp_cwd) / ".scholar.json"
            config_file.write_text(json.dumps({"key": "val"}), encoding="utf-8")

            # Target config already exists
            target_config = Path(tmp_home) / "config" / "config.json"
            target_config.parent.mkdir(parents=True, exist_ok=True)
            target_config.write_text('{"existing": true}', encoding="utf-8")

            result = migrate_to_user_home(
                force=False,
                cwd=Path(tmp_cwd),
                env=env,
                scholar_root=Path(tmp_cwd),
            )

            self.assertEqual(result["status"], "blocked")
            self.assertIn("already exists", result["reason"])

    def test_force_overwrites_existing(self) -> None:
        """With force=True, existing target config is overwritten."""
        with tempfile.TemporaryDirectory() as tmp_cwd, tempfile.TemporaryDirectory() as tmp_home:
            env = {"SCHOLAR_HOME": tmp_home}

            # Source config
            source_config = {"knowledge_dir": "/new/path", "new_key": "new_val"}
            config_file = Path(tmp_cwd) / ".scholar.json"
            config_file.write_text(json.dumps(source_config), encoding="utf-8")

            # Target config already exists
            target_config = Path(tmp_home) / "config" / "config.json"
            target_config.parent.mkdir(parents=True, exist_ok=True)
            target_config.write_text('{"old_key": "old_val"}', encoding="utf-8")

            result = migrate_to_user_home(
                force=True,
                cwd=Path(tmp_cwd),
                env=env,
                scholar_root=Path(tmp_cwd),
            )

            self.assertEqual(result["status"], "ok")
            migrated = json.loads(target_config.read_text(encoding="utf-8"))
            self.assertEqual(migrated["new_key"], "new_val")

    def test_noop_when_same_config(self) -> None:
        """No-op when resolved config is already the target config file."""
        with tempfile.TemporaryDirectory() as tmp_home:
            env = {"SCHOLAR_HOME": tmp_home}

            # Create the user config that will be both source and target
            target_config = Path(tmp_home) / "config" / "config.json"
            target_config.parent.mkdir(parents=True, exist_ok=True)
            target_config.write_text('{"already": "here"}', encoding="utf-8")

            # cwd = tmp_home so workspace walk-up finds the same config
            result = migrate_to_user_home(
                cwd=Path(tmp_home),
                env=env,
                scholar_root=Path(tmp_home),
            )

            self.assertEqual(result["status"], "noop")

    def test_creates_directories_during_migration(self) -> None:
        """Migration creates user home directories as a side-effect."""
        with tempfile.TemporaryDirectory() as tmp_cwd, tempfile.TemporaryDirectory() as tmp_home:
            env = {"SCHOLAR_HOME": tmp_home}

            config_file = Path(tmp_cwd) / ".scholar.json"
            config_file.write_text(json.dumps({"key": "val"}), encoding="utf-8")

            migrate_to_user_home(
                cwd=Path(tmp_cwd),
                env=env,
                scholar_root=Path(tmp_cwd),
            )

            # Check that standard directories were created
            self.assertTrue((Path(tmp_home) / "knowledge").exists())
            self.assertTrue((Path(tmp_home) / "cache").exists())
            self.assertTrue((Path(tmp_home) / "logs").exists())

    def test_result_includes_source_info(self) -> None:
        """Result includes source_mode and source_config_file."""
        with tempfile.TemporaryDirectory() as tmp_cwd, tempfile.TemporaryDirectory() as tmp_home:
            env = {"SCHOLAR_HOME": tmp_home}

            config_file = Path(tmp_cwd) / ".scholar.json"
            config_file.write_text(json.dumps({"key": "val"}), encoding="utf-8")

            result = migrate_to_user_home(
                cwd=Path(tmp_cwd),
                env=env,
                scholar_root=Path(tmp_cwd),
            )

            self.assertIn("source_mode", result)
            self.assertIn("source_config_file", result)
            self.assertIn("target_config_file", result)

    def test_migrate_without_any_source_config(self) -> None:
        """When there's no source config at all, migration still produces a result."""
        with tempfile.TemporaryDirectory() as tmp_cwd, tempfile.TemporaryDirectory() as tmp_home:
            env = {"SCHOLAR_HOME": tmp_home}

            result = migrate_to_user_home(
                cwd=Path(tmp_cwd),
                env=env,
                scholar_root=Path(tmp_cwd),
            )

            # Should succeed using defaults
            self.assertIn(result["status"], ("ok", "planned", "blocked", "noop"))
            self.assertIn("directories_created", result)


if __name__ == "__main__":
    unittest.main()
