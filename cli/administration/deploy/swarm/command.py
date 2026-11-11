"""Swarm-aware deploy CLI command.

Re-uses ``dedicated.command.parse_args`` verbatim, pulls the custom roles
first because the swarm closure reads roles/, then rewrites ``args.id``
via that closure between parse and dispatch.
"""

from __future__ import annotations

from cli.administration.deploy.dedicated.command import (
    parse_args,
    pull_custom_roles,
    run_from_args,
)

from .closure import swarm_deploy_targets


def main(argv: list[str] | None = None) -> int:
    args, passthrough, modes_spec = parse_args(argv)
    pull_custom_roles(args)
    args.id = swarm_deploy_targets(args.id, args.inventory)
    return run_from_args(args, passthrough, modes_spec)
