"""The role README lint exempts a custom role from the Infinito.Nexus licence only."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.lint.ansible.roles import test_readme as lint
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_README

AUTHOR = "Jane Doe"
IMPLEMENTED = f"Implemented by **{AUTHOR}**.\n"
PROJECT = (
    "Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) "
    "and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).\n"
)
INFINITO_LICENSE = (
    "Licensed under the [Infinito.Nexus Community License (Non-Commercial)]"
    "(https://s.infinito.nexus/license).\n"
)
OWN_LICENSE = "Licensed under the [MIT License](https://opensource.org/licenses/MIT).\n"
TAIL_PROBLEM = "Credits tail does not match the canonical wording"


class TestCreditsLicence(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.roles = Path(tmp.name)

    def _problems(self, role: str, *lines: str) -> list[str]:
        readme = self.roles / role / ROLE_FILE_README
        meta = readme.parent / ROLE_FILE_META_MAIN
        meta.parent.mkdir(parents=True)
        meta.write_text(f"galaxy_info:\n  author: {AUTHOR}\n", encoding="utf-8")
        text = "## Credits\n\n" + "".join(lines)
        readme.write_text(text, encoding="utf-8")
        return lint._validate_credits(text, readme)

    def test_a_custom_role_with_its_own_licence_passes(self) -> None:
        self.assertEqual(
            [],
            self._problems("web-app-cst-demo", IMPLEMENTED, PROJECT, OWN_LICENSE),
        )

    def test_an_in_tree_role_without_the_infinito_licence_fails(self) -> None:
        problems = self._problems("web-app-demo", IMPLEMENTED, PROJECT, OWN_LICENSE)
        self.assertTrue(any(TAIL_PROBLEM in problem for problem in problems))

    def test_an_in_tree_role_with_the_infinito_licence_passes(self) -> None:
        self.assertEqual(
            [],
            self._problems("web-app-demo", IMPLEMENTED, PROJECT, INFINITO_LICENSE),
        )

    def test_a_custom_role_without_the_project_line_still_fails(self) -> None:
        problems = self._problems("web-app-cst-demo", IMPLEMENTED, OWN_LICENSE)
        self.assertTrue(any(TAIL_PROBLEM in problem for problem in problems))

    def test_a_custom_role_still_needs_the_author_spot(self) -> None:
        problems = self._problems(
            "web-app-cst-demo", "Implemented by **Someone Else**.\n", PROJECT
        )
        self.assertTrue(any("galaxy_info.author" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
