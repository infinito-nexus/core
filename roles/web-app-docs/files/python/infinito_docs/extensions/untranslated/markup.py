"""Keep a message no translator can act on out of the translation catalogs.

A table cell holding only ``[`e2e/`](e2e/)`` has nothing to translate, yet it
becomes a msgid like any sentence: 2999 of the docs domain's 25742 messages,
11.7 percent, were of that kind. A heading that is nothing but ``Mastodon`` is
the same case for a different reason: the product is called that in every
language. Both count as pending for good and skew every completeness figure.

The messages are taken from sphinx's own ``extract_messages``, which is what the
gettext builder collects, so the transform judges exactly the strings that would
otherwise reach the catalog. The predicate is ``untranslatable``, the one the
translation client applies before it sends a batch, so both ends share one
definition.

The documentation site builds arbitrary refs. A ref older than ``utils/i18n/``
cannot supply the predicate, and the transform then does nothing, which leaves
that build exactly as it was before this extension existed.
"""

from __future__ import annotations

from docutils import nodes
from sphinx.transforms import SphinxTransform
from sphinx.util.nodes import extract_messages

try:
    from utils.i18n.untranslatable import untranslatable
except ImportError:
    untranslatable = None

LOCALE_TRANSFORM_PRIORITY = 10


class UntranslatedMarkup(SphinxTransform):
    """Mark every extracted message without a word untranslatable."""

    default_priority = LOCALE_TRANSFORM_PRIORITY - 5

    def apply(self, **kwargs) -> None:
        """Flag the nodes whose message is markup and punctuation only."""
        if untranslatable is None:
            return
        for node, message in extract_messages(self.document):
            if isinstance(node, nodes.image) or not isinstance(node, nodes.Element):
                continue
            if untranslatable(message):
                node["translatable"] = False


def setup(app):
    app.add_transform(UntranslatedMarkup)
    return {"version": "1.0", "parallel_read_safe": True}
