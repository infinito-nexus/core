"""Check a run's selection inputs against the branch before anything deploys.

Usage:
  python -m cli.meta.ci.validate [--whitelist "..."] [--priority "..."]
      [--modes auto] [--tor auto] [--distros "..."] [--filesystem "..."]
      [--lifecycles "..."]

A selection token names a row that has to exist *on this branch*
(:mod:`utils.github.variant.selection`). Nothing else in the chain can tell
the operator that early: the matrix builder raises on the first bad token, one
per chunk job, so a stale list costs one full CI round per entry and reports
the second problem only after the first is fixed. Every problem is collected
here instead, and the exit code gates the run.

What makes a token bad, in the order this checks it:

* it does not parse, or names a mode or onion state that does not exist;
* it names a role the discovery query does not return -- a typo, a role
  outside the run's lifecycle envelope, or a role that no longer exists;
* it pins a variant the role does not declare (any more): the usual case is a
  list carried over from an older run whose variants have since been renumbered;
* it pins a mode the row cannot take, an onion state the row, the mode or the
  run's own tor axis rules out, or a distro or filesystem the run's own pool
  does not hold.

A bare role name that matches nothing is reported too, but as a warning: the
diff-derived whitelist legitimately names roles the envelope filters out.
"""

from __future__ import annotations

import argparse
import sys

from cli.meta.ci import query
from utils.cache.applications import get_variants
from utils.github.variant import axes, pools, selection, tor
from utils.roles.display import display_names


def problems(
    tokens: str,
    *,
    modes: tuple[str, ...],
    tor_mode: str,
    distros: tuple[str, ...],
    filesystems: tuple[str, ...],
    lifecycles: str,
    label: str,
) -> tuple[list[str], list[str]]:
    """Every reason the tokens of one input cannot deploy on this branch.

    Args:
        tokens: the raw ``whitelist``/``priority`` value.
        modes: the run's selected deploy modes.
        tor_mode: the run's tor axis.
        distros: the distro pool the run draws from.
        filesystems: the filesystem pool the run draws from.
        lifecycles: the run's lifecycle envelope.
        label: the input's name, for the messages.

    Returns:
        ``(errors, warnings)``.
    """
    pins = selection.parse_list(display_names().decode_list(tokens))
    if not pins:
        return [], []

    rows = {
        (row["name"], row["variant"]): query.row_modes(row, modes)
        for row in query.discover_rows(
            modes, whitelist=selection.names(pins), lifecycles=lifecycles
        )
    }
    declared = get_variants()
    errors: list[str] = []
    warnings: list[str] = []
    for pin in pins:
        token = selection.describe(pin)
        variants = pin.variants or (None,)
        for variant in variants:
            offered = rows.get((pin.app, variant))
            if offered is None:
                count = len(declared.get(pin.app) or [])
                reason = (
                    f"role declares {count} variant(s)"
                    if pin.variants
                    else "no row in this run's mode and lifecycle envelope"
                )
                message = f"{label}: {token!r} matches no discovered row ({reason})"
                (errors if pin.pinned else warnings).append(message)
                continue
            try:
                axes.check_pins(
                    pin.app,
                    "" if variant is None else str(variant),
                    offered,
                    pin_mode=pin.mode,
                    pin_tor=pin.tor,
                    pin_distro=pin.distro,
                    pin_filesystem=pin.filesystem,
                    capable=tor.tor_capable(pin.app, variant, declared),
                    tor_mode=tor_mode,
                    distros=distros,
                    filesystems=filesystems,
                )
            except SystemExit as refusal:
                errors.append(f"{label}: {token!r} {str(refusal).split(': ', 1)[-1]}")
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a run's selection inputs against this branch."
    )
    parser.add_argument("--whitelist", default="")
    parser.add_argument("--priority", default="")
    parser.add_argument("--modes", default=query.ALL_MODES)
    parser.add_argument("--tor", default=None)
    parser.add_argument("--distros", default="")
    parser.add_argument("--filesystem", default="")
    parser.add_argument("--lifecycles", default="")
    args = parser.parse_args(argv)

    modes = query.resolve_modes(args.modes)
    tor_mode = tor.resolve_tor_mode(args.tor)
    distros = pools.resolve_distros(args.distros)
    filesystems = pools.resolve_filesystems(args.filesystem)

    errors: list[str] = []
    warnings: list[str] = []
    for label, tokens in (("whitelist", args.whitelist), ("priority", args.priority)):
        found, warned = problems(
            tokens,
            modes=modes,
            tor_mode=tor_mode,
            distros=distros,
            filesystems=filesystems,
            lifecycles=args.lifecycles,
            label=label,
        )
        errors += found
        warnings += warned

    for warning in warnings:
        print(f"::warning::{warning}")
    for error in errors:
        print(f"::error::{error}", file=sys.stderr)
    if errors:
        print(
            f"\n{len(errors)} unusable selection(s). Every one of them would abort a "
            f"chunk's discovery, so the run is refused here instead.",
            file=sys.stderr,
        )
        return 1
    print("Selection inputs are valid for this branch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
