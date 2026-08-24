"""Lint guard: baudolo is pinned to one version, and core agrees with it.

`svc-bkp-volume-2-local` pip-installs baudolo on the target host, while
`[project.dependencies]` declares it for the control host. Two pins mean the
code that reads a backup can be a different version from the one that wrote it,
and the mismatch surfaces as a restore that finds nothing.

`utils.recovery.layout` spells the generation layout out as literals, because
`recover device|nfs|secrets|volume` runs on hosts that carry a git checkout and
no baudolo. This is where that copy is held to baudolo's own `BackupPaths`, so
the literals cannot drift from the tool that writes them.
"""

from __future__ import annotations

import re
import tomllib
import unittest
from importlib.metadata import PackageNotFoundError, version
from pathlib import PurePath

from utils.cache.files import read_text
from utils.recovery import layout

from . import PROJECT_ROOT

_PACKAGE = "backup-docker-to-local"
_PYPROJECT = PROJECT_ROOT / "pyproject.toml"
_INSTALL_TASK = PROJECT_ROOT / "roles/svc-bkp-volume-2-local/tasks/01_install.yml"
_TASK_PIN_RE = re.compile(rf"{re.escape(_PACKAGE)}==([0-9][^\"'\s]*)")


def _declared_pin() -> str | None:
    data = tomllib.loads(read_text(str(_PYPROJECT)))
    for requirement in data.get("project", {}).get("dependencies", []):
        if requirement.startswith(f"{_PACKAGE}=="):
            return requirement.split("==", 1)[1].strip()
    return None


class TestBaudoloPin(unittest.TestCase):
    def test_the_role_installs_the_declared_version(self) -> None:
        declared = _declared_pin()
        self.assertIsNotNone(
            declared,
            f"{_PACKAGE} must be pinned in [project.dependencies] of {_PYPROJECT}",
        )

        found = _TASK_PIN_RE.findall(read_text(str(_INSTALL_TASK)))
        self.assertEqual(
            found,
            [declared],
            f"{_INSTALL_TASK} pins {found}, while pyproject.toml declares "
            f"'{declared}'. Both must name the same version.",
        )

    def test_baudolo_is_installed_here(self) -> None:
        try:
            version(_PACKAGE)
        except PackageNotFoundError:
            self.fail(
                f"{_PACKAGE} is declared in {_PYPROJECT} but not installed for this "
                f"interpreter, so the layout assertion below would be vacuous. Run "
                f"'make install-python-dev'."
            )

    def test_the_manifest_contract_matches_baudolo(self) -> None:
        from baudolo import generation

        self.assertEqual(layout.MANIFEST_FILE, generation.MANIFEST_FILE)
        self.assertEqual(layout.MANIFEST_SCHEMA, generation.MANIFEST_SCHEMA)

    def test_the_layout_literals_match_baudolo(self) -> None:
        from baudolo.restore.paths import BackupPaths

        installed = version(_PACKAGE)
        paths = BackupPaths("", "", "", repo_name="", backups_dir="")
        for name, ours, theirs in (
            ("SQL_DIR", layout.SQL_DIR, PurePath(paths.sql_file("")).parent.name),
            ("FILES_DIR", layout.FILES_DIR, PurePath(paths.files_dir()).name),
            ("DUMP_SUFFIX", layout.DUMP_SUFFIX, PurePath(paths.sql_file("")).name),
            (
                "CLUSTER_SUFFIX",
                layout.CLUSTER_SUFFIX,
                PurePath(paths.cluster_file("")).name,
            ),
        ):
            with self.subTest(constant=name):
                self.assertEqual(
                    ours,
                    theirs,
                    f"utils.recovery.layout.{name} is '{ours}', while "
                    f"{_PACKAGE} {installed} writes '{theirs}'. A restore would "
                    f"look in the wrong place; update the literal, do not import "
                    f"baudolo here.",
                )

    def test_the_layout_module_imports_nothing(self) -> None:
        source = read_text(str(PROJECT_ROOT / "utils/recovery/layout.py"))
        offenders = [
            line
            for line in source.splitlines()
            if re.match(r"^\s*(import|from)\s", line) and "__future__" not in line
        ]
        self.assertEqual(
            offenders,
            [],
            "utils/recovery/layout.py must stay import-free: it is read on swarm "
            "nodes, the NFS server and rescue hosts that have nothing but a git "
            f"checkout. Found {offenders}.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
