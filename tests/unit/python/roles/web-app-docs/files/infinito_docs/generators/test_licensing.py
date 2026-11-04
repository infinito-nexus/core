from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_LICENSE

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

licensing = importlib.import_module("infinito_docs.generators.licensing")

_AGPL = "---\nspdx: AGPL-3.0-or-later\nurl: https://example.invalid/COPYING\n"
_MIT = "---\nspdx: MIT\nurl: https://example.invalid/LICENSE\n"
_NOTHING = "# nocheck: license-declared installs nothing of its own\n---\n"

_INLINE = (
    "---\nspdx: LicenseRef-Probe-EULA\nurl: https://example.invalid/eula\nrights:\n"
    + "\n".join(
        f"  {field}: {'true' if field in ('private_use', 'self_host', 'commercial_use') else 'false'}"
        for field in (
            "commercial_use",
            "modifications",
            "distribution",
            "private_use",
            "patent_use",
            "self_host",
            "include_copyright",
            "document_changes",
            "disclose_source",
            "network_use_disclose",
            "same_license",
            "liability",
            "warranty",
            "trademark_use",
            "open_source",
        )
    )
)


def _render(roles: dict[str, str]) -> str:
    """Render the page for *roles* and return it.

    Args:
        roles: ``{role name: body of its meta/license.yml}``; an empty body
            declares no licence file at all.
    """
    with TemporaryDirectory() as tmp:
        roles_dir = Path(tmp) / "roles"
        for name, body in roles.items():
            path = roles_dir / name / ROLE_FILE_META_LICENSE
            path.parent.mkdir(parents=True)
            if body:
                path.write_text(body, encoding="utf-8")
        output = Path(tmp) / "out" / "licensing.rst"
        licensing.generate(roles_dir, output)
        return read_text(str(output))


class TestLicensingGenerator(unittest.TestCase):
    def test_a_role_is_grouped_by_the_context_its_rights_derive(self):
        page = _render({"web-app-alpha": _AGPL, "web-app-beta": _MIT})
        self.assertIn("Network copyleft", page)
        self.assertIn("Permissive", page)
        self.assertIn("AGPL-3.0-or-later", page)
        self.assertIn("MIT", page)

    def test_the_matrix_carries_one_column_per_right(self):
        page = _render({"web-app-alpha": _MIT})
        header = page[page.index("* - Role") : page.index("* - ``web-app-alpha``")]
        self.assertEqual(len(licensing.COLUMNS) + 1, header.count("     - "))

    def test_an_agpl_role_is_marked_as_owing_network_disclosure(self):
        page = _render({"web-app-alpha": _AGPL})
        row = page[page.index("* - ``web-app-alpha``") :]
        cells = [
            line.strip()[2:]
            for line in row.splitlines()[1:]
            if line.startswith("     - ")
        ]
        index = [field for field, _ in licensing.COLUMNS].index("network_use_disclose")
        self.assertEqual("yes", cells[index + 1])

    def test_a_right_the_licence_withholds_renders_as_a_word(self):
        page = _render({"web-app-alpha": _MIT})
        row = page[page.index("* - ``web-app-alpha``") :]
        cells = [
            line.strip()[2:]
            for line in row.splitlines()[1:]
            if line.startswith("     - ")
        ]
        index = [field for field, _ in licensing.COLUMNS].index("patent_use")
        self.assertEqual("no", cells[index + 1])

    def test_inline_rights_resolve_without_a_table_entry(self):
        page = _render({"web-app-alpha": _INLINE})
        self.assertIn("web-app-alpha", page)
        self.assertNotIn("Not yet determined", page)

    def test_a_role_without_a_licence_file_is_listed_as_undetermined(self):
        page = _render({"web-app-alpha": ""})
        self.assertIn("Not yet determined", page)
        self.assertIn("web-app-alpha", page)

    def test_a_role_that_deploys_nothing_is_not_reported_as_a_gap(self):
        page = _render({"web-app-alpha": _NOTHING})
        self.assertIn("Deploying no third-party software", page)
        self.assertNotIn("Not yet determined", page)

    def test_a_non_invokable_role_is_left_off_the_page(self):
        page = _render({"web-app-alpha": _MIT, "sys-ctl-cln-gamma": _MIT})
        self.assertIn("web-app-alpha", page)
        self.assertNotIn("sys-ctl-cln-gamma", page)


if __name__ == "__main__":
    unittest.main()
