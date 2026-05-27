"""Lint check: tracked files under the Ansible plugin source directories
declared in :file:`ansible.cfg` MUST be Python source files.

The directories scanned are read live from the project's ``ansible.cfg``
``[defaults]`` section. Keys consulted:

* ``action_plugins``
* ``filter_plugins``
* ``lookup_plugins``
* ``library``
* ``module_utils``

A future edit to those keys (renaming a directory, adding a new
``*_plugins`` key) automatically updates this lint's coverage without
touching the test source.

``README.md`` files inside the scanned directories are allowed as
documentation-only exceptions, matching the precedent set by the
sibling ``test_scripts_folder_files.py`` lint.
"""

from __future__ import annotations

import configparser
import subprocess
import unittest
from typing import TYPE_CHECKING

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_ANSIBLE_CFG_PATH = PROJECT_ROOT / "ansible.cfg"

# Plugin path keys to read from the ``[defaults]`` section. Listed
# explicitly (rather than scanning the section blindly) so an unrelated
# defaults entry that happens to point at a directory does not get
# pulled into the lint by accident.
_PLUGIN_PATH_KEYS: tuple[str, ...] = (
    "action_plugins",
    "filter_plugins",
    "lookup_plugins",
    "library",
    "module_utils",
)

# Filenames inside a plugin directory that are exempt from the
# ``.py``-only rule. Kept narrow on purpose: anything else has no
# business living under an Ansible plugin path.
_ALLOWED_NON_PY: frozenset[str] = frozenset({"README.md"})


def _plugin_dirs() -> list[Path]:
    """Return the list of plugin source directories from ``ansible.cfg``.

    Empty values, unset keys, and keys whose resolved path is not an
    existing directory are skipped silently — they cannot harbour file
    violations, so flagging them here would just produce noise.
    """
    parser = configparser.ConfigParser()
    parser.read(_ANSIBLE_CFG_PATH)
    if not parser.has_section("defaults"):
        return []
    dirs: list[Path] = []
    for key in _PLUGIN_PATH_KEYS:
        raw = parser.get("defaults", key, fallback="").strip()
        if not raw:
            continue
        # ansible.cfg paths use forward slashes and may have a leading
        # ``./`` to mark them as repo-relative. Strip the marker so the
        # subsequent join produces a clean absolute path.
        relative = raw.removeprefix("./")
        candidate = PROJECT_ROOT / relative
        if candidate.is_dir():
            dirs.append(candidate.resolve())
    return dirs


def _tracked_files(root: Path) -> list[Path]:
    """Return repo-tracked files under *root*, falling back to a
    filesystem walk when ``git ls-files`` is unavailable (e.g. inside
    the run container where ``.git`` is not mounted).
    """
    try:
        output = subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "ls-files", "-z", "--", str(root)],
            stderr=subprocess.STDOUT,
        )
        rel_paths = [path for path in output.decode("utf-8").split("\0") if path]
        return [PROJECT_ROOT / rel_path for rel_path in rel_paths]
    except Exception:
        return [
            path
            for path in root.rglob("*")  # nocheck: project-walk
            if path.is_file()
            and ".git" not in path.parts
            and "__pycache__" not in path.parts
        ]


class TestPluginPathsFiles(unittest.TestCase):
    def test_plugin_dirs_contain_only_python(self) -> None:
        dirs = _plugin_dirs()
        self.assertTrue(
            dirs,
            f"No plugin directories resolved from {_ANSIBLE_CFG_PATH}; "
            f"expected at least one of {_PLUGIN_PATH_KEYS!r} to exist.",
        )

        violations: list[str] = []
        for plugin_dir in dirs:
            for path in _tracked_files(plugin_dir):
                if path.name in _ALLOWED_NON_PY:
                    continue
                if path.suffix == ".py":
                    continue
                violations.append(path.relative_to(PROJECT_ROOT).as_posix())

        self.assertEqual(
            sorted(violations),
            [],
            "Tracked files under the Ansible plugin directories declared "
            "in ansible.cfg must end with .py (README.md is allowed).\n"
            "Found:\n" + "\n".join(f"  {path}" for path in sorted(violations)),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
