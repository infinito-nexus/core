"""Semver primitives shared by every version-bump backend.

A "version" here is a tag of the shape
``(<channel>-)?v?<numeric-semver><patch>?(-<flavor>)?``, where the numeric part
has 1 to 5 dot-separated components, the optional leading ``<channel>-`` is a
release line written before the number (e.g. the LiteLLM tag
``main-v1.77.7-stable`` or the Jitsi tag ``stable-9646``), the optional
``<patch>`` is a vendor counter written as a letter and a number (e.g. the
Checkmk tag ``2.4.0p32``), and the optional ``-<flavor>`` suffix is an opaque
discriminator (e.g. the Docker Official Image tag ``5.4.5-php8.3-apache`` or
the npm-style ``1.2.3-alpha``).

Upgrade candidates MUST share the same depth (1 to 5 components) AND the same
flavor as the current tag, so that ``5.4.5-php8.3-apache`` never silently bumps
to ``5.4.6-php8.4-apache`` (different runtime) or to ``5.4.6`` (different
depth). Everything that is not the number folds into the flavor: the leading
channel, the trailing suffix and the patch letter. That is what keeps
``main-v1.77.7-stable`` away from ``main-v1.77.7-nightly``, ``stable-9646``
away from a bare ``9646``, and ``2.4.0p32`` ordering against ``2.4.0p33``
rather than against the four-component ``2.4.0.32``. Only the patch number
joins the ordering key, so ``p9`` sorts below ``p10``.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from utils.roles.meta_lookup import get_role_lifecycle

if TYPE_CHECKING:
    from pathlib import Path

UNMAINTAINED_LIFECYCLES = frozenset({"eol"})
_SEMVER_CORE = r"v?\d+(?:\.\d+){0,4}"
_VERSIONED_TAG_RE = re.compile(
    rf"^(?P<channel>[A-Za-z][A-Za-z0-9]*-)?(?P<semver>{_SEMVER_CORE})"
    rf"(?P<patch>[A-Za-z]\d+)?(?P<flavor>-\S+)?$"
)


def _parse_versioned_tag(tag: str) -> tuple[str, str, int | None] | None:
    match = _VERSIONED_TAG_RE.match(str(tag).strip())
    if match is None:
        return None
    patch = match.group("patch")
    flavor = (
        (match.group("channel") or "")
        + (match.group("flavor") or "")
        + (patch[0] if patch else "")
    )
    return match.group("semver"), flavor, int(patch[1:]) if patch else None


def is_semver(value: str) -> bool:
    return _parse_versioned_tag(value) is not None


def version_key(tag: str) -> tuple[int, ...]:
    parsed = _parse_versioned_tag(tag)
    if parsed is None:
        return (0,) * 4
    semver, _flavor, patch = parsed
    parts = tuple(int(part) for part in semver.lstrip("v").split("."))
    padded = parts + (0,) * (4 - len(parts))
    return padded if patch is None else (*padded, patch)


def version_depth(tag: str) -> int:
    parsed = _parse_versioned_tag(tag)
    if parsed is None:
        return 0
    semver, _flavor, _patch = parsed
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


def captured_versions(body: str, pattern: str, template: str = "") -> list[str]:
    """Return the version every match of a pattern names.

    Args:
        body: text to search.
        pattern: regular expression; its first group is the version.
        template: when set, a ``str.format`` template over the pattern's named
            groups that assembles the version instead, for a tag built from
            several upstream values.
    """
    return [
        template.format(**match.groupdict()) if template else match.group(1)
        for match in re.finditer(pattern, body)
    ]


def newer_version(current: str, found: list[str], assembled: bool) -> str | None:
    """Return the version *current* should move to, or ``None``.

    Args:
        current: the pinned version.
        found: every version the upstream offers.
        assembled: *found* was built from several upstream values, so a
            changed suffix is a move and not another flavour.
    """
    if assembled:
        newest = max(filter(is_semver, found), key=version_key, default=None)
        moved = newest not in (None, current)
    else:
        newest = latest_semver(found, version_depth(current), version_flavor(current))
        moved = bool(newest) and version_key(current) != version_key(newest)
    return newest if moved and version_key(current) <= version_key(newest) else None


def resolve_max_fetch_workers() -> int:
    return int(os.environ["INFINITO_WORKER_FETCH"])


def is_maintained(roles_root: Path, role: str) -> bool:
    """Return whether the version-bump backends watch a role.

    Args:
        roles_root: the ``roles/`` directory that holds the role.
        role: role name, the directory name under ``roles_root``.
    """
    lifecycle = get_role_lifecycle(roles_root / role, role_name=role)
    return lifecycle not in UNMAINTAINED_LIFECYCLES


def declares_source(config: object, key: str) -> bool:
    """Report whether a services entity names its own upstream for a pin.

    Args:
        config: one entity of ``meta/services.yml``.
        key: the pinned key; an ``update:`` block without ``key`` names
            ``version``.
    """
    declared = config.get("update") if isinstance(config, dict) else None
    sources = declared if isinstance(declared, list) else [declared]
    return any(
        isinstance(source, dict) and source.get("key", "version") == key
        for source in sources
    )
