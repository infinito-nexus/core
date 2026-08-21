"""Read the deploy axes an operator pins in ``whitelist`` and ``priority``.

A selection token names a role and MAY narrow the axes that role's rows would
otherwise be assigned: which variants run, which deploy mode, whether the row
goes behind the node onion, which distribution it deploys on and which
filesystem its docker data root runs on. What a token leaves open stays open,
exactly as an unpinned run leaves it: the priority line covers every mode and
onion state the row can take, and the sweep rotation picks the distro and the
filesystem on both lines.

Two spellings are accepted, so an operator can either type the token or paste
back the job title of the run they want repeated:

* the job label CI emits (``🐳🧅🌀🦓网络应用·Nextcloud#2``) -- the glyphs carry
  mode, onion state, distro and filesystem, the ``#`` shard the variants;
* an ASCII form (``web-app-nextcloud#0,2@swarm+tor%debian/zfs``).

The onion state spells out as ``+tor``/``+clearnet`` rather than as a ``-tor``
suffix: a role id may itself end in ``-tor`` (``svc-net-tor``), and a suffix
that eats the tail of a role name selects a different role in silence.

Everything a token pins is checked against what the row can actually do
(:func:`utils.github.variant.axes.assign`) and against the run's own mode and
tor inputs. A contradiction aborts the matrix instead of quietly deploying
something else or nothing at all.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

from utils.github.variant.axes import DISTROS, FILESYSTEMS, MODES
from utils.roles.display import VARIANT_SEPARATOR, display_names
from utils.symbol_glossary import to_emoji

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from typing import Any

MODE_SEPARATOR = "@"

TOR_SEPARATOR = "+"

DISTRO_SEPARATOR = "%"

FILESYSTEM_SEPARATOR = "/"

TOR_WORDS = {"tor": True, "clearnet": False}

_STRIPPED_GLYPHS = ("priority", "test_host")

_VARIATION = re.compile("[︎️]")

_SEPARATORS = (
    VARIANT_SEPARATOR
    + MODE_SEPARATOR
    + TOR_SEPARATOR
    + DISTRO_SEPARATOR
    + FILESYSTEM_SEPARATOR
)

_TOKEN = re.compile(
    r"^(?P<name>[^" + re.escape(_SEPARATORS) + r"\s]+)"
    r"(?:" + re.escape(VARIANT_SEPARATOR) + r"(?P<variants>\d+(?:,\d+)*))?"
    r"(?:" + re.escape(MODE_SEPARATOR) + r"(?P<mode>[a-z]+))?"
    r"(?:" + re.escape(TOR_SEPARATOR) + r"(?P<tor>[a-z]+))?"
    r"(?:" + re.escape(DISTRO_SEPARATOR) + r"(?P<distro>[a-z0-9]+))?"
    r"(?:" + re.escape(FILESYSTEM_SEPARATOR) + r"(?P<filesystem>[a-z0-9]+))?$"
)

_SYNTAX = (
    f"<role>[{VARIANT_SEPARATOR}<variant,variant>]"
    f"[{MODE_SEPARATOR}<{'|'.join(MODES)}>]"
    f"[{TOR_SEPARATOR}<{'|'.join(TOR_WORDS)}>]"
    f"[{DISTRO_SEPARATOR}<{'|'.join(DISTROS)}>]"
    f"[{FILESYSTEM_SEPARATOR}<{'|'.join(FILESYSTEMS)}>]"
)


class Pin(NamedTuple):
    """One selection token, taken apart.

    ``variants`` empty and ``mode``/``tor``/``distro``/``filesystem`` ``None``
    each mean "not pinned": that axis keeps whatever the line it stands in
    would assign.
    """

    app: str
    variants: tuple[int, ...] = ()
    mode: str | None = None
    tor: bool | None = None
    distro: str | None = None
    filesystem: str | None = None

    @property
    def pinned(self) -> bool:
        """Whether the token narrows anything at all beyond the role name."""
        return bool(self.variants) or any(
            axis is not None
            for axis in (self.mode, self.tor, self.distro, self.filesystem)
        )

    @property
    def axes(self) -> tuple[str | None, bool | None, str | None, str | None]:
        """What the token narrows, as the key two tokens are equal under."""
        return (self.mode, self.tor, self.distro, self.filesystem)


def describe(pin: Pin) -> str:
    """The token as an operator would have written it, for error messages."""
    variants = ",".join(str(index) for index in pin.variants)
    return (
        pin.app
        + (f"{VARIANT_SEPARATOR}{variants}" if variants else "")
        + (f"{MODE_SEPARATOR}{pin.mode}" if pin.mode else "")
        + (
            f"{TOR_SEPARATOR}{'tor' if pin.tor else 'clearnet'}"
            if pin.tor is not None
            else ""
        )
        + (f"{DISTRO_SEPARATOR}{pin.distro}" if pin.distro else "")
        + (f"{FILESYSTEM_SEPARATOR}{pin.filesystem}" if pin.filesystem else "")
    )


def _word_glyph(text: str, words: Iterable[str]) -> tuple[str, str | None]:
    """Strip whichever of *words* the text carries as a glyph, and name it."""
    found: str | None = None
    for word in words:
        glyph = to_emoji(word)
        if glyph in text:
            found, text = word, text.replace(glyph, "")
    return text, found


def _glyphs(text: str) -> tuple[str, str | None, bool | None, str | None, str | None]:
    """Take the label glyphs off a pasted job title and read them as axes."""
    text, mode = _word_glyph(text, MODES)
    text, onion = _word_glyph(text, TOR_WORDS)
    text, distro = _word_glyph(text, DISTROS)
    text, filesystem = _word_glyph(text, FILESYSTEMS)
    for word in _STRIPPED_GLYPHS:
        text = text.replace(to_emoji(word), "")
    return (
        text.strip(),
        mode,
        None if onion is None else TOR_WORDS[onion],
        distro,
        filesystem,
    )


def _agree(pin: Any, glyph: Any, token: str, axis: str) -> Any:
    """One axis stated twice must state the same thing."""
    if pin is not None and glyph is not None and pin != glyph:
        raise SystemExit(
            f"selection token {token!r} pins two different {axis} values; "
            f"drop one of them"
        )
    return glyph if pin is None else pin


def parse(token: str) -> Pin:
    """One selection token as a :class:`Pin`.

    Args:
        token: label form or ASCII form; a bare role id or display name pins
            nothing and selects every row of that role.

    Raises:
        SystemExit: the token is unparsable, or names a mode or onion state
            that does not exist. A typo must abort the run rather than narrow
            it to nothing.
    """
    text, glyph_mode, glyph_tor, glyph_distro, glyph_fs = _glyphs(
        _VARIATION.sub("", token.strip())
    )
    match = _TOKEN.match(text)
    if match is None:
        raise SystemExit(f"unparsable selection token {token!r}; expected {_SYNTAX}")

    for group, axis, declared in (
        ("mode", "deploy mode", MODES),
        ("tor", "onion state", TOR_WORDS),
        ("distro", "distro", DISTROS),
        ("filesystem", "filesystem", FILESYSTEMS),
    ):
        value = match.group(group)
        if value is not None and value not in declared:
            raise SystemExit(
                f"selection token {token!r} names unknown {axis} {value!r}; "
                f"expected {', '.join(declared)}"
            )

    name = match.group("name")
    variants = match.group("variants")
    word = match.group("tor")
    return Pin(
        display_names().decode(name) or name,
        tuple(int(index) for index in variants.split(",")) if variants else (),
        _agree(match.group("mode"), glyph_mode, token, "mode"),
        _agree(TOR_WORDS[word] if word else None, glyph_tor, token, "onion"),
        _agree(match.group("distro"), glyph_distro, token, "distro"),
        _agree(match.group("filesystem"), glyph_fs, token, "filesystem"),
    )


def covers(pin: Pin, entry: Mapping[str, Any]) -> bool:
    """Whether *pin* names this matrix entry.

    An axis the token leaves open matches anything, so ``web-app-x`` covers
    every row of that role and ``web-app-x#2@swarm`` only its swarm deploy of
    variant 2. Reads the strings a matrix entry carries, not a discovery row's
    native types.
    """
    if entry.get("apps") != pin.app:
        return False
    if pin.variants and str(entry.get("variant", "")) not in {
        str(index) for index in pin.variants
    }:
        return False
    for value, key in (
        (pin.mode, "mode"),
        (pin.distro, "distro"),
        (pin.filesystem, "filesystem"),
    ):
        if value is not None and entry.get(key) != value:
            return False
    return pin.tor is None or (entry.get("tor") == "true") == pin.tor


def parse_list(tokens: str) -> list[Pin]:
    """Every token of a space-separated ``whitelist``/``priority`` input."""
    return [parse(token) for token in tokens.split()]


def names(pins: Iterable[Pin]) -> str:
    """The role ids the pins select, deduplicated, in the order given -- what
    the discovery query filters on. The axes are applied afterwards, on the
    rows the query returned."""
    return " ".join(dict.fromkeys(pin.app for pin in pins))


def apply(
    rows: Sequence[Mapping[str, Any]], pins: Sequence[Pin]
) -> list[dict[str, Any]]:
    """Keep the rows the pins select and stamp the pinned axes onto them.

    Args:
        rows: discovery rows of one line, in query order.
        pins: that line's selection tokens; empty means "no selection", and
            every row passes through untouched.

    Returns:
        one entry per (row, pin) the selection asks for, each carrying
        ``pin_mode``, ``pin_tor``, ``pin_distro`` and ``pin_filesystem`` for
        :func:`utils.github.variant.axes.assign` to honour. Order is the
        query's -- a selection narrows what runs, it never re-ranks it.

        A row several tokens name is emitted once per token, which is the whole
        point of the axes: ``role#1@compose+tor role#1@swarm+tor`` is one
        variant that failed in two modes, and it has to come back as two
        deploys. Two tokens narrowing a row the same way collapse into one, so
        a duplicate in the input cannot become two jobs racing for one artifact
        name.

        A bare role name loses to any token that narrows the same row: writing
        ``role role#1@swarm`` asks for a specific deploy, not for that deploy
        plus a rotation-picked one on top.

    Raises:
        SystemExit: a token that pins something matched no row at all. Silently
            deploying nothing is how a mistyped variant index turns into a
            green run that tested nothing.
    """
    if not pins:
        return [dict(row) for row in rows]
    kept: list[dict[str, Any]] = []
    matched: set[int] = set()
    for row in rows:
        hits = [
            (index, pin)
            for index, pin in enumerate(pins)
            if pin.app == row["name"]
            and (not pin.variants or row.get("variant") in pin.variants)
        ]
        matched.update(index for index, _pin in hits)
        narrowing = [(index, pin) for index, pin in hits if pin.pinned]
        seen: set[tuple[Any, ...]] = set()
        for _index, pin in narrowing or hits[:1]:
            if pin.axes in seen:
                continue
            seen.add(pin.axes)
            kept.append(
                {
                    **row,
                    "pin_mode": pin.mode,
                    "pin_tor": pin.tor,
                    "pin_distro": pin.distro,
                    "pin_filesystem": pin.filesystem,
                }
            )
    for index, pin in enumerate(pins):
        if index not in matched and pin.pinned:
            raise SystemExit(
                f"selection {describe(pin)!r} matches no discovered row; "
                f"check the variant index and the run's lifecycle/mode filters"
            )
    return kept
