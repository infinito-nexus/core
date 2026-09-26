"""Resolve a markdown link to a directory against that directory's index page.

GitHub renders ``[when](when/)`` by opening the folder and showing its README.
myst only builds a document reference when the target ``is_file()``, so a folder
falls through as an unresolvable reference. Rewriting the links in the sources
instead would have made them uglier in the place they already work.

``index`` is tried before ``README`` because that is the order the navigation
uses: ``local.file_headings`` drops README.md from a directory that carries an
index.rst, so resolving a link the other way round would send the reader to a
page its own sidebar hides.
"""

from __future__ import annotations

from pathlib import Path

from sphinx import addnodes
from sphinx.transforms.post_transforms import SphinxPostTransform

MYST_RESOLVER_PRIORITY = 9
INDEX_FILES = ("index.rst", "index.md", "README.md", "README.rst")


class DirectoryIndex(SphinxPostTransform):
    """Point a link to a directory at the document that stands in for it."""

    default_priority = MYST_RESOLVER_PRIORITY - 1

    def _docname(self, target: str, refdoc: str) -> str:
        """Return the docname of the page backing ``target``, empty when none.

        Args:
            target: the link destination, without its anchor.
            refdoc: the document the link was written in.
        """
        _, path = self.env.relfn2path(target, refdoc)
        for name in INDEX_FILES:
            candidate = Path(path) / name
            if candidate.is_file():
                return self.env.path2doc(str(candidate)) or ""
        return ""

    def run(self, **kwargs) -> None:
        """Rewrite every directory reference that an index page backs."""
        for node in self.document.findall(addnodes.pending_xref):
            if node.get("reftype") != "myst" or node.get("refdomain") is not None:
                continue
            target, _, anchor = node["reftarget"].partition("#")
            docname = self._docname(target, node.get("refdoc", self.env.docname))
            if not docname:
                continue
            node["refdomain"] = "doc"
            node["reftarget"] = docname
            node["reftargetid"] = anchor or None


def setup(app):
    app.add_post_transform(DirectoryIndex)
    return {"version": "1.0", "parallel_read_safe": True}
