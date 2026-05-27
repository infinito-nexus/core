"""Lint guard: ``pkgmgr`` / ``pkgmgr-install`` role includes are
deprecated. Prefer ``pip install`` against the upstream PyPI release
(or, where the package is not yet on PyPI, ``pip install git+<repo>``)
so the venv-based bootstrap chain shrinks.

This check is **warn-only**: it never fails the test session. It
surfaces each unmarked usage twice — once via :mod:`warnings` (lands in
pytest's "warnings summary" locally) and once via a GitHub Actions
``::warning file=…,line=…::…`` workflow command (renders as a yellow
PR-side annotation in CI). Suppression via ``# nocheck: pkgmgr-deprecated``
removes the entry from both surfaces.

Why
---

``pkgmgr`` (Kevin's package-manager, https://github.com/kevinveenbirkenbach/package-manager,
published to PyPI as ``kpmx``) clones each managed tool into a venv at
runtime. That is heavier than a single ``pip install`` for the subset
of tools that ship a ``pyproject.toml`` and a PyPI release. New roles
SHOULD reach for ``pip`` directly; existing roles SHOULD carry an
explicit opt-out marker until they are migrated, so the warning chatter
stays focused on freshly introduced usages.

Migration cheat-sheet
---------------------

Already on PyPI (drop-in ``pip install <name>``):

* ``pkgmgr`` → ``pip install kpmx``
* ``doli``   → ``pip install docoli``

Python with ``pyproject.toml`` but not on PyPI
(``pip install git+<repo>``):

* ``infinito`` → ``pip install git+https://github.com/kevinveenbirkenbach/infinito-nexus-core.git``

Still single-file Python scripts (would need packaging upstream first):
``btrfs-auto-balancer``, ``swap-forge``, ``docodol``, ``certreap``,
``unsure``, ``certbundle``.

Definitively not pip-installable: ``cli-gnome-extension-manager``
(Bash), ``infinito-presentation`` (Flask + Docker container app).

Suppression
-----------

Per-line opt-out via ``# nocheck: pkgmgr-deprecated`` on the
``name: pkgmgr`` / ``name: pkgmgr-install`` line itself or on the
preceding non-empty line. Use until the role's installer is migrated
to ``pip install``.

Detection
---------

Scan every ``.yml`` / ``.yaml`` file in the project. A line whose
trimmed content is exactly ``name: pkgmgr`` or ``name: pkgmgr-install``
(with optional trailing comment) is treated as an ``include_role`` /
``import_role`` target for the deprecated installer and warned about
unless the line carries the suppression marker.
"""

from __future__ import annotations

import re
import unittest
import warnings
from pathlib import Path

from utils.annotations.message import in_github_actions
from utils.annotations.message import warning as gha_warning
from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

# A line declaring ``pkgmgr`` or ``pkgmgr-install`` as a bare YAML
# identifier value. Matches:
#   ``    name: pkgmgr-install``
#   ``  name: pkgmgr  # nocheck: pkgmgr-deprecated``
# Does NOT match string values like:
#   ``- name: "pkgmgr install '{{ FOO }}'"``
_PKGMGR_NAME_RE = re.compile(r"^\s*name:\s*(pkgmgr|pkgmgr-install)\s*(#.*)?$")

_SCAN_EXTENSIONS = (".yml", ".yaml")

_RULE = "pkgmgr-deprecated"

_THIS_FILE = Path(__file__).resolve()

_TITLE = "Deprecated pkgmgr role include"

_MIGRATION_HINT = (
    "Prefer pip: pkgmgr -> 'pip install kpmx'; "
    "doli -> 'pip install docoli'; "
    "infinito -> 'pip install git+https://github.com/"
    "kevinveenbirkenbach/infinito-nexus-core.git'. "
    "Suppress with '# nocheck: pkgmgr-deprecated' if intentional."
)


class PkgmgrDeprecatedWarning(DeprecationWarning):
    """Warning category for deprecated ``pkgmgr`` role includes."""


def _emit(path_rel: str, line_no: int, snippet: str) -> None:
    body = (
        f"deprecated 'pkgmgr' / 'pkgmgr-install' role include "
        f"({snippet}). {_MIGRATION_HINT}"
    )
    # Local: pytest renders this in its end-of-session "warnings summary"
    # block regardless of capture mode.
    warnings.warn(
        f"{path_rel}:{line_no}: {body}", PkgmgrDeprecatedWarning, stacklevel=2
    )
    # CI: shared annotation helper writes a structured
    # ``::warning title=...,file=...,line=...::body`` directive that
    # Actions renders with title / file / line columns — matching every
    # other lint's PR-side annotation surface.
    if in_github_actions():
        gha_warning(body, title=_TITLE, file=path_rel, line=line_no)


class TestPkgmgrDeprecated(unittest.TestCase):
    """Warn-only lint: never fails, just surfaces ``pkgmgr`` usages."""

    def test_warns_about_unmarked_pkgmgr_role_usage(self) -> None:
        for path_str in iter_project_files(extensions=_SCAN_EXTENSIONS):
            path = Path(path_str)
            if path.resolve() == _THIS_FILE:
                continue
            try:
                text = read_text(path_str)
            except (OSError, UnicodeDecodeError):
                continue
            if "pkgmgr" not in text:
                continue

            lines = text.splitlines()
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            for idx, line in enumerate(lines, start=1):
                if not _PKGMGR_NAME_RE.match(line):
                    continue
                if is_suppressed_at(lines, idx, _RULE):
                    continue
                _emit(rel, idx, line.strip())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
