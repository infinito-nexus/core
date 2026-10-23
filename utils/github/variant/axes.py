"""Assign the deploy axes to CI matrix rows.

Every row of the CI matrix is one ``role#variant`` selection. Six axes are
decided here, all as a deterministic rotation over the row's position in the
*global* discovery order and the sweep number -- never at random, so a red job
can be reproduced by re-running the same sweep, and so consecutive sweeps
cover the combinations instead of sampling them:

* **mode** -- which of ``compose``/``swarm``/``host`` the row deploys in,
  drawn from the modes the role actually offers. In practice that is at most
  two: swarm requires the role to ship its own stack, host requires it not to.
  ``(position + sweep) % len(offered)`` therefore flips a row between its two
  modes on consecutive sweeps.

* **network** -- which node network mode (``clearnet``, ``tor``, ``multi``)
  the row deploys in, drawn from the modes its role can be served in. Driven
  by ``sweep // 2`` so it does NOT flip in lockstep with the mode; a row walks
  every mode/network combination instead of a diagonal through them.

* **vpn** -- whether a swarm row deploys over the WireGuard mesh
  (:mod:`utils.github.variant.vpn`); every other mode takes the direct arm.

* **distro** -- which declared distribution the row deploys on. Per row rather
  than per run, so one sweep proves every distribution instead of proving one
  and claiming nothing about the other four, and a red row still names the
  exact distribution it died on.

* **filesystem** -- which kind the row's docker data root runs on. The two
  read the row's position like an odometer, the distro as the low digit, so
  consecutive rows walk every pairing rather than a diagonal through it.
  Turning both on the position directly would cover only ``n`` of the
  ``n x m`` pairs whenever the pools are the same length, and no sweep would
  unlock it.

* **architecture** -- which CPU architecture the row deploys on, and through
  :func:`utils.github.variant.pools.runner_of` which runner it lands on. It
  rotates on the position directly rather than as a further odometer digit:
  two values against five distros and fifteen distro/filesystem positions are
  coprime with both, so walking it fastest still reaches every pairing, while
  making it the slowest digit would hand a role with few rows a single
  architecture forever. A role may narrow the pool to one value in
  ``meta/services.yml`` when only that hardware can run it.

A row's position is its index in the uncapped discovery order, not its index
inside a chunk, so slicing the list into chunks never changes what a row is
assigned. A priority row, which deploys several mode/network combinations at
once, walks the distro and filesystem rotations across those combinations
rather than repeating one pair.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from utils.github.variant import instructions
from utils.github.variant.label import (
    LABEL_RE,
    LOCAL_GLYPH,
    artifact_slug,
    parse_label,
)
from utils.github.variant.network import (
    NETWORK_DEPLOY_MODES,
    combinations,
    disabled_services,
    network_states,
    row_pulls_tor,
    row_states,
)
from utils.github.variant.pins import check_pins, row_architectures
from utils.github.variant.pools import (
    ARCHITECTURES,
    DISTROS,
    FILESYSTEMS,
    MODES,
    rotate,
    runner_of,
)
from utils.github.variant.vpn import (
    VPN_DEPLOY_MODES,
    pinned_vpn_states,
    rotated_vpn,
)
from utils.networks.reachability import NODE_MODES
from utils.roles.display import display_names
from utils.symbol_glossary import to_emoji

__all__ = [
    "ARCHITECTURES",
    "DISTROS",
    "FILESYSTEMS",
    "LABEL_RE",
    "LOCAL_GLYPH",
    "MODES",
    "artifact_slug",
    "assign",
    "check_pins",
    "parse_label",
    "pick_mode",
    "resolve_sweep",
    "row_architectures",
    "sort_key",
]

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Any


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


def sort_key(entry: Mapping[str, str]) -> tuple[Any, ...]:
    """Where one entry sorts inside its chunk: display name, then variant,
    then deploy mode, then network mode.

    The chunk split itself is not sorted -- it follows the discovery ranking,
    which is what decides who makes the budget cut. This only orders the jobs
    a chunk already holds, so a chunk's job list reads like the plan table
    instead of like the sweep's rotation.
    """
    states = tuple(NODE_MODES)
    return (
        display_names().encode(entry["apps"]),
        tuple(int(part) for part in entry["variant"].split(",") if part),
        MODES.index(entry["mode"]) if entry["mode"] in MODES else len(MODES),
        states.index(entry["network"]) if entry["network"] in states else len(states),
    )


def assign(
    rows: Sequence[Mapping[str, Any]],
    *,
    sweep: int,
    network_input: str,
    distros: Sequence[str],
    filesystems: Sequence[str],
    architectures: Sequence[str] = ARCHITECTURES,
    vpn_mode: str = "auto",
    variants_per_app: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> list[dict[str, str]]:
    """Turn ordered discovery rows into CI matrix entries.

    Args:
        rows: discovery rows, each carrying ``name``, ``variant``, ``modes``
            (the offered subset), ``priority`` and the ``services`` closure
            (:func:`row_pulls_tor`), in global query order.
            ``pin_mode``/``pin_network``/``pin_distro``/``pin_filesystem``,
            when a selection token set them, pin that axis: the priority line
            then covers only the combinations that match, and the regular line
            takes the pin instead of its rotation.
        sweep: sweep number driving every rotation.
        network_input: ``auto`` rotates over the network modes a row can take;
            ``clearnet``, ``tor`` or ``multi`` keeps only the rows that can
            take that mode, in that mode.
        distros: the distributions this run may draw from
            (:func:`resolve_pool`).
        filesystems: the docker data-root kinds this run may draw from. A pool
            of exactly one is a human naming it: the entry then carries
            ``enforce_filesystem`` and a host that cannot serve it fails
            instead of substituting one. A wider pool leaves the kind a
            preference, because the matrix narrows every row to one anyway.
        vpn_mode: ``enforced`` meshes every swarm row, ``disabled`` none,
            ``auto`` rotates.
        variants_per_app: rendered variant configs per app, so a variant that
            switches the tor gate off is never offered a Tor network mode.

    Returns:
        one entry per (row, mode, network) the run deploys, each stamped with
        the distro and filesystem its rotation drew, carrying the row's
        discovery ``id`` and the ``covered`` id of the earlier row that already
        embeds it (``0``: nothing does), so a reader of the plan can tell a
        redundant row from a unique one without a second query. A regular row
        yields exactly one -- the rotation picks its combination for this
        sweep. A priority row yields every combination :func:`combinations`
        allows, so the roles a run is told to prove are proven everywhere at
        once rather than sampled over several sweeps. ``network`` is the node
        ``NETWORK_MODE`` the deploy runs with, ``vpn`` whether a swarm row
        runs meshed, and ``disable`` carries the provider tokens the deploy
        drill switches off; a ``clearnet`` row disables the Tor provider so no
        dependency edge can pull it back into the closure.
    """
    codec = display_names()
    entries: list[dict[str, str]] = []
    for position, row in enumerate(rows):
        app = row["name"]
        variant = row.get("variant")
        priority = bool(row.get("priority"))
        states = row_states(
            app, variant, variants_per_app, pulls_tor=row_pulls_tor(row)
        )
        offered = tuple(row["modes"])
        variant_csv = "" if variant is None else str(variant)
        pin_mode = row.get("pin_mode")
        pin_network = row.get("pin_network")
        pin_distro = row.get("pin_distro")
        pin_filesystem = row.get("pin_filesystem")
        pin_architecture = row.get("pin_architecture")
        pin_vpn = row.get("pin_vpn")
        offered_architectures = row_architectures(
            app, architectures, row.get("services", ())
        )
        check_pins(
            app,
            variant_csv,
            offered,
            pin_mode=pin_mode,
            pin_network=pin_network,
            pin_distro=pin_distro,
            pin_filesystem=pin_filesystem,
            pin_architecture=pin_architecture,
            pin_vpn=pin_vpn,
            states=states,
            network_input=network_input,
            vpn_mode=vpn_mode,
            distros=distros,
            filesystems=filesystems,
            architectures=offered_architectures,
        )
        if priority:
            picked = [
                (mode, state, meshed)
                for mode, state in combinations(
                    offered, states=states, network_input=network_input
                )
                if pin_mode in (None, mode) and pin_network in (None, state)
                for meshed in pinned_vpn_states(mode, pin=pin_vpn, vpn_mode=vpn_mode)
            ]
        else:
            modes = _offering(
                offered, pin_network, states=states, network_input=network_input
            )
            mode = pin_mode or (pick_mode(modes, position, sweep) if modes else None)
            picked = [
                (
                    mode,
                    state,
                    rotated_vpn(
                        mode,
                        position=position,
                        sweep=sweep,
                        pin=pin_vpn,
                        vpn_mode=vpn_mode,
                    ),
                )
                for state in (
                    _rotated_network(
                        mode,
                        states=states,
                        network_input=network_input,
                        position=position,
                        sweep=sweep,
                        pin=pin_network,
                    )
                    if mode
                    else []
                )
            ]
        label = codec.encode(app, variant_csv)
        for step, (mode, state, meshed) in enumerate(picked):
            distro = pin_distro or rotate(distros, position + step, sweep)
            filesystem = pin_filesystem or rotate(
                filesystems, (position + step) // len(distros), sweep
            )
            architecture = pin_architecture or rotate(
                offered_architectures, position + step, sweep
            )
            glyphs = (
                to_emoji(mode)
                + (to_emoji(state) if mode in NETWORK_DEPLOY_MODES else LOCAL_GLYPH)
                + (
                    to_emoji("vpn" if meshed else "direct")
                    if mode in VPN_DEPLOY_MODES or mode == "compose"
                    else ""
                )
                + to_emoji(distro)
                + to_emoji(filesystem)
                + to_emoji(architecture)
            )
            entries.append(
                {
                    "apps": app,
                    "variant": variant_csv,
                    "mode": mode,
                    "network": state,
                    "vpn": "true" if meshed else "false",
                    "distro": distro,
                    "filesystem": filesystem,
                    "architecture": architecture,
                    "runner": runner_of(architecture),
                    "enforce_filesystem": "true"
                    if pin_filesystem is not None or len(filesystems) == 1
                    else "false",
                    "disable": disabled_services(state),
                    "priority": "true" if priority else "false",
                    "instructions": "",
                    "id": str(row.get("id", 0)),
                    "covered": str(row.get("covered_by", 0)),
                    "clone": "true" if row.get("clone") else "false",
                    "artifact": artifact_slug(
                        mode,
                        app,
                        variant_csv,
                        state,
                        distro,
                        filesystem,
                        architecture,
                        meshed,
                    ),
                    "label": f"{glyphs}{label}"
                    + (f" {to_emoji('priority')}" if priority else ""),
                }
            )
    return instructions.mark(_one_per_deploy(entries), variants_per_app)


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
    offered: Sequence[str],
    pin: str | None,
    *,
    states: Sequence[str],
    network_input: str,
) -> tuple[str, ...]:
    """The modes the rotation may still draw from: the ones that can take the
    pinned network mode, or any network mode the run's input leaves open.
    Pinning ``tor``, or running the whole sweep on ``tor``, must not rotate a
    row that also offers host onto host, where no onion exists."""
    kept = []
    for mode in offered:
        allowed = network_states(mode, states=states, network_input=network_input)
        if (pin in allowed) if pin is not None else allowed:
            kept.append(mode)
    return tuple(kept)


def _rotated_network(
    mode: str,
    *,
    states: Sequence[str],
    network_input: str,
    position: int,
    sweep: int,
    pin: str | None = None,
) -> list[str]:
    """The single network mode a regular row takes this sweep, or nothing when
    the run's network input rules the row out. A pinned mode replaces the
    rotation -- it was proven possible by :func:`check_pins` before we get
    here. The rotation turns on ``sweep // 2`` so it does not flip in lockstep
    with the deploy mode."""
    allowed = network_states(mode, states=states, network_input=network_input)
    if pin is not None:
        return [pin]
    if len(allowed) < 2:
        return allowed
    return [rotate(allowed, position, sweep // 2)]
