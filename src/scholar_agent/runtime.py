"""Runtime installation helpers for Scholar Agent."""

from __future__ import annotations

import importlib.util
import importlib.metadata as metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse


PACKAGE_NAME = "scholar-agent"
EXECUTABLE_NAME = "scholar-agent"


def _file_url_to_path(raw_url: str) -> Path | None:
    parsed = urlparse(raw_url)
    if parsed.scheme != "file":
        return None
    # url2pathname handles platform quirks (e.g. leading /C: on Windows)
    import urllib.request
    return Path(urllib.request.url2pathname(parsed.path)).resolve()


def _load_direct_url(dist_info_path: Path) -> dict[str, object] | None:
    direct_url_path = dist_info_path / "direct_url.json"
    if not direct_url_path.exists():
        return None
    try:
        payload = json.loads(direct_url_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _resolve_install_source(before: dict[str, object], source_path: str | Path | None) -> Path:
    if source_path is not None:
        return Path(source_path).expanduser().resolve()

    raw_source_path = before.get("source_path")
    if isinstance(raw_source_path, str) and raw_source_path.strip():
        return Path(raw_source_path).expanduser().resolve()

    raise RuntimeError("Could not determine a source path for standalone installation; pass --source explicitly.")


def _find_built_wheel(wheel_dir: Path) -> Path:
    wheels = list(wheel_dir.glob("scholar_agent-*.whl"))
    if not wheels:
        raise RuntimeError(f"Failed to build a scholar-agent wheel in {wheel_dir}")
    if len(wheels) == 1:
        return wheels[0]

    def _version_tuple(p: Path) -> tuple[int, ...]:
        m = re.search(r"scholar_agent-(\d+(?:\.\d+)*)", p.name)
        if not m:
            return (0,)
        return tuple(int(x) for x in m.group(1).split("."))
    return max(wheels, key=_version_tuple)


def _resolve_output_dir(resolved_source: Path, output_dir: str | Path | None) -> Path:
    if output_dir is not None:
        return Path(output_dir).expanduser().resolve()
    return (resolved_source / "dist").resolve()


def _build_wheel_artifact(
    *,
    source_path: Path,
    wheel_dir: Path,
    python_executable: str,
    with_deps: bool,
) -> tuple[list[str], subprocess.CompletedProcess[str], Path]:
    wheel_dir.mkdir(parents=True, exist_ok=True)

    build_command = [
        python_executable,
        "-m",
        "pip",
        "wheel",
        "--wheel-dir",
        str(wheel_dir),
        "--no-build-isolation",
    ]
    if not with_deps:
        build_command.append("--no-deps")
    build_command.append(str(source_path))

    try:
        build_completed = subprocess.run(build_command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"pip wheel build failed (exit {exc.returncode}):\n{exc.stderr or exc.stdout}"
        ) from exc
    built_wheel = _find_built_wheel(wheel_dir)
    return build_command, build_completed, built_wheel


def _resolve_pipx_command(
    *,
    python_executable: str,
    pipx_executable: str | Path | None = None,
) -> list[str]:
    if pipx_executable is not None:
        return [str(Path(pipx_executable).expanduser().resolve())]

    resolved_executable = shutil.which("pipx")
    if resolved_executable is not None:
        return [resolved_executable]

    if importlib.util.find_spec("pipx") is not None:
        return [python_executable, "-m", "pipx"]

    raise RuntimeError(
        "pipx is not available. Install pipx or make it importable from the selected Python interpreter."
    )


def _load_pipx_list(pipx_command_prefix: list[str]) -> dict[str, object] | None:
    try:
        completed = subprocess.run(
            [*pipx_command_prefix, "list", "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _pipx_package_installed(pipx_command_prefix: list[str], package_name: str) -> bool:
    payload = _load_pipx_list(pipx_command_prefix)
    if not isinstance(payload, dict):
        return False
    venvs = payload.get("venvs")
    return isinstance(venvs, dict) and package_name in venvs


def _build_pipx_install_plan(
    *,
    pipx_command_prefix: list[str],
    resolved_python: str,
    resolved_wheel: Path,
    force: bool,
) -> tuple[list[str] | None, list[str], str]:
    if force and _pipx_package_installed(pipx_command_prefix, PACKAGE_NAME):
        uninstall_command = [*pipx_command_prefix, "uninstall", PACKAGE_NAME]
        install_command = [*pipx_command_prefix, "install", "--python", resolved_python, str(resolved_wheel)]
        return uninstall_command, install_command, "reinstall"

    command = [*pipx_command_prefix, "install", "--python", resolved_python]
    if force:
        command.append("--force")
    command.append(str(resolved_wheel))
    return None, command, "install"


def _default_pipx_bin_dir(env: Mapping[str, str] | None = None) -> Path:
    env_map = os.environ if env is None else env
    override = env_map.get("PIPX_BIN_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        local_appdata = env_map.get("LOCALAPPDATA", "").strip()
        if local_appdata:
            return (Path(local_appdata) / "pipx" / "bin").resolve()
    return (Path.home() / ".local" / "bin").resolve()


def _default_pipx_home(env: Mapping[str, str] | None = None) -> Path:
    env_map = os.environ if env is None else env
    override = env_map.get("PIPX_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        local_appdata = env_map.get("LOCALAPPDATA", "").strip()
        if local_appdata:
            return (Path(local_appdata) / "pipx").resolve()
    return (Path.home() / ".local" / "pipx").resolve()


def _resolve_optional_path(raw_path: str | Path | None) -> Path | None:
    if raw_path is None:
        return None
    try:
        return Path(raw_path).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _is_relative_to(path: Path | None, parent: Path) -> bool:
    if path is None:
        return False
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _detect_install_manager(
    *,
    dist_info_path: Path,
    package_root: Path,
    python_executable: str,
    env: Mapping[str, str] | None = None,
) -> tuple[str, bool, Path, Path]:
    pipx_home = _default_pipx_home(env)
    pipx_bin_dir = _default_pipx_bin_dir(env)
    pipx_venvs_dir = pipx_home / "venvs"

    pipx_managed = any(
        _is_relative_to(candidate, pipx_venvs_dir)
        for candidate in (
            dist_info_path.resolve(),
            package_root.resolve(),
            _resolve_optional_path(python_executable),
        )
    )

    return ("pipx" if pipx_managed else "direct"), pipx_managed, pipx_home, pipx_bin_dir


def _path_contains(target: Path, env: Mapping[str, str] | None = None) -> bool:
    env_map = os.environ if env is None else env
    for entry in env_map.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            if Path(entry).expanduser().resolve() == target.resolve():
                return True
        except OSError:
            continue
    return False


def build_wheel(
    *,
    source_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    python_executable: str | None = None,
) -> dict[str, object]:
    before = get_installation_state()
    resolved_source = _resolve_install_source(before, source_path)
    resolved_output_dir = _resolve_output_dir(resolved_source, output_dir)
    resolved_python = python_executable or sys.executable

    build_command, build_completed, built_wheel = _build_wheel_artifact(
        source_path=resolved_source,
        wheel_dir=resolved_output_dir,
        python_executable=resolved_python,
        with_deps=False,
    )
    return {
        "status": "ok",
        "source_path": str(resolved_source),
        "output_dir": str(resolved_output_dir),
        "wheel_path": str(built_wheel),
        "python_executable": resolved_python,
        "before": before,
        "build_command": build_command,
        "build_stdout": build_completed.stdout.strip(),
        "build_stderr": build_completed.stderr.strip(),
    }


def install_with_pipx(
    *,
    source_path: str | Path | None = None,
    wheel_path: str | Path | None = None,
    python_executable: str | None = None,
    pipx_executable: str | Path | None = None,
    force: bool = False,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    if source_path is not None and wheel_path is not None:
        raise ValueError("Pass either source_path or wheel_path, not both.")

    resolved_python = python_executable or sys.executable
    pipx_command_prefix = _resolve_pipx_command(
        python_executable=resolved_python,
        pipx_executable=pipx_executable,
    )

    build_payload: dict[str, object] | None = None
    resolved_source: Path | None = None

    if wheel_path is not None:
        resolved_wheel = Path(wheel_path).expanduser().resolve()
        if not resolved_wheel.exists():
            raise RuntimeError(f"Wheel does not exist: {resolved_wheel}")
    else:
        before = get_installation_state()
        resolved_source = _resolve_install_source(before, source_path)
        with tempfile.TemporaryDirectory() as tmp:
            wheel_dir = Path(tmp) / "wheelhouse"
            build_command, build_completed, resolved_wheel = _build_wheel_artifact(
                source_path=resolved_source,
                wheel_dir=wheel_dir,
                python_executable=resolved_python,
                with_deps=False,
            )

            uninstall_command, install_command, pipx_operation = _build_pipx_install_plan(
                pipx_command_prefix=pipx_command_prefix,
                resolved_python=resolved_python,
                resolved_wheel=resolved_wheel,
                force=force,
            )
            uninstall_completed: subprocess.CompletedProcess[str] | None = None
            if uninstall_command is not None:
                try:
                    uninstall_completed = subprocess.run(uninstall_command, check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as exc:
                    raise RuntimeError(
                        f"pipx uninstall failed (exit {exc.returncode}):\n{exc.stderr or exc.stdout}"
                    ) from exc
            try:
                install_completed = subprocess.run(install_command, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    f"pipx install failed (exit {exc.returncode}):\n{exc.stderr or exc.stdout}"
                ) from exc

            build_payload = {
                "source_path": str(resolved_source),
                "wheel_path": str(resolved_wheel),
                "build_command": build_command,
                "build_stdout": build_completed.stdout.strip(),
                "build_stderr": build_completed.stderr.strip(),
                "temporary": True,
            }

            pipx_bin_dir = _default_pipx_bin_dir(env)
            return {
                "status": "ok",
                "python_executable": resolved_python,
                "pipx_command": install_command,
                "pipx_driver": pipx_command_prefix,
                "pipx_operation": pipx_operation,
                "pipx_uninstall_command": uninstall_command,
                "wheel_path": str(resolved_wheel),
                "source_path": str(resolved_source),
                "build": build_payload,
                "force": force,
                "pipx_bin_dir": str(pipx_bin_dir),
                "pipx_path_ready": _path_contains(pipx_bin_dir, env),
                "expected_executable": str(pipx_bin_dir / EXECUTABLE_NAME),
                "uninstall_stdout": uninstall_completed.stdout.strip() if uninstall_completed is not None else "",
                "uninstall_stderr": uninstall_completed.stderr.strip() if uninstall_completed is not None else "",
                "install_stdout": install_completed.stdout.strip(),
                "install_stderr": install_completed.stderr.strip(),
            }

    uninstall_command, install_command, pipx_operation = _build_pipx_install_plan(
        pipx_command_prefix=pipx_command_prefix,
        resolved_python=resolved_python,
        resolved_wheel=resolved_wheel,
        force=force,
    )
    uninstall_completed: subprocess.CompletedProcess[str] | None = None
    if uninstall_command is not None:
        try:
            uninstall_completed = subprocess.run(uninstall_command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"pipx uninstall failed (exit {exc.returncode}):\n{exc.stderr or exc.stdout}"
            ) from exc
    try:
        install_completed = subprocess.run(install_command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"pipx install failed (exit {exc.returncode}):\n{exc.stderr or exc.stdout}"
        ) from exc

    pipx_bin_dir = _default_pipx_bin_dir(env)
    return {
        "status": "ok",
        "python_executable": resolved_python,
        "pipx_command": install_command,
        "pipx_driver": pipx_command_prefix,
        "pipx_operation": pipx_operation,
        "pipx_uninstall_command": uninstall_command,
        "wheel_path": str(resolved_wheel),
        "source_path": str(resolved_source) if resolved_source is not None else None,
        "build": build_payload,
        "force": force,
        "pipx_bin_dir": str(pipx_bin_dir),
        "pipx_path_ready": _path_contains(pipx_bin_dir, env),
        "expected_executable": str(pipx_bin_dir / EXECUTABLE_NAME),
        "uninstall_stdout": uninstall_completed.stdout.strip() if uninstall_completed is not None else "",
        "uninstall_stderr": uninstall_completed.stderr.strip() if uninstall_completed is not None else "",
        "install_stdout": install_completed.stdout.strip(),
        "install_stderr": install_completed.stderr.strip(),
    }


def get_installation_state() -> dict[str, object]:
    executable_path = shutil.which(EXECUTABLE_NAME)
    try:
        dist = metadata.distribution(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return {
            "status": "missing",
            "installed": False,
            "install_mode": "missing",
            "install_manager": None,
            "pipx_managed": False,
            "executable_path": executable_path,
            "python_executable": sys.executable,
        }

    # _path is private, but importlib.metadata exposes no public API that reliably
    # points back to the installed dist-info/egg-info directory across Python 3.10+.
    dist_info_path = Path(dist._path)
    direct_url = _load_direct_url(dist_info_path)
    dir_info = direct_url.get("dir_info", {}) if isinstance(direct_url, dict) else {}
    editable = isinstance(dir_info, dict) and bool(dir_info.get("editable"))
    source_url = direct_url.get("url") if isinstance(direct_url, dict) else None
    source_path = _file_url_to_path(source_url) if isinstance(source_url, str) else None
    if dist_info_path.suffix == ".egg-info":
        editable = True
        if source_path is None:
            source_path = dist_info_path.parent.resolve()

    package_root = Path(dist.locate_file("")).resolve()
    install_manager, pipx_managed, pipx_home, pipx_bin_dir = _detect_install_manager(
        dist_info_path=dist_info_path,
        package_root=package_root,
        python_executable=sys.executable,
    )

    return {
        "status": "ok",
        "installed": True,
        "install_mode": "editable" if editable else "standalone",
        "install_manager": install_manager,
        "pipx_managed": pipx_managed,
        "version": dist.version,
        "package_root": str(package_root),
        "dist_info_path": str(dist_info_path),
        "direct_url": direct_url,
        "source_url": source_url,
        "source_path": str(source_path) if source_path is not None else None,
        "pipx_home": str(pipx_home) if pipx_managed else None,
        "pipx_bin_dir": str(pipx_bin_dir) if pipx_managed else None,
        "executable_path": executable_path,
        "python_executable": sys.executable,
    }


def install_standalone(
    *,
    source_path: str | Path | None = None,
    python_executable: str | None = None,
    with_deps: bool = False,
) -> dict[str, object]:
    before = get_installation_state()

    resolved_source = _resolve_install_source(before, source_path)
    resolved_python = python_executable or sys.executable

    with tempfile.TemporaryDirectory() as tmp:
        wheel_dir = Path(tmp) / "wheelhouse"
        build_command, build_completed, built_wheel = _build_wheel_artifact(
            source_path=resolved_source,
            wheel_dir=wheel_dir,
            python_executable=resolved_python,
            with_deps=with_deps,
        )

        install_command = [
            resolved_python,
            "-m",
            "pip",
            "install",
            "--force-reinstall",
            "--no-index",
            "--find-links",
            str(wheel_dir),
        ]
        if not with_deps:
            install_command.append("--no-deps")
        install_command.append(PACKAGE_NAME)
        try:
            install_completed = subprocess.run(install_command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"pip install failed (exit {exc.returncode}):\n{exc.stderr or exc.stdout}"
            ) from exc

    after = get_installation_state()
    return {
        "status": "ok",
        "build_command": build_command,
        "install_command": install_command,
        "source_path": str(resolved_source),
        "wheel_path": str(built_wheel),
        "with_deps": with_deps,
        "before": before,
        "after": after,
        "build_stdout": build_completed.stdout.strip(),
        "build_stderr": build_completed.stderr.strip(),
        "install_stdout": install_completed.stdout.strip(),
        "install_stderr": install_completed.stderr.strip(),
    }