"""Tests for scholar_agent.runtime pure functions."""

import os
import unittest
from pathlib import Path

from scholar_agent.runtime import (
    _build_pipx_install_plan,
    _default_pipx_bin_dir,
    _default_pipx_home,
    _detect_install_manager,
    _file_url_to_path,
    _is_relative_to,
    _path_contains,
    _resolve_output_dir,
)


class TestDefaultPipxBinDir(unittest.TestCase):
    """Tests for _default_pipx_bin_dir(env)."""

    def test_linux_default(self):
        result = _default_pipx_bin_dir({})
        self.assertEqual(result.resolve(), (Path.home() / ".local" / "bin").resolve())

    def test_env_override(self):
        result = _default_pipx_bin_dir({"PIPX_BIN_DIR": "/custom/bin"})
        self.assertEqual(Path(result), Path("/custom/bin").resolve())

    def test_env_override_expands_user(self):
        result = _default_pipx_bin_dir({"PIPX_BIN_DIR": "~/my-bin"})
        self.assertTrue(str(result).endswith("my-bin"))
        self.assertNotIn("~", str(result))

    @unittest.skipIf(os.name != "nt", "Windows-only test")
    def test_windows_with_localappdata(self):
        """On Windows with LOCALAPPDATA set, should use that path."""
        result = _default_pipx_bin_dir({"LOCALAPPDATA": "C:\\Users\\test\\AppData\\Local"})
        self.assertEqual(result, Path("C:\\Users\\test\\AppData\\Local") / "pipx" / "bin")

    @unittest.skipIf(os.name != "nt", "Windows-only test")
    def test_windows_without_localappdata(self):
        """On Windows without LOCALAPPDATA, falls back to ~/.local/bin."""
        result = _default_pipx_bin_dir({})
        self.assertEqual(result, Path.home() / ".local" / "bin")

    def test_strips_whitespace_from_env(self):
        result = _default_pipx_bin_dir({"PIPX_BIN_DIR": "  /trimmed  "})
        self.assertEqual(Path(result), Path("/trimmed").resolve())

    def test_none_env_uses_os_environ(self):
        # Should not raise; delegates to os.environ
        result = _default_pipx_bin_dir(None)
        self.assertIsInstance(result, Path)

    def test_empty_override_falls_back(self):
        result = _default_pipx_bin_dir({"PIPX_BIN_DIR": "  "})
        self.assertEqual(result.resolve(), (Path.home() / ".local" / "bin").resolve())


class TestDefaultPipxHome(unittest.TestCase):
    """Tests for _default_pipx_home(env)."""

    def test_linux_default(self):
        result = _default_pipx_home({})
        self.assertEqual(result.resolve(), (Path.home() / ".local" / "pipx").resolve())

    def test_env_override(self):
        result = _default_pipx_home({"PIPX_HOME": "/custom/pipx"})
        self.assertEqual(Path(result), Path("/custom/pipx").resolve())

    def test_env_override_expands_user(self):
        result = _default_pipx_home({"PIPX_HOME": "~/pipx-home"})
        self.assertTrue(str(result).endswith("pipx-home"))
        self.assertNotIn("~", str(result))

    @unittest.skipIf(os.name != "nt", "Windows-only test")
    def test_windows_with_localappdata(self):
        """On Windows with LOCALAPPDATA set, should use that path."""
        result = _default_pipx_home({"LOCALAPPDATA": "C:\\Users\\test\\AppData\\Local"})
        self.assertEqual(result, Path("C:\\Users\\test\\AppData\\Local") / "pipx")

    @unittest.skipIf(os.name != "nt", "Windows-only test")
    def test_windows_without_localappdata(self):
        """On Windows without LOCALAPPDATA, falls back to ~/.local/pipx."""
        result = _default_pipx_home({})
        self.assertEqual(result, Path.home() / ".local" / "pipx")

    def test_empty_override_falls_back(self):
        result = _default_pipx_home({"PIPX_HOME": ""})
        self.assertEqual(result.resolve(), (Path.home() / ".local" / "pipx").resolve())


