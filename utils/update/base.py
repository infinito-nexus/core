"""Semver primitives shared by every version-bump backend.

A "version" here is a tag of the shape ``v?<numeric-semver>(-<flavor>)?``,
where the numeric part has 1 to 4 dot-separated components and the
optional ``-<flavor>`` suffix is an opaque discriminator (e.g. the
Docker Official Image tag ``5.4.5-php8.3-apache`` or the npm-style
``1.2.3-alpha``).

Upgrade candidates MUST share the same depth (1, 2, 3 or 4 components)
AND the same flavor as the current tag, so that ``5.4.5-php8.3-apache``
never silently bumps to ``5.4.6-php8.4-apache`` (different runtime) or
to ``5.4.6`` (different depth).
"""

from __future__ import annotations

import os
import re

_SEMVER_CORE = r"v?\d+(?:\.\d+){0,3}"
_VERSIONED_TAG_RE = re.compile(rf"^(?P<semver>{_SEMVER_CORE})(?P<flavor>-\S+)?$")


def _parse_versioned_tag(tag: str) -> tuple[str, str] | None:
    match = _VERSIONED_TAG_RE.match(str(tag).strip())
    if match is None:
        return None
    return match.group("semver"), match.group("flavor") or ""


def is_semver(value: str) -> bool:
    return _parse_versioned_tag(value) is not None


def version_key(tag: str) -> tuple[int, ...]:
    parsed = _parse_versioned_tag(tag)
    if parsed is None:
        return (0,) * 4
    semver, _flavor = parsed
    parts = tuple(int(part) for part in semver.lstrip("v").split("."))
    return parts + (0,) * (4 - len(parts))


def version_depth(tag: str) -> int:
    parsed = _parse_versioned_tag(tag)
    if parsed is None:
        return 0
    semver, _flavor = parsed
    return len(semver.lstrip("v").split("."))


def version_flavor(tag: str) -> str:
    """Return the ``-<flavor>`` suffix of a versioned tag, or "" when none."""
    parsed = _parse_versioned_tag(tag)
    return parsed[1] if parsed else ""


def latest_semver(tags: list[str], depth: int, flavor: str = "") -> str | None:
    candidates = [
        tag
        for tag in tags
        if is_semver(tag)
        and version_depth(tag) == depth
        and version_flavor(tag) == flavor
    ]
    return max(candidates, key=version_key, default=None)


def resolve_max_fetch_workers() -> int:
    return int(os.environ["INFINITO_WORKER_FETCH"])
