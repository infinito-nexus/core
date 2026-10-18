"""What the deploy axes may draw from, and how they draw.

Separate from :mod:`utils.github.variant.axes` because it answers a narrower
question: ``axes`` decides which value a given row takes, this module owns the
value sets themselves, the narrowing a run may apply to them, and the rotation
that walks them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.distros import distro_names

if TYPE_CHECKING:
    from collections.abc import Sequence

MODES = ("compose", "swarm", "host")

DISTROS = distro_names()

FILESYSTEMS = ("zfs", "btrfs", "ext4")

ARCHITECTURES = ("amd64", "arm64")

RUNNERS = {"amd64": "ubuntu-latest", "arm64": "ubuntu-24.04-arm"}
"""The runner label each architecture deploys on."""


def resolve_pool(
    raw: str | None, declared: Sequence[str], axis: str
) -> tuple[str, ...]:
    """The values one axis may draw from this run.

    Args:
        raw: the run's input, space- or comma-separated. Empty means the whole
            declared set, the same way ``--modes auto`` opens the mode axis.
        declared: every value the axis knows, in declaration order.
        axis: what to call the axis in the refusal.

    Raises:
        SystemExit: a token naming no declared value. A typo has to abort the
            run rather than narrow it to a set nobody asked for.
    """
    tokens = (raw or "").replace(",", " ").split()
    if not tokens:
        return tuple(declared)
    unknown = [token for token in tokens if token not in declared]
    if unknown:
        raise SystemExit(
            f"unknown {axis}(s): {' '.join(unknown)}; expected {', '.join(declared)}"
        )
    return tuple(value for value in declared if value in tokens)


def resolve_distros(raw: str | None) -> tuple[str, ...]:
    """The distributions this run spreads its rows over; empty means all."""
    return resolve_pool(raw, DISTROS, "distro")


def resolve_filesystems(raw: str | None) -> tuple[str, ...]:
    """The docker data-root kinds this run spreads its rows over; empty means
    all."""
    return resolve_pool(raw, FILESYSTEMS, "filesystem")


def resolve_architectures(raw: str | None) -> tuple[str, ...]:
    """The CPU architectures this run spreads its rows over; empty means
    both."""
    return resolve_pool(raw, ARCHITECTURES, "architecture")


def runner_of(architecture: str) -> str:
    """The runner label *architecture* deploys on.

    Raises:
        KeyError: the architecture has no label. Falling back to the amd64
            runner would deploy an arm64 row on amd64 hardware and report it
            green under an arm64 job title.
    """
    return RUNNERS[architecture]


def rotate(pool: Sequence[str], position: int, sweep: int) -> str:
    """The value a row draws from *pool* this sweep: a plain rotation over the
    row's global position, so consecutive rows spread across the pool and
    consecutive sweeps move every row on to the next value."""
    return pool[(position + sweep) % len(pool)]
