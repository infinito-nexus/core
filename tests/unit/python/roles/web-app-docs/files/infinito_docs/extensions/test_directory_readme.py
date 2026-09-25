from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path

from docutils.frontend import get_default_settings
from docutils.parsers.rst import Parser
from docutils.utils import new_document
from sphinx import addnodes

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

directory_readme = importlib.import_module(
    "infinito_docs.extensions.directory_readme"
)

REFDOC = "docs/index"


class _Env:
    """The three env members the transform reads, backed by a real tree."""

    def __init__(self, srcdir: Path, docnames: set[str]):
        self.srcdir = srcdir
        self.docname = REFDOC
        self.all_docs = dict.fromkeys(docnames, 0)

    def relfn2path(self, target: str, _docname: str):
        absolute = (self.srcdir / target).resolve()
        return target, str(absolute)

    def path2doc(self, path: str) -> str | None:
        relative = Path(path).resolve().relative_to(self.srcdir)
        return str(relative.with_suffix("")) if relative.suffix == ".md" else None


def _xref(target: str, refdomain=None) -> addnodes.pending_xref:
    return addnodes.pending_xref(
        reftype="myst", refdomain=refdomain, reftarget=target, refdoc=REFDOC
    )


class TestDirectoryReadme(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="infinito-dirreadme-")
        self.src = Path(self._tmp.name).resolve()
        (self.src / "guide").mkdir()
        (self.src / "guide" / "README.md").write_text("# Guide\n", encoding="utf-8")
        (self.src / "empty").mkdir()
        self.addCleanup(self._tmp.cleanup)

    def _run(self, node) -> None:
        document = new_document("/src/docs/index.md", get_default_settings(Parser))
        document.settings.env = _Env(self.src, {"guide/README"})
        document.append(node)
        directory_readme.DirectoryReadme(document).run()

    def test_a_directory_link_resolves_to_its_readme(self) -> None:
        node = _xref("guide/")

        self._run(node)

        self.assertEqual(node["refdomain"], "doc")
        self.assertEqual(node["reftarget"], "guide/README")

    def test_the_transform_reads_the_domain_myst_actually_sets(self) -> None:
        node = _xref("guide/", refdomain=None)

        self._run(node)

        self.assertEqual(
            node["reftarget"],
            "guide/README",
            "myst builds a doc reference only when the target is_file(), so a "
            "directory arrives with refdomain None; filtering on 'doc' made an "
            "earlier version of this transform do nothing at all",
        )

    def test_an_anchor_survives_the_rewrite(self) -> None:
        node = _xref("guide/#usage")

        self._run(node)

        self.assertEqual(node["reftarget"], "guide/README")
        self.assertEqual(node["reftargetid"], "usage")

    def test_a_directory_without_a_readme_is_left_to_be_reported(self) -> None:
        node = _xref("empty/")

        self._run(node)

        self.assertIsNone(node["refdomain"])
        self.assertEqual(node["reftarget"], "empty/")

    def test_a_reference_of_another_type_is_untouched(self) -> None:
        node = _xref("guide/")
        node["reftype"] = "ref"

        self._run(node)

        self.assertEqual(node["reftarget"], "guide/")

    def test_it_runs_before_the_myst_resolver(self) -> None:
        from myst_parser.sphinx_ext.myst_refs import MystReferenceResolver

        self.assertLess(
            directory_readme.DirectoryReadme.default_priority,
            MystReferenceResolver.default_priority,
        )


if __name__ == "__main__":
    unittest.main()
