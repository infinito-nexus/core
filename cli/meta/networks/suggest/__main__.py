#!/usr/bin/env python3
"""Suggest free per-role subnets based on the live role tree (req-009).

Walks every ``roles/*/meta/server.yml``, collects occupied
``networks.local.subnet`` assignments, picks the smallest CIDR prefix that
fits the requested client count, and proposes free sub-blocks gap-first.

Usage:

  cli meta networks suggest --clients 14 --count 2
  cli meta networks suggest --clients 254 --count 1
  cli meta networks suggest --clients 14 --block 192.168.101.0/24
"""

from __future__ import annotations

import argparse
import ipaddress
import sys
from typing import Iterable, List, Optional, Tuple

from utils.meta.scan import iter_subnets


# Prefix length thresholds — smallest prefix that still fits N clients.
# Each entry is (max_clients, prefix_length).
_PREFIX_THRESHOLDS: Tuple[Tuple[int, int], ...] = (
    (2, 30),
    (6, 29),
    (14, 28),
    (30, 27),
    (62, 26),
    (126, 25),
    (254, 24),
    (510, 23),
    (1022, 22),
    (2046, 21),
    (4094, 20),
)


def smallest_prefix(clients: int) -> int:
    if clients < 1:
        raise SystemExit("--clients must be >= 1")
    for max_clients, prefix in _PREFIX_THRESHOLDS:
        if clients <= max_clients:
            return prefix
    raise SystemExit(
        f"--clients {clients} exceeds the largest supported prefix; "
        f"pass --block <cidr> to bootstrap a new umbrella block manually."
    )


def umbrella_blocks_for(prefix: int) -> List[ipaddress.IPv4Network]:
    """Return the set of /24 (or coarser) umbrella blocks already in use for
    sub-allocations of the requested prefix length.
    """
    occupied = [net for _r, net in iter_subnets() if net.prefixlen == prefix]
    if not occupied:
        return []
    umbrellas: set[ipaddress.IPv4Network] = set()
    for net in occupied:
        # The umbrella block is the closest enclosing /24 (or coarser).
        # For prefixes <= 24 the umbrella is the network itself.
        umbrella_prefix = min(prefix, 24)
        umbrellas.add(net.supernet(new_prefix=umbrella_prefix))
    return sorted(umbrellas, key=lambda n: int(n.network_address))


def gap_first_subnets(
    block: ipaddress.IPv4Network, prefix: int, occupied: Iterable[ipaddress.IPv4Network]
) -> Iterable[ipaddress.IPv4Network]:
    occupied_set = {net for net in occupied if block.supernet_of(net)}
    for sub in block.subnets(new_prefix=prefix):
        if sub in occupied_set:
            continue
        yield sub


def suggest_subnets(
    clients: int,
    count: int,
    explicit_block: Optional[ipaddress.IPv4Network],
) -> Tuple[List[ipaddress.IPv4Network], int]:
    prefix = smallest_prefix(clients)
    occupied = sorted(
        {net for _r, net in iter_subnets() if net.prefixlen == prefix},
        key=lambda n: int(n.network_address),
    )

    if explicit_block is not None:
        if explicit_block.prefixlen > prefix:
            raise SystemExit(
                f"--block {explicit_block} prefix /{explicit_block.prefixlen} "
                f"is smaller than the required /{prefix}."
            )
        candidate_blocks = [explicit_block]
    else:
        candidate_blocks = umbrella_blocks_for(prefix)
        if not candidate_blocks:
            raise SystemExit(
                f"no umbrella block established for prefix /{prefix}; pass "
                f"--block <cidr> to bootstrap a new one manually."
            )

    suggestions: List[ipaddress.IPv4Network] = []
    gaps_filled = 0
    for block in candidate_blocks:
        for sub in gap_first_subnets(block, prefix, occupied):
            suggestions.append(sub)
            gaps_filled += 1
            occupied.append(sub)
            if len(suggestions) >= count:
                break
        if len(suggestions) >= count:
            break

    if len(suggestions) < count:
        raise SystemExit(
            f"available umbrella blocks {[str(b) for b in candidate_blocks]} "
            f"cannot satisfy --count {count} subnet(s) at /{prefix}."
        )

    return suggestions, gaps_filled


def capacity_for(network: ipaddress.IPv4Network) -> int:
    if network.prefixlen >= 31:
        return 0
    return network.num_addresses - 2


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cli meta networks suggest",
        description=(
            "Suggest free per-role IPv4 subnets based on the live role tree. "
            "Picks the smallest CIDR prefix that fits --clients, then "
            "proposes free sub-blocks gap-first within established umbrella "
            "blocks (or --block when given)."
        ),
    )
    parser.add_argument(
        "--clients",
        type=int,
        required=True,
        help="minimum number of usable client IPs the subnet must fit.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="how many free subnets to return (default: 1).",
    )
    parser.add_argument(
        "--block",
        help=(
            "force suggestions inside a specific umbrella block, e.g. "
            "'192.168.101.0/24'."
        ),
    )

    args = parser.parse_args(argv)
    if args.count < 1:
        raise SystemExit("--count must be >= 1")

    explicit_block: Optional[ipaddress.IPv4Network] = None
    if args.block:
        try:
            explicit_block = ipaddress.IPv4Network(args.block)
        except (ipaddress.AddressValueError, ValueError) as exc:
            raise SystemExit(f"invalid --block {args.block!r}: {exc}") from exc

    suggestions, gaps = suggest_subnets(args.clients, args.count, explicit_block)

    for sub in suggestions:
        print(str(sub))
    sys.stderr.write(
        f"# clients={args.clients} prefix=/{suggestions[0].prefixlen} "
        f"capacity={capacity_for(suggestions[0])} returned={len(suggestions)} "
        f"gaps={gaps}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
