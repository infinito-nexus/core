"""Check the roundtrip's ``apps`` entries before its first deploy.

Usage:
  python -m cli.meta.ci.roundtrip <token> [<token> ...]

Prints one ``<role> <variant>`` line per entry. Exits non-zero, naming the
entry, when one is not a single role and variant: the roundtrip runs every
deploy mode itself, so a token takes ``<role>`` or ``<role>#<variant>`` only.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from utils.cache.applications import get_variants
from utils.github.variant import selection

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def entries(
    tokens: Sequence[str], declared: Mapping[str, Sequence[object]]
) -> list[tuple[str, int]]:
    """Each token as ``(role, variant)``.

    Args:
        tokens: the ``apps`` entries, selection tokens.
        declared: ``{role: its variants}`` of every application role.

    Raises:
        SystemExit: a token pins an axis other than the variant, more than one
            variant, no application role, or a variant its role does not
            declare.
    """
    out = []
    for token in tokens:
        pin = selection.parse(token)
        variants = pin.variants or (0,)
        if any(axis is not None for axis in pin.axes):
            raise SystemExit(
                f"roundtrip: {token!r} pins a deploy axis; the roundtrip runs "
                "every mode itself, so a token takes <role> or <role>#<variant> only"
            )
        if len(variants) != 1:
            raise SystemExit(
                f"roundtrip: {token!r} pins {len(variants)} variants; a token "
                "takes <role> or <role>#<variant> only"
            )
        if pin.app not in declared:
            raise SystemExit(f"roundtrip: {token!r} names no application role")
        if variants[0] >= len(declared[pin.app]):
            raise SystemExit(
                f"roundtrip: {token!r} pins a variant {pin.app} does not declare "
                f"({len(declared[pin.app])} variant(s))"
            )
        out.append((pin.app, variants[0]))
    return out


def main(argv: list[str] | None = None) -> int:
    for app, variant in entries(
        sys.argv[1:] if argv is None else argv, get_variants(readonly=True)
    ):
        print(app, variant)
    return 0


if __name__ == "__main__":
    sys.exit(main())
