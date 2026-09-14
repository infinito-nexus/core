"""Pinned pip requirements in ``roles/**/*.yml``.

A role that hands ``sys-pip-install`` a bare package name follows whatever pip
resolves; one that pins ``name==version`` freezes it, and nothing thaws it
again. The docker updater keeps image tags current and dependabot reads
``pyproject.toml``; neither sees a version inside an Ansible task variable, so
a pin set once ages silently.

Only exact ``==`` pins are collected. A range or a VCS reference states an
intent this cannot second-guess.

Suppress a package by placing ``# nocheck: pip-version`` on the line directly
above the ``package_name:`` key, or on the key itself:

    # nocheck: pip-version
    package_name: "automtu==1.1.1"
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.update.base import is_semver, version_key

if TYPE_CHECKING:
    from pathlib import Path

PIN_PATTERN = re.compile(
    r"^(?P<indent>\s*)package_name:\s*"
    r"(?P<quote>[\"']?)(?P<package>[A-Za-z0-9][A-Za-z0-9._-]*)=="
    r"(?P<version>[0-9][0-9A-Za-z.+-]*)(?P=quote)"
    r"(?P<suffix>\s*(?:#.*)?)$"
)

MARKER = "pip-version"


@dataclass(frozen=True)
class PipPinEntry:
    """One ``package_name: "<name>==<version>"`` line.

    Args:
        role: the role directory the pin lives in.
        package: the distribution name on PyPI.
        version: the pinned version.
        config_path: the task file holding the pin.
        line_number: 1-indexed line of the pin.
    """

    role: str
    package: str
    version: str
    config_path: Path
    line_number: int


@dataclass(frozen=True)
class PipPinUpdate:
    entry: PipPinEntry
    latest: str


def collect_entries(repo_root: Path) -> list[PipPinEntry]:
    """Return every exact pip pin under ``roles/``.

    Args:
        repo_root: repository root to scan.
    """
    entries: list[PipPinEntry] = []
    for path in sorted((repo_root / "roles").rglob("*.yml")):
        text = read_text(str(path))
        if "package_name:" not in text:
            continue
        lines = text.splitlines()
        for index, line in enumerate(lines):
            match = PIN_PATTERN.match(line)
            if not match:
                continue
            if is_suppressed_at(lines, index + 1, MARKER) or MARKER in line:
                continue
            entries.append(
                PipPinEntry(
                    role=path.relative_to(repo_root / "roles").parts[0],
                    package=match.group("package"),
                    version=match.group("version"),
                    config_path=path,
                    line_number=index + 1,
                )
            )
    return entries


def fetch_pypi_versions(package: str) -> list[str]:
    """Return every released version of ``package``, empty when PyPI is unreachable.

    Args:
        package: distribution name.
    """
    url = f"https://pypi.org/pypi/{package}/json"
    req = urllib.request.Request(
        url, headers={"User-Agent": "infinito-nexus-version-updater"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - fixed https PyPI origin, package name matched against PIN_PATTERN
            body = json.loads(resp.read().decode())
    except (
        urllib.error.URLError,
        OSError,
        http.client.HTTPException,
        json.JSONDecodeError,
    ):
        return []
    releases = body.get("releases") or {}
    return [
        version
        for version, files in releases.items()
        if is_semver(version) and any(not f.get("yanked") for f in files)
    ]


def latest_release(package: str) -> str | None:
    """Return the highest released version of ``package``, or None.

    Args:
        package: distribution name.
    """
    versions = fetch_pypi_versions(package)
    return max(versions, key=version_key) if versions else None


def find_outdated_updates(repo_root: Path) -> list[PipPinUpdate]:
    """Return one update per pin that PyPI has moved past.

    Args:
        repo_root: repository root to scan.
    """
    updates: list[PipPinUpdate] = []
    latest_by_package: dict[str, str | None] = {}
    for entry in collect_entries(repo_root):
        if not is_semver(entry.version):
            continue
        if entry.package not in latest_by_package:
            latest_by_package[entry.package] = latest_release(entry.package)
        latest = latest_by_package[entry.package]
        if latest and version_key(latest) > version_key(entry.version):
            updates.append(PipPinUpdate(entry=entry, latest=latest))
    return updates


def apply_updates(updates: list[PipPinUpdate]) -> list[Path]:
    """Rewrite each pin to its latest version and return the files changed.

    Args:
        updates: the updates to apply.
    """
    by_path: dict[Path, dict[int, str]] = {}
    for update in updates:
        by_path.setdefault(update.entry.config_path, {})[update.entry.line_number] = (
            update.latest
        )

    changed: list[Path] = []
    for path, line_versions in sorted(by_path.items()):
        lines = read_text(str(path)).splitlines(keepends=True)
        touched = False
        for line_number, latest in line_versions.items():
            original = lines[line_number - 1]
            match = PIN_PATTERN.match(original.rstrip("\n"))
            if not match:
                continue
            quote = match.group("quote")
            replacement = (
                f"{match.group('indent')}package_name: "
                f"{quote}{match.group('package')}=={latest}{quote}"
                f"{match.group('suffix')}\n"
            )
            if replacement != original:
                lines[line_number - 1] = replacement
                touched = True
        if touched:
            path.write_text("".join(lines), encoding="utf-8")
            changed.append(path)
    return changed
