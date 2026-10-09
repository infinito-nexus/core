"""Generators that derive documentation pages from the sources they describe."""

from __future__ import annotations

import re

_INLINE = re.compile(r"([*`|_])")


def literal(text: str) -> str:
    """Return ``text`` safe to drop into an RST body as plain prose.

    The prose comes from a Makefile comment, an alias comment or a module
    docstring, which nobody writes as RST. A single ``*.pyc`` is harmless, but
    a second one on the same line opens an emphasis that never closes and the
    build reports it; the same holds for a backtick, a pipe in a table cell and
    a trailing underscore, which reads as a link reference.

    Args:
        text: the prose to escape.
    """
    return _INLINE.sub(r"\\\1", text)
