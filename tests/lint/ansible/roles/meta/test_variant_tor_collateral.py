"""A clearnet round may not quietly take an onion-capable partner down with it.

A variant that pins ``tor.enabled: false`` serves every service it enables
over clearnet only. That is unavoidable for the partner forcing the drop - the
real-time media roles pin ``tor.enabled`` to a literal ``false`` because onion
routing breaks their transport - and for the role the variant belongs to. It
is not unavoidable for the others: ``web-app-gitlab`` carries the dynamic flag
and serves fine over the onion, yet sat in a round that had dropped it, so the
matrix-gitlab bridge was only ever proven from a clearnet origin.

A variant that takes such partners down with it therefore needs
``# nocheck: variant-tor-collateral`` on its own ``tor`` pin, with text naming
why those partners belong in a clearnet round. The marker sits on the pin that
makes the decision rather than on each affected service, because the reason is
one fact about the round, not one per partner.

The round is read from ``get_variants``, the merged view: a service the base
``meta/services.yml`` enables counts even when the variant never names it.
Reading the override file alone would miss those and under-report.

Backends are out of scope: they publish no surface, so the onion means nothing
to them even though they carry the same consumer flag.
"""

from __future__ import annotations

import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.applications import get_variants
from utils.cache.files import read_text
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

from . import ROLES_DIR, load_role_meta, role_dirs

RULE = "variant-tor-collateral"
TOR_KEY = "tor"


def _incapable_roles() -> set[str]:
    """Roles whose own ``services.tor.enabled`` is a literal ``false``."""
    found: set[str] = set()
    for role_dir in role_dirs():
        services = load_role_meta(role_dir / ROLE_FILE_META_SERVICES)
        tor = services.get(TOR_KEY) if isinstance(services, dict) else None
        if isinstance(tor, dict) and tor.get("enabled") is False:
            found.add(role_dir.name)
    return found


def _variant_spans(lines: list[str]) -> list[range]:
    """The line range each top-level list entry occupies.

    Args:
        lines: the variants file's lines.
    """
    starts = [n for n, line in enumerate(lines, 1) if line.startswith("- ")]
    bounds = [*starts[1:], len(lines) + 1]
    return [range(start, end) for start, end in zip(starts, bounds, strict=True)]


def _pin_line(lines: list[str], span: range, key: str) -> int | None:
    """The line declaring *key* inside one variant entry.

    Args:
        lines: the variants file's lines.
        span: the variant's line range.
        key: the service key to locate.
    """
    for number in span:
        if lines[number - 1].strip().startswith(f"{key}:"):
            return number
    return None


def _collateral(
    services: dict, role: str, registry: dict, incapable: set[str]
) -> list[str]:
    """Onion-capable frontend partners a clearnet round keeps enabled.

    Args:
        services: the variant's merged ``services`` mapping.
        role: the role the variant belongs to.
        registry: service key to registry entry.
        incapable: roles that refuse the onion outright.
    """
    return sorted(
        key
        for key, entry in services.items()
        if isinstance(entry, dict)
        and entry.get("enabled") is True
        and (registry.get(key) or {}).get("service_type") == "frontend"
        and (registry.get(key) or {}).get("role") not in incapable
        and (registry.get(key) or {}).get("role") != role
    )


class TestVariantTorCollateral(unittest.TestCase):
    def test_every_onion_capable_frontend_in_a_clearnet_round_is_justified(
        self,
    ) -> None:
        incapable = _incapable_roles()
        registry = build_service_registry_from_roles_dir(ROLES_DIR)
        offenders: list[str] = []

        for role, variants in sorted(get_variants().items()):
            if role in incapable:
                continue
            path = ROLES_DIR / role / ROLE_FILE_META_VARIANTS
            if not path.is_file():
                continue
            lines = read_text(str(path)).splitlines()
            spans = _variant_spans(lines)
            for index, variant in enumerate(variants):
                services = variant.get("services") or {}
                if (services.get(TOR_KEY) or {}).get("enabled") is not False:
                    continue
                if index >= len(spans):
                    continue
                collateral = _collateral(services, role, registry, incapable)
                if not collateral:
                    continue
                number = _pin_line(lines, spans[index], TOR_KEY)
                if number is None or not is_suppressed_at(lines, number, RULE):
                    offenders.append(
                        f"{role} variant {index}: drops the onion while pinning "
                        f"{', '.join(collateral)} on, all of which serve over it"
                    )

        if offenders:
            self.fail(
                f"{len(offenders)} clearnet round(s) take an onion-capable partner "
                "down with them. Move the partner into a variant that keeps the "
                f"onion, or mark the tor pin '# nocheck: {RULE} <why they belong "
                "here>':\n" + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
