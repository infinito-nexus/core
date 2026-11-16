from __future__ import annotations

import re

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}|sha512:[0-9a-f]{128}")


def valid_digest(value: object) -> str | None:
    """
    Args:
        value: a ``digest`` field or ``Docker-Content-Digest`` header.

    Returns:
        ``value`` when it is ``sha256:`` or ``sha512:`` with lowercase hex of
        the matching length, else ``None``.
    """
    if isinstance(value, str) and _DIGEST_RE.fullmatch(value):
        return value
    return None
