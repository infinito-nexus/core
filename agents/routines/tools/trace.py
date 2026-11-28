"""Playwright trace reader: turn trace events into the navigation chain, and
read a ``Set-Cookie`` header into its attributes. The cookie reader returns the
attributes only (Path, HttpOnly, SameSite, Secure, ...) and never the cookie's
name or value, so a trace dump cannot spill a session token.
"""

from __future__ import annotations

_NAV_TYPES = {"navigate", "navigated"}


def navigation_chain(entries: list[dict]) -> list[str]:
    """Return the navigated URLs, in order, from a list of trace entries.

    A navigation entry has ``type`` in ``{"navigate", "navigated"}`` and a
    ``url``; every other entry is ignored.

    Args:
        entries: the trace events read out of a Playwright ``trace.zip``.
    """
    return [
        entry["url"]
        for entry in entries
        if entry.get("type") in _NAV_TYPES and entry.get("url")
    ]


def cookie_attributes(set_cookie: str) -> dict[str, str]:
    """Return the attributes of a ``Set-Cookie`` header as a name/value map;
    flag attributes (``HttpOnly``, ``Secure``) map to an empty string.

    The leading ``name=value`` pair that carries the cookie's own name and
    value is dropped, so it never appears in the result.

    Args:
        set_cookie: the raw ``Set-Cookie`` header value.
    """
    attributes: dict[str, str] = {}
    for raw in set_cookie.split(";")[1:]:
        segment = raw.strip()
        if not segment:
            continue
        key, sep, value = segment.partition("=")
        attributes[key.strip()] = value.strip() if sep else ""
    return attributes
