"""One deploy job's title and artifact name: how they are built and read back."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

from utils.github.variant.pools import ARCHITECTURES, DISTROS, FILESYSTEMS, MODES
from utils.roles.display import VARIANT_SEPARATOR
from utils.symbol_glossary import to_emoji, to_word

if TYPE_CHECKING:
    from collections.abc import Sequence

LOCAL_GLYPH = to_emoji("test_host")

_AXIS_GLYPHS = (
    "".join(to_emoji(word) for word in ("tor", "clearnet", "priority", "instructions"))
    + LOCAL_GLYPH
)


def _alternation(words: Sequence[str]) -> str:
    """A regex alternation over the glyphs of *words*."""
    return "|".join(re.escape(to_emoji(word)) for word in words)


LABEL_RE = re.compile(
    r"^.*(?P<mode>" + _alternation(MODES) + r")️?"
    r"(?P<tor>" + re.escape(to_emoji("tor")) + r")?"
    r"(?:" + re.escape(to_emoji("clearnet")) + r"|" + re.escape(LOCAL_GLYPH) + r")?️?"
    r"(?P<distro>" + _alternation(DISTROS) + r")?️?"
    r"(?P<filesystem>" + _alternation(FILESYSTEMS) + r")?️?"
    r"(?P<architecture>" + _alternation(ARCHITECTURES) + r")?️?"
    r"[" + re.escape(_AXIS_GLYPHS) + r"️\s]*"
    r"(?P<name>.+?)"
    r"(?:" + re.escape(VARIANT_SEPARATOR) + r"(?P<variant>[0-9,]+))?"
    r"[" + re.escape(_AXIS_GLYPHS) + r"️\s]*$"
)


class Label(NamedTuple):
    """One deploy job title, taken apart."""

    mode: str
    name: str
    variant: str
    tor: bool
    distro: str = ""
    filesystem: str = ""
    architecture: str = ""


def parse_label(name: str) -> Label | None:
    """Take a deploy job title apart.

    The inverse of what :func:`assign` builds, kept next to it so the two
    cannot drift: consumers that hand-rolled their own regex over raw role
    ids silently matched nothing once job titles carried display names, and
    every failure went unreported.

    Args:
        name: the job title, with or without a reusable-workflow caller path
            in front of it.

    Returns:
        ``None`` when the title carries no deploy row. ``name`` is the display
        name, returned unresolved -- callers decode it through
        ``utils.roles.display``, which is what knows the role tree. ``tor``,
        ``distro`` and ``filesystem`` matter because a priority role runs the
        same mode and variant several times over, and only the glyphs tell
        those jobs apart -- a retrigger built from the title alone would
        otherwise replay a different combination than the one that failed.
    """
    match = LABEL_RE.match(name.strip())
    if match is None:
        return None
    return Label(
        to_word(match.group("mode")),
        match.group("name").strip(),
        match.group("variant") or "",
        match.group("tor") is not None,
        to_word(match.group("distro") or ""),
        to_word(match.group("filesystem") or ""),
        to_word(match.group("architecture") or ""),
    )


def artifact_slug(
    mode: str,
    app: str,
    variant: str,
    tor: bool,
    distro: str = "",
    filesystem: str = "",
    architecture: str = "",
) -> str:
    """What identifies one deploy job's artifacts.

    Built here rather than as a workflow expression so the matrix entry and
    every consumer read the same string: a priority role runs the same mode
    and variant twice, once behind the onion and once not, and two jobs
    uploading under one name is an artifact conflict, not an overwrite. The
    distro and filesystem are in it for the same reason -- a selection may
    name one row on two distros (``role#0%debian role#0%fedora``), and those
    are two deploys of one mode, variant and onion state.
    """
    shards = (variant, "tor" if tor else "", distro, filesystem, architecture)
    return f"{mode}-{app}" + "".join(f"-{shard}" for shard in shards if shard)
