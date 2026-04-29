#!/usr/bin/env python3
"""Suggest free host-bound ports based on the live role tree (req-009).

Walks every ``roles/*/meta/services.yml``, collects occupied
``<entity>.ports.{local,public}.<category>`` assignments per scope+category,
and proposes the lowest free port(s) within
``PORT_BANDS.<scope>.<category>`` from ``group_vars/all/08_networks.yml``.

`inter` is NOT supported: internal container ports are dictated by the
upstream image, not by a project-managed pool.

Usage:

  cli meta ports suggest --scope local --category http --count 3
  cli meta ports suggest --scope public --category relay --length 10000 --count 1
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional, Tuple

from utils.meta.port_bands import (
    PortBandsError,
    available_categories,
    lookup_band,
)
from utils.meta.scan import (
    occupied_ports_for,
    occupied_relay_ranges,
)


def _parse_range(text: str) -> Tuple[int, int]:
    head, _, tail = text.partition("-")
    try:
        start = int(head)
        end = int(tail)
    except ValueError as exc:
        raise SystemExit(f"--range expects '<start>-<end>', got {text!r}") from exc
    if start > end:
        raise SystemExit(f"--range start ({start}) must be <= end ({end})")
    return start, end


def suggest_single_ports(
    scope: str,
    category: str,
    count: int,
    explicit_range: Optional[Tuple[int, int]],
) -> Tuple[List[int], int]:
    """Return ``(suggestions, gap_count)``.

    `gap_count` is the number of suggestions that came from a band gap (vs.
    appended after `max(used) + 1`).
    """
    if explicit_range is not None:
        band = explicit_range
    else:
        band = lookup_band(scope, category)
        if band is None:
            cats = available_categories(scope)
            raise SystemExit(
                f"no PORT_BANDS entry for scope={scope!r} category={category!r}; "
                f"pass --range '<start>-<end>' or extend PORT_BANDS in "
                f"group_vars/all/08_networks.yml. Available categories under "
                f"scope={scope!r}: {cats}"
            )

    start, end = band
    occupied = set(occupied_ports_for(scope, category))
    suggestions: List[int] = []
    gaps_filled = 0

    cursor = start
    while len(suggestions) < count and cursor <= end:
        if cursor not in occupied:
            suggestions.append(cursor)
            gaps_filled += 1 if cursor < (max(occupied) if occupied else start) else 0
            occupied.add(cursor)
        cursor += 1

    if len(suggestions) < count:
        raise SystemExit(
            f"PORT_BANDS.{scope}.{category} ({start}-{end}) cannot satisfy "
            f"--count {count} (only {len(suggestions)} free ports)."
        )

    return suggestions, gaps_filled


def _ranges_overlap(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
    a_start, a_end = a
    b_start, b_end = b
    return not (a_end < b_start or b_end < a_start)


def suggest_relay_ranges(
    length: int, count: int, explicit_range: Optional[Tuple[int, int]]
) -> Tuple[List[Tuple[int, int]], int]:
    if explicit_range is not None:
        band = explicit_range
    else:
        band = lookup_band("public", "relay")
        if band is None:
            raise SystemExit(
                "no PORT_BANDS.public.relay entry; pass --range '<start>-<end>' "
                "or extend PORT_BANDS in group_vars/all/08_networks.yml."
            )

    band_start, band_end = band
    occupied = list(occupied_relay_ranges())

    suggestions: List[Tuple[int, int]] = []
    gaps_filled = 0
    cursor = band_start

    sorted_occ = sorted(occupied + [(band_end + 1, band_end + 1)])

    while len(suggestions) < count and cursor + length - 1 <= band_end:
        candidate = (cursor, cursor + length - 1)
        clash = next(
            (occ for occ in sorted_occ if _ranges_overlap(candidate, occ)),
            None,
        )
        if clash is None:
            suggestions.append(candidate)
            gaps_filled += 1
            cursor = candidate[1] + 1
        else:
            cursor = clash[1] + 1

    if len(suggestions) < count:
        raise SystemExit(
            f"PORT_BANDS.public.relay ({band_start}-{band_end}) cannot fit "
            f"--count {count} contiguous range(s) of --length {length}."
        )

    return suggestions, gaps_filled


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cli meta ports suggest",
        description=(
            "Suggest free host-bound ports based on the live role tree. "
            "Allocates from PORT_BANDS.<scope>.<category> in "
            "group_vars/all/08_networks.yml; gap-first then increment."
        ),
    )
    parser.add_argument(
        "--scope",
        required=True,
        choices=("local", "public"),
        help="port scope; 'inter' is NOT supported.",
    )
    parser.add_argument(
        "--category",
        required=True,
        help=(
            "category band (e.g. http, websocket, oauth2, ssh, federation, "
            "stun_turn, relay)."
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="how many free ports/ranges to return (default: 1)",
    )
    parser.add_argument(
        "--range",
        dest="explicit_range",
        help="override the band (e.g. '8001-8099') for ad-hoc allocations",
    )
    parser.add_argument(
        "--length",
        type=int,
        help=(
            "for --category relay: inclusive port count of the contiguous "
            "range (start..start+length-1). Required for relay."
        ),
    )

    args = parser.parse_args(argv)

    if args.count < 1:
        raise SystemExit("--count must be >= 1")

    explicit = _parse_range(args.explicit_range) if args.explicit_range else None

    try:
        if args.category == "relay":
            if not args.length or args.length < 2:
                raise SystemExit("--category relay requires --length >= 2")
            suggestions, gaps = suggest_relay_ranges(args.length, args.count, explicit)
            for start, end in suggestions:
                print(f"{start}-{end}")
            band_label = (
                "PORT_BANDS.public.relay"
                if explicit is None
                else f"--range {explicit[0]}-{explicit[1]}"
            )
            sys.stderr.write(
                f"# {band_label}: returned {len(suggestions)} range(s), "
                f"{gaps} from gaps.\n"
            )
        else:
            suggestions, gaps = suggest_single_ports(
                args.scope, args.category, args.count, explicit
            )
            for port in suggestions:
                print(port)
            band_label = (
                f"PORT_BANDS.{args.scope}.{args.category}"
                if explicit is None
                else f"--range {explicit[0]}-{explicit[1]}"
            )
            sys.stderr.write(
                f"# {band_label}: returned {len(suggestions)} port(s), "
                f"{gaps} from gaps.\n"
            )
    except PortBandsError as exc:
        raise SystemExit(str(exc)) from exc

    return 0


if __name__ == "__main__":
    sys.exit(main())