class TestBuildPipxInstallPlan(unittest.TestCase):
    """Tests for _build_pipx_install_plan(pipx_command_prefix, resolved_python, resolved_wheel, force)."""

    def test_fresh_install(self):
        uninstall, install, mode = _build_pipx_install_plan(
            pipx_command_prefix=["pipx"],
            resolved_python="/usr/bin/python3",
            resolved_wheel=Path("/tmp/pkg.whl"),
            force=False,
        )
        self.assertIsNone(uninstall)
        self.assertEqual(mode, "install")
        self.assertIn("pipx", install)
        self.assertIn("install", install)
        self.assertIn("/usr/bin/python3", install)
        self.assertIn(str(Path("/tmp/pkg.whl")), install)

    def test_force_install_not_yet_installed(self):
        """When force=True but package is not installed, should use --force flag."""
        uninstall, install, mode = _build_pipx_install_plan(
            pipx_command_prefix=["pipx"],
            resolved_python="/usr/bin/python3",
            resolved_wheel=Path("/tmp/pkg.whl"),
            force=True,
        )
        self.assertIsNone(uninstall)
        self.assertEqual(mode, "install")
        self.assertIn("--force", install)

    def test_install_command_includes_wheel(self):
        _, install, _ = _build_pipx_install_plan(
            pipx_command_prefix=["/usr/local/bin/pipx"],
            resolved_python="/usr/bin/python3",
            resolved_wheel=Path("/wheels/scholar_agent-1.0.whl"),
            force=False,
        )
        self.assertIn(str(Path("/wheels/scholar_agent-1.0.whl")), install)

    def test_install_command_uses_custom_prefix(self):
        _, install, _ = _build_pipx_install_plan(
            pipx_command_prefix=["python", "-m", "pipx"],
            resolved_python="/usr/bin/python3",
            resolved_wheel=Path("/tmp/pkg.whl"),
            force=False,
        )
        self.assertEqual(install[:3], ["python", "-m", "pipx"])

    def test_install_command_includes_python_flag(self):
        _, install, _ = _build_pipx_install_plan(
            pipx_command_prefix=["pipx"],
            resolved_python="/opt/python3.12/bin/python3",
            resolved_wheel=Path("/tmp/pkg.whl"),
            force=False,
        )
        self.assertIn("--python", install)
        idx = install.index("--python")
        self.assertEqual(install[idx + 1], "/opt/python3.12/bin/python3")


class TestIsRelativeTo(unittest.TestCase):
    """Tests for _is_relative_to(path, parent)."""

    def test_child_path(self):
        self.assertTrue(_is_relative_to(Path("/a/b/c"), Path("/a/b")))

    def test_same_path(self):
        self.assertTrue(_is_relative_to(Path("/a/b"), Path("/a/b")))

    def test_unrelated_paths(self):
        self.assertFalse(_is_relative_to(Path("/x/y"), Path("/a/b")))

    def test_none_path(self):
        self.assertFalse(_is_relative_to(None, Path("/a")))

    def test_parent_is_not_relative_to_child(self):
        self.assertFalse(_is_relative_to(Path("/a"), Path("/a/b")))

    def test_nested_deep_path(self):
        self.assertTrue(_is_relative_to(Path("/a/b/c/d/e"), Path("/a/b/c")))


class TestPathContains(unittest.TestCase):
    """Tests for _path_contains(target, env)."""

    def test_target_in_path(self):
        env = {"PATH": f"/usr/bin{os.pathsep}/usr/local/bin"}
        self.assertTrue(_path_contains(Path("/usr/bin"), env))

    def test_target_not_in_path(self):
        env = {"PATH": f"/usr/bin{os.pathsep}/usr/local/bin"}
        self.assertFalse(_path_contains(Path("/opt/custom/bin"), env))

    def test_empty_path_env(self):
        env = {"PATH": ""}
        self.assertFalse(_path_contains(Path("/usr/bin"), env))

    def test_missing_path_key(self):
        env = {}
        self.assertFalse(_path_contains(Path("/usr/bin"), env))

    def test_expands_tilde(self):
        env = {"PATH": f"~/bin{os.pathsep}/usr/bin"}
        home_bin = Path.home() / "bin"
        self.assertTrue(_path_contains(home_bin, env))

    def test_multiple_entries(self):
        env = {"PATH": f"/a{os.pathsep}/b{os.pathsep}/c"}
        self.assertTrue(_path_contains(Path("/b"), env))
        self.assertFalse(_path_contains(Path("/d"), env))


