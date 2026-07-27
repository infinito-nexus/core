"""Lint: packages are installed through the registry, not the raw module.

``ansible.builtin.package`` and the distro modules take a package name
straight from the task, which is exactly the per-role distro mapping the
``meta/packages.yml`` registry replaces. Roles MUST call ``package_install``
with a logical id instead, so the mapping stays reviewable in one place and
covers every default distribution.

A task whose package name is genuinely dynamic (assembled from inventory
input or a loop variable) cannot carry a static id. Those sites opt out with
``# nocheck: dynamic-package`` on the module line or the line above it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_FORBIDDEN_MODULES = (
    "package",
    "ansible.builtin.package",
    "apt",
    "ansible.builtin.apt",
    "dnf",
    "ansible.builtin.dnf",
    "yum",
    "ansible.builtin.yum",
    "pacman",
    "community.general.pacman",
)

_MODULE_RE = re.compile(
    r"^\s*(?:-\s+)?(?P<module>"
    + "|".join(re.escape(m) for m in _FORBIDDEN_MODULES)
    + r"):\s*$"
)
_NOCHECK_RE = re.compile(r"#\s*nocheck:\s*dynamic-package")


def _role_task_files() -> list[Path]:
    wanted = ("/tasks/", "/handlers/")
    return [
        Path(candidate)
        for candidate in iter_project_files(extensions=(".yml",))
        if str(candidate).startswith(str(PROJECT_ROOT / "roles"))
        and any(part in str(candidate) for part in wanted)
    ]


class TestPackageModuleForbidden(unittest.TestCase):
    def test_roles_install_via_the_registry(self) -> None:
        offenders: list[str] = []
        for path in _role_task_files():
            lines = read_text(str(path)).splitlines()
            for number, line in enumerate(lines, start=1):
                match = _MODULE_RE.match(line)
                if not match:
                    continue
                context = line + "\n" + (lines[number - 2] if number >= 2 else "")
                if _NOCHECK_RE.search(context):
                    continue
                rel = path.relative_to(PROJECT_ROOT)
                offenders.append(f"{rel}:{number}: {match.group('module')}")

        if not offenders:
            return

        self.fail(
            f"{len(offenders)} task(s) install packages directly instead of "
            "through the registry. Declare the package in the owning role's "
            "meta/packages.yml and call:\n"
            "  package_install:\n    id: <package-id>\n"
            "A genuinely dynamic package name opts out with "
            "'# nocheck: dynamic-package'.\n" + "\n".join(f"  - {o}" for o in offenders)
        )


if __name__ == "__main__":
    unittest.main()
