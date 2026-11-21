from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

builders = importlib.import_module("infinito_docs.commands")


class TestProgress(unittest.TestCase):
    def test_sphinx_phases_map_onto_one_rising_bar(self) -> None:
        lines = [
            "Running Sphinx v9.1.0",
            "reading sources... [ 50%] a .. b",
            "writing output... [100%] c",
            "reading sources... [100%] late line",
            "postprocess html... [ 50%] /out/html/x.html",
        ]
        progress, seen = 0, []
        for line in lines:
            progress = builders.progress_of(line, progress)
            seen.append(progress)

        self.assertEqual(seen, [0, 25, 60, 60, 79])

    def test_generators_run_in_order_without_the_checkout_on_sys_path(self) -> None:
        commands = builders.generate_commands(Path("/w/src"))

        self.assertEqual(
            commands[0],
            [
                sys.executable,
                "-m",
                "sphinx.ext.apidoc",
                "-f",
                "-o",
                "/w/src/generated/modules",
                "/w/src",
                "/w/src/tests",
                "/w/src/roles",
                "/w/src/library",
            ],
        )
        self.assertEqual(
            [command[3] for command in commands[1:]],
            [
                "infinito_docs.generators.yaml_index",
                "infinito_docs.generators.ansible_roles",
                "infinito_docs.generators.index",
                "infinito_docs.generators.roles_overview",
                "infinito_docs.generators.make_targets",
                "infinito_docs.generators.aliases",
                "infinito_docs.generators.cli_commands",
                "infinito_docs.generators.integrations",
                "infinito_docs.generators.licensing",
                "infinito_docs.generators.readmes",
                "cli.build.docs.readme",
                "cli.build.docs.readme.overview",
            ],
        )
        self.assertTrue(all(command[1] == "-P" for command in commands[1:]))

    def test_the_readme_generators_write_only_inside_the_checkout(self) -> None:
        commands = builders.generate_commands(Path("/w/src"))
        targets = [arg for command in commands[-2:] for arg in command[4:]]

        self.assertEqual(
            targets,
            [
                "--override",
                "--roles-dir",
                "/w/src/roles",
                "--readme",
                "/w/src/README.md",
                "--roles-dir",
                "/w/src/roles",
            ],
        )


class TestLifecycleDiagramStep(unittest.TestCase):
    def _checkout(self, *, spot: bool, generator: bool) -> Path:
        root = Path(self._tmp.name) / f"src-{spot}-{generator}"
        if spot:
            path = root.joinpath(*builders.LIFECYCLE_SPOT)
            path.parent.mkdir(parents=True)
            path.write_text("statuses: {}\n", encoding="utf-8")
        if generator:
            package = root.joinpath(*builders.LIFECYCLE_MODULE.split("."))
            package.mkdir(parents=True)
            (package / "__main__.py").write_text("", encoding="utf-8")
        root.mkdir(exist_ok=True)
        return root

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_a_new_checkout_renders_the_diagram_last(self) -> None:
        commands = builders.generate_commands(self._checkout(spot=True, generator=True))
        self.assertEqual(
            [sys.executable, "-P", "-m", builders.LIFECYCLE_MODULE], commands[-1]
        )

    def test_an_old_checkout_builds_unchanged(self) -> None:
        reference = builders.generate_commands(Path("/w/src"))
        for spot, generator in ((False, False), (True, False), (False, True)):
            with self.subTest(spot=spot, generator=generator):
                root = self._checkout(spot=spot, generator=generator)
                modules = [c[3] for c in builders.generate_commands(root)[1:]]
                self.assertNotIn(builders.LIFECYCLE_MODULE, modules)
                self.assertEqual(len(reference), len(modules) + 1)


class TestHeaderTrustTableStep(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _checkout(self, *, generator: bool) -> Path:
        root = Path(self._tmp.name) / f"src-{generator}"
        root.mkdir()
        if generator:
            package = root.joinpath(*builders.HEADER_TRUST_MODULE.split("."))
            package.mkdir(parents=True)
            (package / "__main__.py").write_text("", encoding="utf-8")
        return root

    def test_a_new_checkout_renders_the_table_into_its_own_rbac_doc(self) -> None:
        root = self._checkout(generator=True)
        self.assertEqual(
            [
                sys.executable,
                "-P",
                "-m",
                builders.HEADER_TRUST_MODULE,
                "--doc",
                str(root / "docs/contributing/design/iam/rbac.md"),
                "--roles-dir",
                str(root / "roles"),
            ],
            builders.generate_commands(root)[-1],
        )

    def test_an_old_checkout_builds_unchanged(self) -> None:
        modules = [
            command[3]
            for command in builders.generate_commands(self._checkout(generator=False))[
                1:
            ]
        ]
        self.assertNotIn(builders.HEADER_TRUST_MODULE, modules)

    def test_the_inputs_ship_in_the_snapshot(self) -> None:
        role_vars = load_yaml(
            str(PROJECT_ROOT / "roles" / "web-app-docs" / ROLE_FILE_VARS_MAIN)
        )
        self.assertLessEqual(
            {builders.HEADER_TRUST_DOC[0], "roles", "utils"},
            set(role_vars["DOCS_SNAPSHOT_PATHS"]),
        )


class TestSnapshotCoversEveryGeneratorInput(unittest.TestCase):
    """``/snapshot`` is a tar of ``DOCS_SNAPSHOT_PATHS``, so a generator
    reaching for a path the list omits dies with FileNotFoundError.

    That failure is invisible: ``_failed`` only writes a state file and
    ``library.status`` omits the ``deployed`` version, so the suite polls a
    dead build for its whole budget. Two missing entries cost three hours.
    """

    ROOT = Path("/w/src")
    BUILT = "generated"

    def snapshot_paths(self) -> set[str]:
        role_vars = load_yaml(
            str(PROJECT_ROOT / "roles" / "web-app-docs" / ROLE_FILE_VARS_MAIN)
        )
        return set(role_vars["DOCS_SNAPSHOT_PATHS"])

    def test_every_generator_path_under_src_is_in_the_snapshot(self) -> None:
        needed: set[str] = set()
        for argv in builders.generate_commands(self.ROOT):
            for argument in argv:
                text = str(argument)
                if not text.startswith(str(self.ROOT)):
                    continue
                parts = Path(text).relative_to(self.ROOT).parts
                if parts and parts[0] != self.BUILT:
                    needed.add(parts[0])

        missing = sorted(needed - self.snapshot_paths())
        self.assertEqual(
            missing,
            [],
            "generate_commands() reaches for these repository paths but "
            "DOCS_SNAPSHOT_PATHS does not ship them, so the deployed build "
            f"dies before sphinx runs: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
