from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
