"""Assign the deploy axes to CI matrix rows.

Every row of the CI matrix is one ``role#variant`` selection. Four axes are
decided here, all as a deterministic rotation over the row's position in the
*global* discovery order and the sweep number -- never at random, so a red job
can be reproduced by re-running the same sweep, and so consecutive sweeps
cover the combinations instead of sampling them:

* **mode** -- which of ``compose``/``swarm``/``host`` the row deploys in,
  drawn from the modes the role actually offers. In practice that is at most
  two: swarm requires the role to ship its own stack, host requires it not to.
  ``(position + sweep) % len(offered)`` therefore flips a row between its two
  modes on consecutive sweeps.

* **tor** -- whether the row deploys behind the node onion. Driven by
  ``sweep // 2`` so it does NOT flip in lockstep with the mode; a row walks
  all four mode/tor combinations over four sweeps instead of only two.

* **distro** -- which declared distribution the row deploys on. Per row rather
  than per run, so one sweep proves every distribution instead of proving one
  and claiming nothing about the other four, and a red row still names the
  exact distribution it died on.

* **filesystem** -- which kind the row's docker data root runs on. The two
  read the row's position like an odometer: the distro is the low digit and
  the filesystem the high one, so consecutive rows walk every pairing rather
  than a diagonal through it. Turning both on the position directly would
  cover only ``n`` of the ``n x m`` pairs whenever the two pools happen to be
  the same length, and no sweep would unlock it, because the sweep shifts both
  by the same amount.

A row's position is its index in the uncapped discovery order, not its index
inside a chunk, so slicing the list into chunks never changes what a row is
assigned. A priority row, which deploys several mode/tor combinations at once,
walks the distro and filesystem rotations across those combinations rather
than repeating one pair.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, NamedTuple

from utils.github.variant.pools import DISTROS, FILESYSTEMS, rotate
from utils.github.variant.tor import (
    TOR_DEPLOY_MODES,
    combinations,
    tor_capable,
    tor_provider,
    tor_states,
    wants_tor,
)
from utils.roles.display import VARIANT_SEPARATOR, display_names
from utils.symbol_glossary import to_emoji, to_word

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Any

MODES = ("compose", "swarm", "host")

LOCAL_GLYPH = to_emoji("test_host")

_AXIS_GLYPHS = (
    "".join(to_emoji(word) for word in ("tor", "clearnet", "priority")) + LOCAL_GLYPH
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
    )


def resolve_sweep(raw: str | None = None) -> int:
    """Sweep number from ``INFINITO_CI_SWEEP``; it drives both rotations."""
    if raw is None:
        raw = os.environ.get("INFINITO_CI_SWEEP")
    try:
        return int((raw or "0").strip())
    except ValueError:
        return 0


def pick_mode(offered: Sequence[str], position: int, sweep: int) -> str:
    """The deploy mode a row runs in this sweep.

    Args:
        offered: modes the role supports, in a stable order.
        position: the row's index in the global discovery order.
        sweep: sweep number.

    Raises:
        ValueError: *offered* is empty -- a row the query returned always has
            at least one mode, so an empty list is a bug upstream, not a case
            to paper over with a fallback mode.
    """
    if not offered:
        raise ValueError("row offers no deploy mode; the query should have dropped it")
    return rotate(offered, position, sweep)


def artifact_slug(
    mode: str, app: str, variant: str, tor: bool, distro: str = "", filesystem: str = ""
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
    shards = (variant, "tor" if tor else "", distro, filesystem)
    return f"{mode}-{app}" + "".join(f"-{shard}" for shard in shards if shard)


def _reject(app: str, variant: str, reason: str) -> None:
    """Abort on a selection the row cannot satisfy.

    Raises:
        SystemExit: always. A pin the row cannot take is an operator mistake,
            and dropping the row instead would report a green run for a
            combination that never ran.
    """
    shard = f"{VARIANT_SEPARATOR}{variant}" if variant else ""
    raise SystemExit(f"selection {app}{shard}: {reason}")


def check_pins(
    app: str,
    variant: str,
    offered: Sequence[str],
    *,
    pin_mode: str | None,
    pin_tor: bool | None,
    pin_distro: str | None,
    pin_filesystem: str | None,
    capable: bool,
    tor_mode: str,
    distros: Sequence[str],
    filesystems: Sequence[str],
) -> None:
    """Prove the row can take what the selection token pinned on it.

    The offered modes are already narrowed by the run's ``--modes`` input, the
    onion states by its ``--tor`` input and the two pools by ``--distros`` and
    ``--filesystem``, so this catches a pin that fights the role, the variant,
    or the run's own axes with one check each.
    """
    if pin_mode is not None and pin_mode not in offered:
        _reject(
            app,
            variant,
            f"pinned mode {pin_mode!r} is not available here "
            f"(offered: {', '.join(offered)})",
        )
    for value, pool, axis in (
        (pin_distro, distros, "distro"),
        (pin_filesystem, filesystems, "filesystem"),
    ):
        if value is not None and value not in pool:
            _reject(
                app,
                variant,
                f"pinned {axis} {value!r} is outside this run's {axis} pool "
                f"({', '.join(pool) or 'empty'})",
            )
    if pin_tor is None:
        return
    for mode in (pin_mode,) if pin_mode else offered:
        if pin_tor in tor_states(mode, capable=capable, tor_mode=tor_mode):
            return
    _reject(
        app,
        variant,
        f"pinned onion state {'tor' if pin_tor else 'clearnet'} is impossible "
        f"here (mode, variant or the run's tor axis rules it out)",
    )


def sort_key(entry: Mapping[str, str]) -> tuple[Any, ...]:
    """Where one entry sorts inside its chunk: display name, then variant,
    then deploy mode, then onion state.

    The chunk split itself is not sorted -- it follows the discovery ranking,
    which is what decides who makes the budget cut. This only orders the jobs
    a chunk already holds, so a chunk's job list reads like the plan table
    instead of like the sweep's rotation.
    """
    return (
        display_names().encode(entry["apps"]),
        tuple(int(part) for part in entry["variant"].split(",") if part),
        MODES.index(entry["mode"]) if entry["mode"] in MODES else len(MODES),
        entry["tor"] == "true",
    )


def assign(
    rows: Sequence[Mapping[str, Any]],
    *,
    sweep: int,
    tor_mode: str,
    distros: Sequence[str],
    filesystems: Sequence[str],
    variants_per_app: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> list[dict[str, str]]:
    """Turn ordered discovery rows into CI matrix entries.

    Args:
        rows: discovery rows, each carrying ``name``, ``variant``, ``modes``
            (the offered subset) and ``priority``, in global query order.
            ``pin_mode``/``pin_tor``/``pin_distro``/``pin_filesystem``, when a
            selection token set them, pin that axis: the priority line then
            covers only the combinations that match, and the regular line takes
            the pin instead of its rotation.
        sweep: sweep number driving every rotation.
        tor_mode: ``enforced`` onions every capable row, ``disabled`` none,
            ``exclusive`` drops the rows that cannot take one, ``auto``
            rotates.
        distros: the distributions this run may draw from
            (:func:`resolve_pool`).
        filesystems: the docker data-root kinds this run may draw from. A pool
            of exactly one, like a token that pins the kind, is a human naming
            it: the entry then carries ``enforce_filesystem``, and a host that
            cannot serve it fails instead of substituting one. A wider pool
            leaves the row's kind a preference, because the matrix narrows
            every row to one kind and reading that as a demand would fail rows
            for conditions the applying step is built to tolerate.
        variants_per_app: rendered variant configs per app, so a variant that
            switches the tor gate off is never counted capable.

    Returns:
        one entry per (row, mode, tor) the run deploys, each stamped with the
        distro and filesystem its rotation drew, carrying the row's
        discovery ``id`` and the ``covered`` id of the earlier row that already
        embeds it (``0``: nothing does), so a reader of the plan can tell a
        redundant row from a unique one without a second query. A regular row
        yields
        exactly one -- the rotation picks its combination for this sweep. A
        priority row yields every combination :func:`combinations` allows, so
        the roles a run is told to prove are proven everywhere at once rather
        than sampled over four sweeps. ``disable`` carries the provider tokens
        the deploy drill switches off; a row without tor disables the provider
        so no dependency edge can pull it back into the closure. The provider's
        own rows therefore never take the clearnet state: disabling tor there
        would strip the app under test out of its own deploy.
    """
    codec = display_names()
    provider = tor_provider()
    entries: list[dict[str, str]] = []
    for position, row in enumerate(rows):
        app = row["name"]
        variant = row.get("variant")
        priority = bool(row.get("priority"))
        capable = tor_capable(app, variant, variants_per_app)
        offered = tuple(row["modes"])
        variant_csv = "" if variant is None else str(variant)
        pin_mode = row.get("pin_mode")
        pin_tor = row.get("pin_tor")
        pin_distro = row.get("pin_distro")
        pin_filesystem = row.get("pin_filesystem")
        check_pins(
            app,
            variant_csv,
            offered,
            pin_mode=pin_mode,
            pin_tor=pin_tor,
            pin_distro=pin_distro,
            pin_filesystem=pin_filesystem,
            capable=capable,
            tor_mode=tor_mode,
            distros=distros,
            filesystems=filesystems,
        )
        if priority:
            picked = [
                (mode, state)
                for mode, state in combinations(
                    offered, capable=capable, tor_mode=tor_mode
                )
                if pin_mode in (None, mode) and pin_tor in (None, state)
            ]
        else:
            mode = pin_mode or pick_mode(
                _offering(offered, pin_tor, capable=capable, tor_mode=tor_mode),
                position,
                sweep,
            )
            picked = [
                (mode, state)
                for state in _rotated_tor(
                    mode,
                    capable=capable,
                    tor_mode=tor_mode,
                    position=position,
                    sweep=sweep,
                    pin=pin_tor,
                )
            ]
        if app == provider:
            picked = [(mode, enabled) for mode, enabled in picked if enabled]
        label = codec.encode(app, variant_csv)
        for step, (mode, enabled) in enumerate(picked):
            distro = pin_distro or rotate(distros, position + step, sweep)
            filesystem = pin_filesystem or rotate(
                filesystems, (position + step) // len(distros), sweep
            )
            glyphs = (
                to_emoji(mode)
                + (
                    to_emoji("tor" if enabled else "clearnet")
                    if mode in TOR_DEPLOY_MODES
                    else LOCAL_GLYPH
                )
                + to_emoji(distro)
                + to_emoji(filesystem)
            )
            entries.append(
                {
                    "apps": app,
                    "variant": variant_csv,
                    "mode": mode,
                    "tor": "true" if enabled else "false",
                    "distro": distro,
                    "filesystem": filesystem,
                    "enforce_filesystem": "true"
                    if pin_filesystem is not None or len(filesystems) == 1
                    else "false",
                    "disable": "" if enabled else "tor",
                    "priority": "true" if priority else "false",
                    "weight": str(row.get("weight", 0)),
                    "id": str(row.get("id", 0)),
                    "covered": str(row.get("covered_by", 0)),
                    "clone": "true" if row.get("clone") else "false",
                    "artifact": artifact_slug(
                        mode, app, variant_csv, enabled, distro, filesystem
                    ),
                    "label": f"{glyphs}{label}"
                    + (f" {to_emoji('priority')}" if priority else ""),
                }
            )
    return _one_per_deploy(entries)


def _one_per_deploy(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    """Collapse entries that describe the same deployment, keeping the first.

    Two selection tokens can pin different axes of one row -- ``role#0%debian``
    and ``role#0/zfs`` -- and each leaves the other's axis to the rotation. When
    the rotation lands on exactly that value, both tokens resolve to the same
    deploy. That is one job, not two: they would carry one artifact name, and
    ``actions/upload-artifact`` rejects the second upload rather than merging
    it. The artifact slug is the identity because it is precisely what
    distinguishes one deploy job's output from another's.

    ``enforce_filesystem`` is OR-ed rather than taken from the survivor: the
    token that pinned the kind may be the one collapsing into a token that did
    not, and dropping its demand would let the deploy fall back to a filesystem
    the operator explicitly named against.
    """
    kept: dict[str, dict[str, str]] = {}
    for entry in entries:
        first = kept.setdefault(entry["artifact"], entry)
        if entry["enforce_filesystem"] == "true":
            first["enforce_filesystem"] = "true"
    return list(kept.values())


def _offering(
    offered: Sequence[str], pin: bool | None, *, capable: bool, tor_mode: str
) -> tuple[str, ...]:
    """The modes the rotation may still draw from once an onion state is
    pinned: pinning the onion on a row that also offers host must not rotate
    the row onto host, where no onion exists."""
    if pin is None:
        return tuple(offered)
    return tuple(
        mode
        for mode in offered
        if pin in tor_states(mode, capable=capable, tor_mode=tor_mode)
    )


def _rotated_tor(
    mode: str,
    *,
    capable: bool,
    tor_mode: str,
    position: int,
    sweep: int,
    pin: bool | None = None,
) -> list[bool]:
    """The single onion state a regular row takes this sweep, or nothing when
    ``exclusive`` drops it. A pinned state replaces the rotation -- it was
    proven possible by :func:`check_pins` before we get here."""
    allowed = tor_states(mode, capable=capable, tor_mode=tor_mode)
    if pin is not None:
        return [pin]
    if len(allowed) < 2:
        return allowed
    return [capable and wants_tor(position, sweep)]
