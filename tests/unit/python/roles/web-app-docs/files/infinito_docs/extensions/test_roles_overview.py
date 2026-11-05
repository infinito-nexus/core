from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from docutils import nodes

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

roles_overview = importlib.import_module("infinito_docs.extensions.roles_overview")


class _Reporter:
    def error(self, message, *args, **kwargs):
        return ("ERROR", message)


def _directive(srcdir: str):
    return roles_overview.RolesOverviewDirective(
        name="roles-overview",
        arguments=[],
        options={},
        content=[],
        lineno=1,
        content_offset=0,
        block_text=".. roles-overview::",
        state=SimpleNamespace(
            document=SimpleNamespace(
                settings=SimpleNamespace(env=SimpleNamespace(srcdir=srcdir)),
                reporter=_Reporter(),
            )
        ),
        state_machine=SimpleNamespace(reporter=_Reporter()),
    )


def _role(name, title, description):
    return {
        "name": name,
        "title": title,
        "description": description,
        "link": f"roles/{name}/README.md",
        "tags": [],
    }


class TestRolesOverview(unittest.TestCase):
    def test_categories_and_roles_render_sorted_with_links(self) -> None:
        overview = {
            "wiki": [_role("web-app-demo", "Demo Title", "Demo role")],
            "Docs": [
                _role("web-app-zeta", "Zeta", ""),
                _role("web-app-demo", "Demo Title", "Demo role"),
            ],
        }
        with TemporaryDirectory() as td:
            target = Path(td) / roles_overview.OVERVIEW_FILE
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(overview), encoding="utf-8")

            (container,) = _directive(td).run()

        sections = {
            section[0].astext(): [role[0].astext() for role in section[1:]]
            for section in container.children
        }
        self.assertEqual(
            sections, {"Docs": ["Demo Title", "Zeta"], "wiki": ["Demo Title"]}
        )
        self.assertEqual(
            [section[0].astext() for section in container.children], ["Docs", "wiki"]
        )
        reference = next(iter(container.findall(nodes.reference)))
        self.assertEqual(reference["refuri"], "roles/web-app-demo/README.md")
        self.assertEqual(
            [paragraph.astext() for paragraph in container.findall(nodes.paragraph)],
            ["Demo role", "Demo role"],
        )

    def test_missing_overview_reports_an_error(self) -> None:
        with TemporaryDirectory() as td:
            (result,) = _directive(td).run()

        self.assertEqual(result, ("ERROR", "Roles overview not generated."))


if __name__ == "__main__":
    unittest.main()
