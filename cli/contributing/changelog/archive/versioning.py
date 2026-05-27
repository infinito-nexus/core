"""Version-string padding and the archive filename schema.

Archive files are named ``<padded-semver>-<date>.md`` so that a plain
directory listing already sorts them in chronological order. The
padding zero-fills each numeric component of the semver to three
digits, so ``7.0.0`` becomes ``007.000.000``. Pre-release and build
suffixes (``1.2.3-rc1``, ``1.2.3+meta``) are preserved verbatim and
tacked onto the padded core version.
"""

from __future__ import annotations

import re

_NUMERIC_COMPONENT_RE = re.compile(r"^\d+$")


def pad_version(version: str) -> str:
    """Zero-pad each numeric component of *version* to three digits."""
    parts = re.split(r"([-+])", version, maxsplit=1)
    core = parts[0]
    sep = parts[1] if len(parts) > 1 else ""
    suffix = parts[2] if len(parts) > 2 else ""
    padded = ".".join(
        c.zfill(3) if _NUMERIC_COMPONENT_RE.match(c) else c for c in core.split(".")
    )
    return f"{padded}{sep}{suffix}"


def unpad_version(padded: str) -> str:
    """Inverse of :func:`pad_version`. ``007.000.000`` → ``7.0.0``."""
    parts = re.split(r"([-+])", padded, maxsplit=1)
    core = parts[0]
    sep = parts[1] if len(parts) > 1 else ""
    suffix = parts[2] if len(parts) > 2 else ""
    unpadded = ".".join(
        (c.lstrip("0") or "0") if _NUMERIC_COMPONENT_RE.match(c) else c
        for c in core.split(".")
    )
    return f"{unpadded}{sep}{suffix}"


def archive_filename(version: str, date: str) -> str:
    """Return the canonical archive filename for ``(version, date)``."""
    return f"{pad_version(version)}-{date}.md"
