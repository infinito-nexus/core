"""Hand every node of a translated message over to the page it was patched into."""

from __future__ import annotations

from sphinx.transforms import SphinxTransform
from sphinx.transforms.i18n import Locale


class AdoptTranslatedNodes(SphinxTransform):
    """Point each node that still names its msgstr's own document at the page."""

    default_priority = Locale.default_priority + 1

    def apply(self, **kwargs) -> None:
        """Rebind every node whose document is not the page being read."""
        for node in self.document.findall():
            if node.document is not self.document:
                node.document = self.document


def setup(app):
    app.add_transform(AdoptTranslatedNodes)
    return {"version": "1.0", "parallel_read_safe": True}
