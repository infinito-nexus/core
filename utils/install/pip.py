"""Pip-based installer with venv / sudo / --user fallback logic."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from utils.install.primitives import ensure_dir_on_path, log


def detect_python_bin() -> str:
    candidate = os.environ.get("PYTHON")
    if candidate and shutil.which(candidate) is not None:
        return candidate
    if shutil.which("python3") is not None:
        return "python3"
    if shutil.which("python") is not None:
        return "python"
    raise RuntimeError("Need python, python3, curl, or wget.")


def python_runs_in_venv(python_bin: str) -> bool:
    code = "import sys; raise SystemExit(0 if sys.prefix != getattr(sys, 'base_prefix', sys.prefix) else 1)"
    result = subprocess.run([python_bin, "-c", code], capture_output=True, check=False)
    return result.returncode == 0


def detect_python_scripts_dir(python_bin: str) -> str:
    code = "import sysconfig; print(sysconfig.get_path('scripts') or '')"
    result = subprocess.run(
        [python_bin, "-c", code], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def detect_python_user_scripts_dir(python_bin: str) -> str:
    code = (
        "import site, sys\n"
        "ub = site.getuserbase()\n"
        "sys.exit(1) if not ub else print(f'{ub}/bin')\n"
    )
    result = subprocess.run(
        [python_bin, "-c", code], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def pip_supports_break_system_packages(python_bin: str) -> bool:
    result = subprocess.run(
        [python_bin, "-m", "pip", "install", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    return "--break-system-packages" in result.stdout


def install_pip_pkg(pip_spec: str) -> None:
    python_bin = detect_python_bin()
    scripts_dir = ""
    user_scripts_dir = ""

    try:
        scripts_dir = detect_python_scripts_dir(python_bin)
    except subprocess.CalledProcessError:
        scripts_dir = ""

    log(f"Installing Python package '{pip_spec}' via {python_bin} -m pip")

    pip_args = [python_bin, "-m", "pip", "install", "--upgrade", pip_spec]

    if python_runs_in_venv(python_bin):
        try:
            subprocess.run(pip_args, check=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"pip install failed for '{pip_spec}' in venv") from exc
    elif os.geteuid() == 0:
        try:
            subprocess.run(pip_args, check=True)
        except subprocess.CalledProcessError:
            if not pip_supports_break_system_packages(python_bin):
                raise RuntimeError(
                    f"pip install failed for '{pip_spec}' (root) and "
                    "--break-system-packages is unsupported"
                ) from None
            log("Retrying Python package install with --break-system-packages")
            try:
                subprocess.run(
                    [
                        python_bin,
                        "-m",
                        "pip",
                        "install",
                        "--break-system-packages",
                        "--upgrade",
                        pip_spec,
                    ],
                    check=True,
                )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    f"pip install --break-system-packages failed for '{pip_spec}'"
                ) from exc
    else:
        try:
            subprocess.run(
                [python_bin, "-m", "pip", "install", "--user", "--upgrade", pip_spec],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"pip install --user failed for '{pip_spec}'") from exc
        user_scripts_dir = detect_python_user_scripts_dir(python_bin)

    if scripts_dir and Path(scripts_dir).is_dir():
        ensure_dir_on_path(scripts_dir)

    if user_scripts_dir and Path(user_scripts_dir).is_dir():
        ensure_dir_on_path(user_scripts_dir)


__all__ = [
    "detect_python_bin",
    "detect_python_scripts_dir",
    "detect_python_user_scripts_dir",
    "install_pip_pkg",
    "pip_supports_break_system_packages",
    "python_runs_in_venv",
]
