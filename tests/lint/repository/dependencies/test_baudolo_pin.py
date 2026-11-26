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

import ast
import tomllib
import unittest
import unittest.mock as mock
from importlib.metadata import PackageNotFoundError, version
from pathlib import PurePath

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar, trust_as_template

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.recovery import layout

from . import PROJECT_ROOT

_PACKAGE = "backup-docker-to-local"
_PYPROJECT = PROJECT_ROOT / "pyproject.toml"
_INSTALL_TASK = PROJECT_ROOT / "roles/svc-bkp-volume-2-local/tasks/01_install.yml"
_INSTALLER = "sys-pip-install"
_LOOKED_UP = "looked-up-"


class _Version(LookupBase):
    def run(self, terms, *_args, **_kwargs):
        return [f"{_LOOKED_UP}{term}" for term in terms]


def _declared_pin() -> str | None:
    data = tomllib.loads(read_text(str(_PYPROJECT)))
    for requirement in data.get("project", {}).get("dependencies", []):
        if requirement.startswith(f"{_PACKAGE}=="):
            return requirement.split("==", 1)[1].strip()
    return None


def _installed_requirement() -> str:
    """Returns:
    The requirement the install task hands to the pip installer, rendered
    with a ``version`` lookup that answers ``looked-up-<distribution>``.
    """
    task = next(
        task
        for task in load_yaml_any(str(_INSTALL_TASK))
        if (task.get("include_role") or {}).get("name") == _INSTALLER
    )
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name == "version":
            return _Version()
        return real_get(name, *args, **kwargs)

    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return Templar(loader=DataLoader()).template(
            trust_as_template(task["vars"]["package_name"])
        )


class TestBaudoloPin(unittest.TestCase):
    def test_the_role_installs_the_declared_version(self) -> None:
        declared = _declared_pin()
        self.assertIsNotNone(
            declared,
            f"{_PACKAGE} must be pinned in [project.dependencies] of {_PYPROJECT}",
        )
        self.assertEqual(
            _installed_requirement(),
            f"{_PACKAGE}=={_LOOKED_UP}{_PACKAGE}",
            f"{_INSTALL_TASK} must install {_PACKAGE} at "
            f"lookup('version', '{_PACKAGE}'), the pin of pyproject.toml. A "
            f"literal pin is bumped by the pip pin updater while dependabot "
            f"bumps pyproject.toml, each on its own.",
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
        from baudolo import generation
        from baudolo.restore.paths import BackupPaths

        installed = version(_PACKAGE)
        paths = BackupPaths("", "", "", repo_name="", backups_dir="")
        for name, ours, theirs in (
            (
                "COMPRESSED_SUFFIX",
                layout.COMPRESSED_SUFFIX,
                generation.COMPRESSED_SUFFIX,
            ),
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
        tree = ast.parse(read_text(str(PROJECT_ROOT / "utils/recovery/layout.py")))
        offenders = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            or (isinstance(node, ast.ImportFrom) and node.module != "__future__")
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