class TestDetectInstallManager(unittest.TestCase):
    """Tests for _detect_install_manager(dist_info_path, package_root, python_executable, env)."""

    def test_detects_pipx_when_under_pipx_venvs(self):
        pipx_home = Path("/fake/home/.local/pipx").resolve()
        dist_info = (pipx_home / "venvs" / "scholar-agent" / "lib" / "site-packages" / "scholar_agent-1.0.dist-info").resolve()
        package_root = (pipx_home / "venvs" / "scholar-agent" / "lib" / "site-packages" / "scholar_agent").resolve()
        env = {
            "PIPX_HOME": str(pipx_home),
            "PIPX_BIN_DIR": str(pipx_home.parent / "bin"),
        }
        manager, is_pipx, _, _ = _detect_install_manager(
            dist_info_path=dist_info,
            package_root=package_root,
            python_executable=str(pipx_home / "venvs" / "scholar-agent" / "bin" / "python"),
            env=env,
        )
        self.assertEqual(manager, "pipx")
        self.assertTrue(is_pipx)

    def test_detects_direct_when_not_under_pipx(self):
        dist_info = Path("/usr/lib/python3.12/site-packages/scholar_agent-1.0.dist-info").resolve()
        package_root = Path("/usr/lib/python3.12/site-packages/scholar_agent").resolve()
        env = {
            "PIPX_HOME": str(Path("/fake/home/.local/pipx").resolve()),
            "PIPX_BIN_DIR": str(Path("/fake/home/.local/bin").resolve()),
        }
        manager, is_pipx, _, _ = _detect_install_manager(
            dist_info_path=dist_info,
            package_root=package_root,
            python_executable="/usr/bin/python3",
            env=env,
        )
        self.assertEqual(manager, "direct")
        self.assertFalse(is_pipx)

    def test_returns_pipx_home_and_bin_dir(self):
        dist_info = Path("/opt/python/lib/site-packages/pkg.dist-info").resolve()
        package_root = Path("/opt/python/lib/site-packages/pkg").resolve()
        env = {
            "PIPX_HOME": str(Path("/custom/pipx").resolve()),
            "PIPX_BIN_DIR": str(Path("/custom/bin").resolve()),
        }
        _, _, pipx_home, pipx_bin = _detect_install_manager(
            dist_info_path=dist_info,
            package_root=package_root,
            python_executable="/usr/bin/python3",
            env=env,
        )
        self.assertEqual(pipx_home, Path("/custom/pipx").resolve())
        self.assertEqual(pipx_bin, Path("/custom/bin").resolve())


class TestFileUrlToPath(unittest.TestCase):
    """Tests for _file_url_to_path(url)."""

    def test_unix_file_url(self):
        result = _file_url_to_path("file:///tmp/test.whl")
        self.assertIsNotNone(result)
        self.assertTrue(str(result).endswith("test.whl"))

    def test_non_file_url_returns_none(self):
        result = _file_url_to_path("https://example.com/test.whl")
        self.assertIsNone(result)

    def test_http_url_returns_none(self):
        result = _file_url_to_path("http://example.com/test.whl")
        self.assertIsNone(result)

    def test_empty_string(self):
        result = _file_url_to_path("")
        self.assertIsNone(result)

    def test_file_url_with_nested_path(self):
        result = _file_url_to_path("file:///home/user/project/dist/pkg.whl")
        self.assertIsNotNone(result)
        self.assertIn("dist", str(result))
        self.assertTrue(str(result).endswith("pkg.whl"))

    def test_resolves_path(self):
        result = _file_url_to_path("file:///tmp/../tmp/test.whl")
        self.assertIsNotNone(result)
        # Should be resolved
        self.assertNotIn("..", str(result))


class TestResolveOutputDir(unittest.TestCase):
    """Tests for _resolve_output_dir(source, override)."""

    def test_with_override(self):
        result = _resolve_output_dir(Path("/project/src"), "/custom/output")
        self.assertEqual(result, Path("/custom/output").resolve())

    def test_without_override_uses_dist(self):
        result = _resolve_output_dir(Path("/project/src"), None)
        self.assertEqual(result, (Path("/project/src") / "dist").resolve())

    def test_override_expands_user(self):
        result = _resolve_output_dir(Path("/project/src"), "~/output")
        self.assertNotIn("~", str(result))

    def test_override_resolves(self):
        result = _resolve_output_dir(Path("/project/src"), "/tmp/../tmp/output")
        self.assertNotIn("..", str(result))


if __name__ == "__main__":
    unittest.main()
