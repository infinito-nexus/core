"""Codex CLI at the version the dsk-gnt-codex role pins."""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.install.npm import ensure_npm_present, npm_install_global
from utils.install.primitives import which
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.source import collect_entries

if TYPE_CHECKING:
    from pathlib import Path

ROLE = "dsk-gnt-codex"
ENTITY = "codex"
PROBE_TIMEOUT_SECONDS = 30


class CodexPinError(RuntimeError):
    """The role declares no single npm pin for the Codex CLI."""


class CodexInstallError(RuntimeError):
    """npm did not leave the pinned Codex CLI on PATH."""


def pinned_package(repo_root: Path) -> tuple[str, str]:
    """Return the npm package and version the role pins for the Codex CLI.

    Args:
        repo_root: repository root whose ``roles/`` holds the role.

    Returns:
        The package name and the pinned version.

    Raises:
        CodexPinError: the role, its entity, its npm source or the pinned
            version is missing, or the update job does not watch the pin.
    """
    pins = [
        entry
        for entry in collect_entries(repo_root)
        if entry.role == ROLE
        and entry.entity == ENTITY
        and entry.source.get("type") == "npm"
        and entry.source.get("package")
    ]
    if len(pins) != 1:
        raise CodexPinError(
            f"No Codex CLI pin in {repo_root / 'roles' / ROLE / ROLE_FILE_META_SERVICES}: "
            f"the update job needs exactly one npm source with a package and a "
            f"pinned version on the {ENTITY} entity, found {len(pins)}."
        )
    return str(pins[0].source["package"]), pins[0].current


def installed_version() -> str:
    """Return the version the ``codex`` on PATH reports.

    The client writes path aliases into ``CODEX_HOME`` on every start,
    ``--version`` included, so the probe runs against a throwaway home.

    Returns:
        The reported version, or an empty string when no client answers in
        time or with success, which the caller treats as one to replace.
    """
    if not which("codex"):
        return ""
    with tempfile.TemporaryDirectory() as home:
        try:
            reported = subprocess.run(
                ["codex", "--version"],
                env=dict(os.environ, CODEX_HOME=home),
                capture_output=True,
                text=True,
                check=True,
                timeout=PROBE_TIMEOUT_SECONDS,
            ).stdout.split()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return ""
    return reported[-1] if reported else ""


def ensure_published(package: str, version: str) -> None:
    """Refuse the install before npm retries a spec its registry cannot serve.

    ``npm view`` resolves the spec the way ``npm install`` does, through the
    scoped registries and proxies of the npm config. It exits 0 with empty
    output when the package exists but the version does not.

    Args:
        package: npm package name.
        version: version the caller is about to install.

    Raises:
        CodexInstallError: npm does not answer in time, fails, or finds no
            such version.
    """
    spec = f"{package}@{version}"
    try:
        published = subprocess.run(
            ["npm", "view", spec, "version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        ).stdout.strip()
    except subprocess.TimeoutExpired as exc:
        raise CodexInstallError(
            f"npm cannot reach its registry, so {spec} cannot be installed: "
            f"npm view did not answer within {PROBE_TIMEOUT_SECONDS}s"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise CodexInstallError(
            f"npm cannot resolve {spec} through its registry, so it cannot be "
            f"installed: {exc.stderr.strip()}"
        ) from exc
    if published != version:
        raise CodexInstallError(f"{spec} is not published in npm's configured registry")


def ensure_codex_present(repo_root: Path) -> None:
    """Install the Codex CLI at the version the role pins.

    The result is checked against the PATH this process started with. When
    the global install is refused, ``npm_install_global`` falls back to a
    per-user prefix and puts it on this process's PATH only; the test run
    started after this one would not find that client and skip its tests.

    Args:
        repo_root: repository root whose ``roles/`` holds the role.

    Raises:
        CodexPinError: the role declares no single pin.
        CodexInstallError: the registry cannot serve the pin, or ``codex`` on
            the original PATH still reports another version after the install.
    """
    package, version = pinned_package(repo_root)
    if installed_version() == version:
        return
    spec = f"{package}@{version}"
    ensure_npm_present()
    ensure_published(package, version)
    search = os.environ["PATH"]
    npm_install_global(spec)
    os.environ["PATH"] = search
    installed = installed_version()
    if installed != version:
        raise CodexInstallError(
            f"codex on PATH reports {installed!r} after installing {spec}"
        )


if __name__ == "__main__":
    ensure_codex_present(PROJECT_ROOT)
