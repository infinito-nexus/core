"""Decide whether a CI line deploys its modes in sequence or in parallel.

Usage:
  python -m cli.meta.ci.sequencing [--modes "swarm compose host"]
      [--whitelist "..."] [--blacklist "..."] [--lifecycles "..."]
      [--choice auto|serial|parallel]

A *line* is the priority (⭐) or the regular (🔁) half of an orchestrator
run. Its job count is the sum of the deploy-matrix entries every active
mode contributes, counted on the row basis the discover steps use: swarm
selections are ``role#variant`` tokens mapping 1:1 onto jobs, compose and
host selections are whole roles whose variants pack into bundles
(utils.github.variant.bundles, the same packing the matrix runs).

GitHub cancels a job that sat queued for 24 hours. A line that starts every
mode at once floods the runner pool, so the tail of its matrix waits past
that cut and dies unrun. ``auto`` therefore serialises the modes -- swarm,
then compose, then host, heaviest first -- once the line exceeds
``INFINITO_CI_SEQUENTIAL_THRESHOLD`` jobs, which restarts the queue clock
per mode. Below the threshold the modes run in parallel for wall-clock.

The count omits the runner-storage filter scripts/meta/resolve/apps.sh
applies inside GitHub Actions, so it can only overestimate, erring towards
the sequential layout that cannot be cancelled.

Writes ``jobs=<n>`` and ``sequencing=<serial|parallel>``, ready to append to
``$GITHUB_OUTPUT``.
"""

from __future__ import annotations

import argparse
import os
import sys

from cli.meta.ci.query import MODES, discover, expands_variants
from utils.cache.applications import get_variants
from utils.github.variant.bundles import compose_bundle_counts
from utils.roles.display import display_names

CHOICES = ("auto", "serial", "parallel")


def mode_jobs(mode: str, *, whitelist: str, blacklist: str, lifecycles: str) -> int:
    """Deploy-matrix jobs *mode* contributes to the line."""
    selection = discover(
        mode, whitelist=whitelist, blacklist=blacklist, lifecycles=lifecycles
    )
    if expands_variants(mode):
        return len(selection)
    return sum(compose_bundle_counts(selection, get_variants()).values())


def line_jobs(modes: str, *, whitelist: str, blacklist: str, lifecycles: str) -> int:
    return sum(
        mode_jobs(mode, whitelist=whitelist, blacklist=blacklist, lifecycles=lifecycles)
        for mode in MODES
        if mode in modes.split()
    )


def threshold() -> int:
    return int(os.environ["INFINITO_CI_SEQUENTIAL_THRESHOLD"])


def decide(jobs: int | None, choice: str) -> str:
    """``choice`` verbatim unless it is ``auto``, which compares *jobs*
    against the threshold."""
    if choice != "auto":
        return choice
    return "serial" if jobs > threshold() else "parallel"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Decide serial or parallel deploy modes for one CI line."
    )
    parser.add_argument("--modes", default=" ".join(MODES))
    parser.add_argument("--whitelist", default="")
    parser.add_argument("--blacklist", default="")
    parser.add_argument("--lifecycles", default="")
    parser.add_argument("--choice", default="auto", choices=CHOICES)
    args = parser.parse_args(argv)

    codec = display_names()
    args.whitelist = codec.decode_list(args.whitelist)
    args.blacklist = codec.decode_list(args.blacklist)

    if args.lifecycles.strip():
        os.environ["INFINITO_LIFECYCLES"] = args.lifecycles

    jobs = None
    if args.choice == "auto":
        jobs = line_jobs(
            args.modes,
            whitelist=args.whitelist,
            blacklist=args.blacklist,
            lifecycles=args.lifecycles,
        )

    print(f"jobs={'' if jobs is None else jobs}")
    print(f"sequencing={decide(jobs, args.choice)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
