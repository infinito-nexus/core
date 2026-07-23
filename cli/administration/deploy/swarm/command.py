"""Swarm-aware deploy CLI command.

Re-uses ``dedicated.command.parse_args`` verbatim, then rewrites
``args.id`` via the swarm closure between parse and dispatch.
"""

from __future__ import annotations

from cli.administration.deploy.dedicated.command import parse_args, run_from_args

from .closure import swarm_deploy_targets


def main(argv: list[str] | None = None) -> int:
    args, passthrough, modes_spec = parse_args(argv)
    args.id = swarm_deploy_targets(args.id, args.inventory)
    return run_from_args(args, passthrough, modes_spec)
