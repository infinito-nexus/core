"""Read a deploy job title back into the axes that built it.

The inverse of what :func:`utils.github.variant.axes.assign` builds, kept in
its own module so the two cannot drift: consumers that hand-rolled a regex over
raw role ids silently matched nothing once job titles carried display names,
and every failure went unreported.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

from utils.github.variant.pools import DISTROS, FILESYSTEMS
from utils.github.variant.vpn import MESH_GLYPH_MODES  # noqa: F401 - re-exported
from utils.roles.display import VARIANT_SEPARATOR
from utils.symbol_glossary import to_emoji, to_word

if TYPE_CHECKING:
    from collections.abc import Sequence

MODES = ("compose", "swarm", "host")

LOCAL_GLYPH = to_emoji("test_host")

_AXIS_GLYPHS = (
    "".join(
        to_emoji(word)
        for word in ("tor", "clearnet", "vpn", "direct", "priority", "instructions")
    )
    + LOCAL_GLYPH
)


def _alternation(words: Sequence[str]) -> str:
    """A regex alternation over the glyphs of *words*."""
    return "|".join(re.escape(to_emoji(word)) for word in words)


LABEL_RE = re.compile(
    r"^.*(?P<mode>" + _alternation(MODES) + r")️?"
    r"(?P<tor>" + re.escape(to_emoji("tor")) + r")?"
    r"(?:" + re.escape(to_emoji("clearnet")) + r"|" + re.escape(LOCAL_GLYPH) + r")?️?"
    r"(?P<vpn>" + re.escape(to_emoji("vpn")) + r")?️?"
    r"(?:" + re.escape(to_emoji("direct")) + r")?️?"
    r"(?P<distro>" + _alternation(DISTROS) + r")?️?"
    r"(?P<filesystem>" + _alternation(FILESYSTEMS) + r")?️?"
    r"[" + re.escape(_AXIS_GLYPHS) + r"️\s]*"
    r"(?P<name>.+?)"
    r"(?:" + re.escape(VARIANT_SEPARATOR) + r"(?P<variant>[0-9,]+))?"
    r"[" + re.escape(_AXIS_GLYPHS) + r"️\s]*$"
)
"""The leading ``.*`` is greedy on purpose: it anchors on the LAST mode glyph.
A reusable-workflow caller path can carry a mode glyph of its own (``z / 💻
Host / 💻 sys-front-proxy``), and matching the first one would swallow the
caller name into the role."""


class Label(NamedTuple):
    """One deploy job title, taken apart."""

    mode: str
    name: str
    variant: str
    tor: bool
    distro: str = ""
    filesystem: str = ""
    vpn: bool = False


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
        match.group("vpn") is not None,
    )
