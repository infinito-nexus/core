"""Keep a message that carries no word out of the translation catalogs.

A table cell holding only ``[`e2e/`](e2e/)`` has nothing to translate, yet it
becomes a msgid like any sentence: 2999 of the docs domain's 25742 messages,
11.7 percent, are of that kind. They can never be filled, so they count as
pending for good and skew every completeness figure.

The messages are taken from sphinx's own ``extract_messages``, which is what the
gettext builder collects, so the transform judges exactly the strings that would
otherwise reach the catalog. The predicate is ``has_words``, the one the
translation client already applies before it sends a batch, so both ends share
one definition of translatable.

The documentation site builds arbitrary refs. A ref older than ``utils/i18n/``
cannot supply the predicate, and the transform then does nothing, which leaves
that build exactly as it was before this extension existed.
"""

from __future__ import annotations

from docutils import nodes
from sphinx.transforms import SphinxTransform
from sphinx.util.nodes import extract_messages

try:
    from utils.i18n.placeholders import has_words
except ImportError:
    has_words = None

LOCALE_TRANSFORM_PRIORITY = 10


class UntranslatedMarkup(SphinxTransform):
    """Mark every extracted message without a word untranslatable."""

    default_priority = LOCALE_TRANSFORM_PRIORITY - 5

    def apply(self, **kwargs) -> None:
        """Flag the nodes whose message is markup and punctuation only."""
        if has_words is None:
            return
        for node, message in extract_messages(self.document):
            if isinstance(node, nodes.image) or not isinstance(node, nodes.Element):
                continue
            if not has_words(message):
                node["translatable"] = False


def setup(app):
    app.add_transform(UntranslatedMarkup)
    return {"version": "1.0", "parallel_read_safe": True}
