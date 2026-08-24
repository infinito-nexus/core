"""Lint: a role's ``files/`` sorts its scripts by language.

``.js`` belongs in ``files/javascript/``, ``.sh`` in ``files/shell/``, ``.php``
in ``files/php/``, ``.py`` in ``files/python/``, ``.rb`` in ``files/ruby/`` and
``.sql`` in ``files/sql/``. The last two are already the house style - every
``.sql`` and most ``.rb`` sit there today; this lint keeps them there. Without
it, a role's
``files/`` becomes a flat pile where the only way to tell a deploy hook from a
test fixture is to open it - and tooling that keys on the path (eslint scopes
``roles/**/files/**`` by directory, for one) cannot tell them apart either.

Exemption
---------

Some directories under ``files/`` are trees whose shape is dictated from
outside: a Playwright suite the runner discovers by path, a WordPress
mu-plugin, a Joomla extension, an app with its own entry point. Sorting those
by extension would break them.

Such a directory carries a ``.nocheck`` file whose contents state why, and
everything at or below it is exempt. The rationale is mandatory - an empty
marker is a failure of this lint, because an exemption nobody can review is
indistinguishable from an oversight.

Find every exemption with::

    find roles -name .nocheck -path '*/files/*'
"""

from __future__ import annotations

import unittest
from collections import defaultdict
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text

ROLES = PROJECT_ROOT / "roles"
MARKER = ".nocheck"
RULE = "role-files-layout"
HOME = {
    ".js": "javascript",
    ".sh": "shell",
    ".php": "php",
    ".py": "python",
    ".rb": "ruby",
    ".sql": "sql",
}


def _sorted_files():
    """Yield ``(path, segments)`` for every file this lint governs.

    :return: iterator of the file and its path segments below ``files/``
    """
    for raw in sorted(iter_project_files(extensions=tuple(HOME))):
        path = Path(raw)
        if ROLES not in path.parents:
            continue
        parts = path.relative_to(ROLES).parts
        if "files" not in parts:
            continue
        yield path, parts[parts.index("files") + 1 :]


def _markers():
    """Yield every ``.nocheck`` marker that sits under a role's ``files/``.

    :return: sorted iterator of marker paths
    """
    return sorted(
        marker
        for raw in iter_project_files()
        if (marker := Path(raw)).name.endswith(MARKER)
        and ROLES in marker.parents
        and "files" in marker.relative_to(ROLES).parts
    )


def _exempting_marker(path):
    """Return the ``.nocheck`` that exempts ``path`` from THIS rule, or ``None``.

    A marker written for another lint does not exempt this one, so the rule
    name is required rather than the file's mere presence.
    """
    beside = path.with_name(path.name + MARKER)
    if beside.is_file() and f"nocheck: {RULE}" in read_text(str(beside)):
        return beside

    for parent in path.parents:
        marker = parent / MARKER
        if marker.is_file() and f"nocheck: {RULE}" in read_text(str(marker)):
            return marker
        if parent.name == "files":
            return None
    return None


class TestRoleFilesLayout(unittest.TestCase):
    def test_every_script_sits_under_its_language(self) -> None:
        misplaced = defaultdict(list)
        for path, segments in _sorted_files():
            if _exempting_marker(path):
                continue
            if segments[:1] == (HOME[path.suffix],):
                continue
            misplaced[path.suffix].append(str(path.relative_to(PROJECT_ROOT)))

        report = "\n".join(
            f"{suffix} belongs in files/{HOME[suffix]}/:\n  " + "\n  ".join(paths)
            for suffix, paths in sorted(misplaced.items())
        )
        self.assertFalse(misplaced, f"\n{report}")

    def test_every_exemption_says_why(self) -> None:
        empty = []
        for marker in _markers():
            if "files" not in marker.relative_to(ROLES).parts:
                continue
            if len(read_text(str(marker)).strip()) < 20:
                empty.append(str(marker.relative_to(PROJECT_ROOT)))

        self.assertFalse(
            empty,
            "an exemption nobody can review is indistinguishable from an oversight:\n  "
            + "\n  ".join(empty),
        )

    def test_no_exemption_covers_an_empty_directory(self) -> None:
        governed = {path for path, _ in _sorted_files()}
        idle = []
        for marker in _markers():
            if "files" not in marker.relative_to(ROLES).parts:
                continue
            if not any(marker.parent in path.parents for path in governed):
                idle.append(str(marker.relative_to(PROJECT_ROOT)))

        self.assertFalse(
            idle, "these exemptions no longer cover anything:\n  " + "\n  ".join(idle)
        )


if __name__ == "__main__":
    unittest.main()
