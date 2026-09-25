"""Resolve a markdown link to a directory against that directory's README.

GitHub renders ``[when](when/)`` by opening the folder and showing its README.
myst only builds a document reference when the target ``is_file()``, so a folder
falls through as an unresolvable reference and reported 2512 of these. Rewriting
the links in the sources instead would have made them uglier in the place they
already work.
"""

from __future__ import annotations

from pathlib import Path

from sphinx import addnodes
from sphinx.transforms.post_transforms import SphinxPostTransform

MYST_RESOLVER_PRIORITY = 9
README = "README.md"


class DirectoryReadme(SphinxPostTransform):
    """Point a link to a directory at the document its README became."""

    default_priority = MYST_RESOLVER_PRIORITY - 1

    def _docname(self, target: str, refdoc: str) -> str:
        """Return the docname of the README backing ``target``, empty when none.

        Args:
            target: the link destination, without its anchor.
            refdoc: the document the link was written in.
        """
        _, path = self.env.relfn2path(target, refdoc)
        readme = Path(path) / README
        return self.env.path2doc(str(readme)) or "" if readme.is_file() else ""

    def run(self, **kwargs) -> None:
        """Rewrite every directory reference that a README backs."""
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
    app.add_post_transform(DirectoryReadme)
    return {"version": "1.0", "parallel_read_safe": True}
