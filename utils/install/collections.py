"""Compare the pinned Galaxy requirements against what is on disk.

Imported by the lint bootstrap, which runs on a bare interpreter before any
dependency is installed, so this module stays on the standard library. It also
stays inside its own package: the Dockerfile copies it into the image beside
``utils/__init__.py`` and ``utils/install/__init__.py`` and nothing else, so
importing any other ``utils`` submodule raises ``ModuleNotFoundError`` in the
layer that runs it. The
requirements files it reads are this repository's own and hold one shape:
a ``collections:`` list of ``- name:`` entries with an optional ``version:``.
A line that does not match that shape leaves the entry unpinned, which the
caller treats as unsatisfied and installs.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_NAME = re.compile(r"^\s*-\s+name:\s*(?P<name>[A-Za-z0-9_.]+)\s*(?:#.*)?$")
_VERSION = re.compile(
    r"^\s*version:\s*(?P<quote>[\"']?)(?P<version>[^\s#\"']+)(?P=quote)\s*(?:#.*)?$"
)


def declared_pins(requirements_file: Path) -> list[tuple[str, str | None]]:
    """The ``(fqcn, version)`` pairs a requirements file declares, in order.

    Args:
        requirements_file: the requirements.galaxy.yml to read.
    """
    pins: list[tuple[str, str | None]] = []
    try:
        raw = requirements_file.read_text(encoding="utf-8")  # nocheck: cache-read
    except OSError:
        return pins
    lines = raw.splitlines()

    for line in lines:
        name_match = _NAME.match(line)
        if name_match:
            pins.append((name_match.group("name"), None))
            continue
        version_match = _VERSION.match(line)
        if version_match and pins:
            fqcn, _ = pins[-1]
            pins[-1] = (fqcn, version_match.group("version"))
    return pins


def _installed_version(collections_dir: Path, namespace: str, name: str) -> str | None:
    """The version recorded in a collection's manifest, or None when absent.

    Args:
        collections_dir: the ``-p`` target ansible-galaxy installs into.
        namespace: collection namespace, the part before the dot.
        name: collection name, the part after the dot.
    """
    manifest = (
        collections_dir / "ansible_collections" / namespace / name / "MANIFEST.json"
    )
    try:
        raw = manifest.read_text(encoding="utf-8")  # nocheck: cache-read
        payload = json.loads(raw)
    except (OSError, ValueError):
        return None
    version = payload.get("collection_info", {}).get("version")
    return str(version) if version else None


def unsatisfied(requirements_file: Path, collections_dir: Path) -> list[str]:
    """Requirements that COLLECTIONS_DIR does not already hold at the pinned version.

    An entry without a pinned version can never be confirmed from disk and is
    always reported, so the caller falls through to a real install.

    Args:
        requirements_file: the requirements.galaxy.yml to read.
        collections_dir: the ``-p`` target ansible-galaxy installs into.
    """
    missing: list[str] = []
    for fqcn, pinned in declared_pins(requirements_file):
        if "." not in fqcn or not pinned:
            missing.append(fqcn)
            continue
        namespace, _, name = fqcn.partition(".")
        if _installed_version(collections_dir, namespace, name) != pinned:
            missing.append(f"{fqcn}:{pinned}")
    return missing


def main() -> int:
    """Exit 0 when every pinned collection is present at its pinned version.

    Args:
        argv[1]: path to requirements.galaxy.yml.
        argv[2]: path to the collections directory.
    """
    missing = unsatisfied(Path(sys.argv[1]), Path(sys.argv[2]))
    if missing:
        print(" ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
