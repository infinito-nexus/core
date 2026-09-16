"""The swarm matrix bakes a variant payload for every app it deploys."""

from __future__ import annotations

import unittest
from typing import ClassVar

from cli.administration.deploy.development.inventory.payload import (
    _resolve_variant_payloads,
    get_variant_overrides_only,
)
from cli.administration.deploy.development.inventory.planner import (
    plan_dev_inventory_matrix,
)
from utils.cache.files import PROJECT_ROOT
from utils.tests.swarm.derive_includes import (
    _EXPLICIT_INCLUDES,
    derive_includes,
    variant_scope,
)

_ROLES_DIR = str(PROJECT_ROOT / "roles")


def _rounds(primary: str) -> list[tuple]:
    return plan_dev_inventory_matrix(
        roles_dir=_ROLES_DIR,
        primary_apps=[primary],
        base_inventory_dir="/tmp/variant-payload-scope",
    )


class TestVariantPayloadScope(unittest.TestCase):
    PRIMARIES: ClassVar[tuple[str, ...]] = (
        "svc-ai-litellm",
        "web-app-bigbluebutton",
        "web-app-peertube",
        "web-app-nextcloud",
    )

    def test_every_deployed_app_receives_its_declared_override(self) -> None:
        overrides = get_variant_overrides_only(roles_dir=_ROLES_DIR)
        for primary in self.PRIMARIES:
            for round_index, _inv, round_variants, _include, *_ in _rounds(primary):
                scope = variant_scope(primary, variants=round_variants)
                payloads = _resolve_variant_payloads(
                    roles_dir=_ROLES_DIR,
                    include=scope,
                    active_variants=round_variants,
                )
                for app in derive_includes(primary, variants=round_variants):
                    declared = overrides.get(app) or []
                    if not declared:
                        continue
                    index = round_variants.get(app, 0)
                    if not 0 <= index < len(declared):
                        index = 0
                    if not declared[index] or app in _EXPLICIT_INCLUDES:
                        continue
                    self.assertIn(
                        app,
                        payloads,
                        f"{primary}#{round_index} deploys {app}, whose variants.yml "
                        f"declares an override, but the inventory bakes none, so it "
                        f"silently runs on its base config",
                    )

    def test_a_dependency_keeps_its_override_when_the_include_collapses(self) -> None:
        primary = "svc-ai-litellm"
        for round_index, _inv, round_variants, round_include, *_ in _rounds(primary):
            if "web-app-keycloak" not in variant_scope(
                primary, variants=round_variants
            ):
                continue
            payloads = _resolve_variant_payloads(
                roles_dir=_ROLES_DIR,
                include=variant_scope(primary, variants=round_variants),
                active_variants=round_variants,
            )
            realm = (
                payloads.get("web-app-keycloak", {})
                .get("services", {})
                .get("keycloak", {})
                .get("realm", {})
            )
            self.assertIs(
                realm.get("totp_enabled"),
                False,
                f"{primary}#{round_index} deploys keycloak with "
                f"{len(round_include)} planned app(s); without its variant override "
                f"the realm demands CONFIGURE_TOTP and every SSO persona times out",
            )


if __name__ == "__main__":
    unittest.main()
