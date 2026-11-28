from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable

SCHEME = "https"
BASE_SCHEMES = frozenset({"http", SCHEME})
SHELL_DEFAULT_BASE = f"{SCHEME}:/"
SLASH = "/"
HUB = "huggingface.co"
HUB_KINDS = frozenset({"datasets", "spaces"})
HUB_RESOLVE = "resolve"
GITHUB_RAW = "raw.githubusercontent.com"
GITHUB = "github.com"
GITHUB_RELEASE = ("releases", "download")
RELEASE_TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
ARGOS_NET = "argos-net.com"
ARGOS_VERSION = re.compile(r"[0-9]+_[0-9]+(?:_[0-9]+)?")
ARGOS_FILE = re.compile(rf"[A-Za-z0-9._~-]+-({ARGOS_VERSION.pattern})\.argosmodel")
TREE = "tree"
UNPACKED = "argos-packages"


def path_segments(path: str) -> list[str]:
    """
    Args:
        path: the path of a URL, empty or starting with a slash.

    Returns:
        Its segments after the leading slash; empty for an empty path.
    """
    return path.split("/")[1:] if path else []


def _hub_ref(segments: list[str]) -> str:
    resolve = 3 if segments[:1] and segments[0] in HUB_KINDS else 2
    if (
        len(segments) < resolve + 3
        or segments[resolve] != HUB_RESOLVE
        or segments.count(HUB_RESOLVE) != 1
    ):
        return ""
    return segments[resolve + 1]


def _github_raw_ref(segments: list[str]) -> str:
    return segments[2] if len(segments) > 3 else ""


def _argos_ref(segments: list[str]) -> str:
    match = ARGOS_FILE.fullmatch(segments[-1]) if segments else None
    return match.group(1) if match else ""


def _github_release_ref(segments: list[str]) -> str:
    if len(segments) != 6 or tuple(segments[2:4]) != GITHUB_RELEASE:
        return ""
    return segments[4]


REF_OF: dict[str, Callable[[list[str]], str]] = {
    HUB: _hub_ref,
    GITHUB_RAW: _github_raw_ref,
    GITHUB: _github_release_ref,
    ARGOS_NET: _argos_ref,
}

REVISION_OF: dict[str, tuple[re.Pattern[str], str]] = {
    GITHUB: (RELEASE_TAG, "a release tag"),
    ARGOS_NET: (ARGOS_VERSION, "a <major>_<minor>[_<patch>] package version"),
}


def _base_problem(base: str) -> str:
    if not (base.isascii() and base.isprintable()) or " " in base:
        return "carries whitespace, a control or a non-ASCII character"
    if "?" in base or "#" in base:
        return "carries a query or a fragment"
    if "%" in base:
        return "carries a percent escape"
    if base.endswith(SLASH):
        return "ends in a slash"
    try:
        parts = urlsplit(base)
    except ValueError:
        return "is not a URL"
    if parts.scheme not in BASE_SCHEMES or not parts.hostname:
        return "is not an http or https URL with a host"
    if "@" in parts.netloc:
        return "carries userinfo"
    try:
        valid_port = parts.port != 0
    except ValueError:
        valid_port = False
    return "" if valid_port else "carries a port outside 1 to 65535"


def checked_base(base: str) -> str:
    """
    Args:
        base: the value of ``INFINITO_ARTEFACT_BASE``.

    Returns:
        *base* itself.

    Raises:
        ValueError: *base* is malformed, as `url_for` refuses it.
    """
    if base in ("", SHELL_DEFAULT_BASE):
        return base
    problem = _base_problem(base)
    if problem:
        raise ValueError(f"INFINITO_ARTEFACT_BASE {base!r} {problem}")
    return base


def url_for(url: str, base: str) -> str:
    """
    Args:
        url: the pinned upstream URL.
        base: the value of ``INFINITO_ARTEFACT_BASE``; empty keeps the upstream.

    Returns:
        ``<base>/<host>/<path>``, or *url* itself for an empty base.

    Raises:
        ValueError: *base* is neither empty, ``https:/``, nor an http or https
            URL with a host and a port from 1 to 65535 if any, free of whitespace,
            query, fragment, percent escape, userinfo and a trailing slash.
    """
    if not checked_base(base):
        return url
    parts = urlsplit(url)
    return f"{base}/{parts.netloc}{parts.path}"


def tree_path(url: str) -> str:
    """
    Args:
        url: the pinned upstream URL.

    Returns:
        ``tree/<host>/<path>``, where the store links the file under its
        upstream name, so an engine reads a repository directory offline.
    """
    parts = urlsplit(url)
    return f"{TREE}/{parts.netloc}{parts.path}"


def tree_root(url: str) -> str:
    """
    Args:
        url: a pinned upstream URL the contract accepts.

    Returns:
        Its ``tree_path`` up to and including the ref segment, the directory
        an engine loads the pinned repository from; for a host whose ref sits
        in the file name, the file's directory.
    """
    parts = urlsplit(url)
    segments = path_segments(parts.path)
    ref = REF_OF[parts.hostname or ""](segments)
    cut = segments.index(ref) + 1 if ref in segments else len(segments) - 1
    return "/".join([TREE, parts.netloc, *segments[:cut]])


def unpack_path(url: str, sha256: str) -> str:
    """
    Args:
        url: the pinned upstream URL.
        sha256: the digest of the file it names.

    Returns:
        ``argos-packages/<sha256>``, where the store unpacks an Argos package
        once, or empty for a file an engine reads as it is.
    """
    return f"{UNPACKED}/{sha256}" if urlsplit(url).hostname == ARGOS_NET else ""
