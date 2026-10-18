"""Every relative bind source a compose file names must exist in the tree.

Docker silently creates a directory for a bind source that is missing, so a
mistyped path never fails the `up`. It fails much later, wherever the target
was supposed to be a file: one such directory landed on a systemd drop-in and
turned `systemctl enable docker` into `File docker.service: Is a directory`.

A relative source resolves against the project directory, so one that escapes
the tree is wrong by construction. Absolute sources are host paths the cache
stack creates on demand and are out of scope, as is a source a ``.gitignore``
claims: the repository declares it generated, and its generator runs before
the ``up``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import ClassVar

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.gitignore import is_path_gitignored, load_gitignore_patterns
from utils.cache.yaml import load_yaml_any

FILES = ("compose.yml", "compose.cache-consumer.yml", "compose/*.yml", "i18n/*.yml")
DEFAULT_ENV = "default.env"
INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:[:?-][^}]*)?\}")


def _defaults(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in read_text(str(root / DEFAULT_ENV)).splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _expand(text: str, values: dict[str, str]) -> str | None:
    """Substitute every ``${VAR}`` from *values*, or None when one is unknown."""
    missing = False

    def replace(match: re.Match[str]) -> str:
        nonlocal missing
        name = match.group(1)
        if name not in values:
            missing = True
            return ""
        return values[name]

    expanded = INTERPOLATION.sub(replace, text)
    return None if missing else expanded


def _head(entry: str) -> str:
    """Return the source of a short-syntax mount.

    A plain ``split(":")`` cuts inside ``${VAR:?message}``, so the scan skips
    every colon that sits within an interpolation.
    """
    depth = 0
    for index, char in enumerate(entry):
        if entry.startswith("${", index):
            depth += 1
        elif char == "}" and depth:
            depth -= 1
        elif char == ":" and not depth:
            return entry[:index]
    return entry


def _generated(root: Path, resolved: Path) -> bool:
    """Whether a ``.gitignore`` between *root* and *resolved* declares the source generated.

    Args:
        root: the project directory relative sources resolve against.
        resolved: an in-tree bind source that does not exist yet.
    """
    rel = resolved.relative_to(root).parts
    for depth in range(len(rel)):
        patterns = load_gitignore_patterns(str(root.joinpath(*rel[:depth])))
        if patterns and is_path_gitignored("/".join(rel[depth:]), patterns):
            return True
    return False


def _sources(body) -> list[str]:
    found: list[str] = []
    for entry in (body or {}).get("volumes") or []:
        if isinstance(entry, str):
            found.append(_head(entry))
        elif isinstance(entry, dict) and entry.get("type") == "bind":
            found.append(str(entry.get("source", "")))
    return found


class TestComposeBindSourcesExist(unittest.TestCase):
    root: ClassVar[Path] = Path(PROJECT_ROOT)

    def test_every_in_tree_bind_source_exists(self) -> None:
        values = _defaults(self.root)
        missing: dict[str, list[str]] = {}
        for pattern in FILES:
            for path in sorted(self.root.glob(pattern)):
                loaded = load_yaml_any(str(path), default_if_missing={}) or {}
                for body in (loaded.get("services") or {}).values():
                    if not isinstance(body, dict):
                        continue
                    for raw in _sources(body):
                        source = _expand(raw, values)
                        if source is None or not source.startswith((".", "/")):
                            continue
                        resolved = (self.root / source).resolve()
                        outside = not resolved.is_relative_to(self.root)
                        if outside and Path(source).is_absolute():
                            continue
                        if outside or not (
                            resolved.exists() or _generated(self.root, resolved)
                        ):
                            key = str(path.relative_to(self.root))
                            missing.setdefault(key, []).append(raw)

        self.assertEqual(
            missing,
            {},
            f"{sum(len(v) for v in missing.values())} relative bind source(s) "
            f"escape the project tree or do not exist: {missing}. Docker creates "
            "each one as an empty directory and mounts that over the target. "
            "Spell every relative source against the project directory.",
        )


if __name__ == "__main__":
    unittest.main()
