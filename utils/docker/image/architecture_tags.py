from __future__ import annotations

from collections.abc import Mapping

PREFIX = "prefix"
REPLACEMENT = "replacement"


def _mapping(rewrites: object) -> Mapping:
    if not isinstance(rewrites, Mapping):
        raise TypeError(
            f"architecture_tags is a {type(rewrites).__name__}, not a mapping"
        )
    return rewrites


def _rewrite(architecture: str, rewrite: object) -> tuple[str, str]:
    if not isinstance(rewrite, Mapping):
        raise TypeError(
            f"architecture_tags.{architecture} is a {type(rewrite).__name__}, "
            f"not a mapping of {PREFIX} and {REPLACEMENT}"
        )
    prefix, replacement = (str(rewrite.get(key) or "") for key in (PREFIX, REPLACEMENT))
    if not prefix or not replacement:
        raise ValueError(
            f"architecture_tags.{architecture} needs a non-empty {PREFIX} and "
            f"{REPLACEMENT}"
        )
    return prefix, replacement


def architecture_tag(version: str, architecture: str, rewrites: object) -> str:
    """
    Args:
        version: the one tag the service pins in ``version``.
        architecture: the OCI architecture of the node that pulls the image,
            such as ``amd64`` or ``arm64``.
        rewrites: the service's ``architecture_tags``, mapping an architecture
            to the ``prefix`` of ``version`` its own tag swaps for
            ``replacement``; empty or None when every architecture pulls
            ``version``.

    Returns:
        The tag *architecture* pulls: ``version`` with its prefix rewritten
        for an architecture that has a rewrite, ``version`` itself otherwise.

    Raises:
        TypeError: *rewrites* or its rewrite for *architecture* is no mapping.
        ValueError: the rewrite for *architecture* lacks a prefix or a
            replacement, or *version* does not start with that prefix, as
            after a bump to a tag of another shape.
    """
    if not rewrites:
        return version
    rewrites = _mapping(rewrites)
    if architecture not in rewrites:
        return version
    prefix, replacement = _rewrite(architecture, rewrites[architecture])
    if not version.startswith(prefix):
        raise ValueError(
            f"version {version!r} does not start with {prefix!r}, so its "
            f"{architecture} tag cannot be derived from it"
        )
    return replacement + version[len(prefix) :]


def architecture_tags(version: str, rewrites: object) -> dict[str, str]:
    """
    Args:
        version: the one tag the service pins in ``version``.
        rewrites: the service's ``architecture_tags``, as `architecture_tag`
            reads them.

    Returns:
        The derived tag of every architecture with a rewrite, keyed by
        architecture; empty when every architecture pulls ``version``.

    Raises:
        TypeError: as `architecture_tag` raises it.
        ValueError: as `architecture_tag` raises it.
    """
    if not rewrites:
        return {}
    rewrites = _mapping(rewrites)
    return {
        str(architecture): architecture_tag(version, str(architecture), rewrites)
        for architecture in rewrites
    }
