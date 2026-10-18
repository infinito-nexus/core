"""A variant may drop the onion only when something in it cannot carry one.

``services.tor`` is a consumer flag, not a capability: every role declares the
same ``enabled: "{{ 'svc-net-tor' in group_names }}"`` and so joins the onion
whenever ``svc-net-tor`` is deployed. A handful of roles pin it to a literal
``false`` instead, because onion routing breaks their transport - the
real-time media services. Those are the only legitimate reason for a variant
to pin ``tor.enabled: false``.

A variant that drops the onion without one of them in scope removes onion
coverage from every service it does enable, for nothing. ``web-app-gitlab`` is
the case that motivated this guard: it carries the dynamic flag and works over
the onion, yet sat in a round that had dropped it.

Scope: a variant is excused when its own role is one of the incapable ones, or
when it pins a service whose provider role is. A role coupled only through
``group_names`` is invisible here, which is why the failure message asks for a
pin rather than assuming the author is wrong.
"""

from __future__ import annotations

import unittest

from utils.cache.applications import get_variants
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import ROLES_DIR, load_role_meta, role_dirs

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


def _service_providers() -> dict[str, str]:
    """Map every service key to the role that provides it."""
    registry = build_service_registry_from_roles_dir(ROLES_DIR)
    return {
        key: entry["role"]
        for key, entry in registry.items()
        if isinstance(entry, dict) and entry.get("role")
    }


class TestVariantTorOffNeedsAReason(unittest.TestCase):
    def test_no_variant_drops_the_onion_without_an_incapable_role(self) -> None:
        incapable = _incapable_roles()
        providers = _service_providers()
        offenders: list[str] = []

        for role, variants in sorted(get_variants().items()):
            if role in incapable:
                continue
            for index, variant in enumerate(variants):
                services = variant.get("services") or {}
                if (services.get(TOR_KEY) or {}).get("enabled") is not False:
                    continue
                excused = [
                    key
                    for key, entry in services.items()
                    if isinstance(entry, dict)
                    and entry.get("enabled") is True
                    and providers.get(key) in incapable
                ]
                if not excused:
                    offenders.append(
                        f"{role} variant {index}: pins tor.enabled false while "
                        "enabling nothing that refuses the onion"
                    )

        if offenders:
            self.fail(
                f"{len(offenders)} variant(s) drop the onion for no reason. Either "
                "pin tor.enabled true so the round keeps onion coverage, or pin the "
                "service whose role refuses the onion so the drop is visible:\n"
                + "\n".join(offenders)
            )

    def test_at_least_one_role_refuses_the_onion(self) -> None:
        self.assertTrue(
            _incapable_roles(),
            "no role pins tor.enabled false any more, so every variant dropping "
            "the onion is unjustified and this guard needs rewriting rather than "
            "passing vacuously",
        )


if __name__ == "__main__":
    unittest.main()
