# filter_plugins/xwiki_filters.py
from __future__ import annotations

import re


def xwiki_extension_status(raw: str) -> int:
    """
    Parse the output of the Groovy CheckExtension page.

    - Strips HTML tags and entities (&nbsp;)
    - Returns 200 if extension is INSTALLED, otherwise 404

    Args:
        raw: Raw HTTP body from the checker page.

    Returns:
        200 if installed, 404 if missing/unknown.
    """
    if raw is None:
        return 404

    text = re.sub(r"<[^>]+>", "", str(raw))
    text = text.replace("&nbsp;", " ").replace("\u00a0", " ")
    text = text.strip()

    if text.startswith("INSTALLED::"):
        return 200
    return 404


class FilterModule:
    """Custom filters for XWiki helpers."""

    def filters(self):
        return {
            "xwiki_extension_status": xwiki_extension_status,
        }
