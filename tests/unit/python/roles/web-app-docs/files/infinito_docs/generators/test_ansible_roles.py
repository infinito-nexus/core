from __future__ import annotations

import importlib
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_README

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

ansible_roles = importlib.import_module("infinito_docs.generators.ansible_roles")


class TestAnsibleRoles(unittest.TestCase):
    @patch.object(ansible_roles.subprocess, "run")
    def test_markdown_is_converted_through_pandoc(self, run: MagicMock) -> None:
        run.return_value = MagicMock(stdout=b"RST\n")

        self.assertEqual(ansible_roles.convert_md_to_rst("# Title\n"), "RST\n")
        self.assertEqual(
            run.call_args.args[0], ["pandoc", "-f", "markdown", "-t", "rst"]
        )

    @patch.object(ansible_roles.subprocess, "run")
    def test_failed_conversion_keeps_the_markdown(self, run: MagicMock) -> None:
        run.side_effect = subprocess.CalledProcessError(1, ["pandoc"])

        self.assertEqual(ansible_roles.convert_md_to_rst("# Title\n"), "# Title\n")

    @patch.object(ansible_roles.subprocess, "run")
    def test_one_page_per_role_with_meta(self, run: MagicMock) -> None:
        run.return_value = MagicMock(stdout=b"Converted README\n")

        with TemporaryDirectory() as td:
            roles = Path(td) / "roles"
            meta_file = roles / "web-app-demo" / ROLE_FILE_META_MAIN
            meta_file.parent.mkdir(parents=True)
            meta_file.write_text(
                "galaxy_info:\n  description: Demo role\n  license: MIT\n",
                encoding="utf-8",
            )
            (roles / "web-app-demo" / ROLE_FILE_README).write_text(
                "# Demo\n", encoding="utf-8"
            )
            (roles / "no-meta").mkdir()

            ansible_roles.generate_ansible_roles_doc(roles, Path(td) / "out")

            self.assertEqual(
                sorted(p.name for p in (Path(td) / "out").iterdir()),
                ["web-app-demo.rst"],
            )
            page = read_text(str(Path(td) / "out" / "web-app-demo.rst"))

        self.assertTrue(page.startswith("Web-app-demo Role\n" + "=" * 19 + "\n\n"))
        self.assertIn("**Description:** Demo role\n", page)
        self.assertIn("- **license**: MIT\n", page)
        self.assertTrue(page.endswith("\nREADME\n------\n\nConverted README\n"))

    @patch.object(ansible_roles.subprocess, "run")
    def test_a_block_scalar_stays_on_its_bullet(self, run: MagicMock) -> None:
        run.return_value = MagicMock(stdout=b"Converted README\n")

        with TemporaryDirectory() as td:
            roles = Path(td) / "roles"
            meta_file = roles / "web-app-demo" / ROLE_FILE_META_MAIN
            meta_file.parent.mkdir(parents=True)
            meta_file.write_text(
                "galaxy_info:\n  company: |\n    Kevin Veen-Birkenbach\n"
                "    https://www.veen.world\n",
                encoding="utf-8",
            )

            ansible_roles.generate_ansible_roles_doc(roles, Path(td) / "out")

            page = read_text(str(Path(td) / "out" / "web-app-demo.rst"))

        self.assertIn(
            "- **company**: Kevin Veen-Birkenbach https://www.veen.world\n",
            page,
            "almost every role declares company as a block scalar, and its second "
            "line landed in column 0, which ends the bullet list it sits in",
        )


if __name__ == "__main__":
    unittest.main()
