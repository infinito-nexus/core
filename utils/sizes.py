"""Parse human-readable memory size strings to bytes.

SI/decimal units for the bare suffixes (k=10^3, m=10^6, g=10^9, ...) and IEC
binary for the explicit ``*ib`` suffixes (kib=1024, mib=1024^2, ...). Shared by
the ``node_max_old_space_size`` lookup and the peertube ``install_mem_limit``
filter.
"""

from __future__ import annotations

import re

from ansible.errors import AnsibleFilterError

_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgtp]?i?b?)?\s*$", re.IGNORECASE)
_MULT = {
    "": 1,
    "b": 1,
    "k": 10**3,
    "kb": 10**3,
    "m": 10**6,
    "mb": 10**6,
    "g": 10**9,
    "gb": 10**9,
    "t": 10**12,
    "tb": 10**12,
    "p": 10**15,
    "pb": 10**15,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "pib": 1024**5,
}


def to_bytes(val):
    """Convert a numeric or string size (e.g. '512m', '2GiB', 1024) to bytes.

    Returns None for None/empty input. Raises AnsibleFilterError on an unparseable value.
    """
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return int(val)
    if not isinstance(val, str):
        raise AnsibleFilterError(
            f"to_bytes: unsupported size type: {type(val).__name__}"
        )
    m = _SIZE_RE.match(val)
    if not m:
        raise AnsibleFilterError(f"to_bytes: unrecognized size string: {val!r}")
    num = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit not in _MULT:
        raise AnsibleFilterError(f"to_bytes: unknown unit in size: {unit!r}")
    return int(num * _MULT[unit])


def docker_to_bytes(val):
    """Convert a Docker memory size (``mem_limit``, ``memswap_limit``) to bytes
    the way Docker reads it: every suffix is binary, so ``4g``, ``4gb`` and
    ``4GiB`` are all 4 GiB.

    Args:
        val: the size as Docker accepts it, or a number of bytes.
    """
    if isinstance(val, (int, float)):
        return int(val)
    m = _SIZE_RE.match(val) if isinstance(val, str) else None
    if not m:
        raise AnsibleFilterError(f"docker_to_bytes: unrecognized size: {val!r}")
    prefix = (m.group(2) or "").lower()[:1]
    if prefix in ("", "b"):
        return int(float(m.group(1)))
    return int(float(m.group(1)) * 1024 ** ("kmgtp".index(prefix) + 1))
