"""Shared variant-selection for the dev-deploy ``init`` and ``deploy`` commands.

A single ``--variant`` (comma-separated, zero-based) selects the matrix rounds a
run iterates: ``2`` pins one round, ``0,1,2`` is the runner-split bundle from CI
discovery, empty/unset is the full matrix. One value is just a one-element
bundle — there is no separate "variants" flag — and whether inter-round cleanup
runs follows the number of selected rounds, not the flag. Centralising this here
keeps init and deploy walking the exact same selection (SPOT)."""

from __future__ import annotations

import argparse
import os

from .inventory import filter_plan_to_variants


def parse_variant_csv(raw: str) -> list[int]:
    try:
        return [int(tok.strip()) for tok in raw.split(",") if tok.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"must be a comma-separated list of integers, got {raw!r}"
        ) from None


def env_variant() -> list[int] | None:
    raw = os.environ.get("variant", "").strip()
    if not raw:
        return None
    try:
        return parse_variant_csv(raw)
    except argparse.ArgumentTypeError as exc:
        raise SystemExit(f"variant environment variable {exc}") from None


def add_variant_args(parser: argparse.ArgumentParser, *, action: str) -> None:
    parser.add_argument(
        "--variant",
        type=parse_variant_csv,
        default=env_variant(),
        help=(
            f"Pin the matrix {action} to one or more rounds (comma-separated "
            "zero-based indices, e.g. `2` or `0,1,2`). A single index pins one "
            "round; multiple indices are the runner-split bundle. Empty/unset = "
            "full matrix. Defaults to the variant environment variable when set."
        ),
    )


def apply_variant_filter(plan, args):
    """Filter `plan` to the rounds in `--variant`; empty/None = full matrix."""
    return filter_plan_to_variants(plan, args.variant or None)
