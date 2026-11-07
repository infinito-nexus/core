"""Golden guard for ``python -m cli.meta.ci.variant_tree``.

The tree is the operator's view of what one CI row deploys. It must read the
same resolver the deploy does, so its closure is the ``resolve_round`` include
and every pinned partner names the pin that moved it.
"""

from __future__ import annotations

import json
import unittest

from cli.meta.ci.variant_tree import tree
from utils.cache.applications import get_variants
from utils.cache.yaml import dump_yaml_str, load_yaml_str
from utils.roles.applications import variants as round_variants

from . import PROJECT_ROOT

ROLES_DIR = str(PROJECT_ROOT / "roles")
UNPINNED_ROW = "web-app-nextcloud#1"

SHARED = {
    "svc-ai-libretranslate-engine",
    "svc-bkp-secrets-2-local",
    "svc-bkp-volume-2-local",
    "svc-db-mariadb",
    "svc-db-openldap",
    "svc-db-postgres",
    "svc-db-redis",
    "svc-net-tor",
    "svc-net-tor-smtp",
    "web-app-dashboard",
    "web-app-discourse",
    "web-app-jitsi",
    "web-app-keycloak",
    "web-app-matomo",
    "web-app-matrix",
    "web-app-prometheus",
    "web-app-stalwart",
    "web-app-weblate",
    "web-svc-asset",
    "web-svc-cdn",
    "web-svc-coturn",
    "web-svc-design",
    "web-svc-file",
    "web-svc-logout",
    "web-svc-mirror",
    "web-svc-seaweedfs",
    "web-svc-simpleicons",
    "web-svc-translate",
}
PINNED = {
    "web-app-keycloak": (0, "pin by web-app-dashboard#0"),
    "web-app-matomo": (0, "pin by web-app-dashboard#0"),
    "web-svc-logout": (0, "pin by web-app-matomo#0"),
}
GOLDEN = {
    "web-app-wordpress#0": (29, SHARED | {"web-app-wordpress"}, "round index", PINNED),
    "web-app-nextcloud#7": (
        29,
        SHARED | {"web-app-nextcloud"},
        "default 0: round past its variants",
        PINNED,
    ),
}


def _tree(tok: str) -> dict:
    return tree.build(
        tok,
        roles_dir=ROLES_DIR,
        variants_per_app=get_variants(roles_dir=ROLES_DIR, readonly=True),
    )


class TestVariantTreeGolden(unittest.TestCase):
    def test_golden_rows(self) -> None:
        for tok, (count, roles, default, pinned) in GOLDEN.items():
            with self.subTest(row=tok):
                built = _tree(tok)
                name, index = tree.parse_token(tok)
                self.assertEqual(built["include_count"], count)
                got = {
                    node["role"]: (node["variant"], node["reason"])
                    for node in built["nodes"]
                }
                want = {
                    role: (index, "primary")
                    if role == name
                    else pinned.get(role, (0, default))
                    for role in roles
                }
                self.assertEqual(got, want)

    def test_the_closure_is_the_resolve_round_include(self) -> None:
        variants = get_variants(roles_dir=ROLES_DIR, readonly=True)
        resolved = round_variants.resolve_round(
            roles_dir=ROLES_DIR,
            round_index=7,
            primary_app_variants={"web-app-nextcloud": 7},
            variants_per_app=variants,
        )
        self.assertEqual(
            [node["role"] for node in _tree("web-app-nextcloud#7")["nodes"]],
            list(resolved.include),
        )

    def test_negative_control_a_partner_whose_carrier_is_absent_is_not_pinned(
        self,
    ) -> None:
        built = _tree(UNPINNED_ROW)
        roles = {node["role"]: node for node in built["nodes"]}
        self.assertNotIn("web-app-dashboard", roles)
        self.assertFalse(roles["web-app-keycloak"]["reason"].startswith("pin by"))

    def test_the_pin_reason_names_a_carrier_the_resolver_runs(self) -> None:
        variants = get_variants(roles_dir=ROLES_DIR, readonly=True)
        resolved = round_variants.resolve_round(
            roles_dir=ROLES_DIR,
            round_index=0,
            primary_app_variants={"web-app-wordpress": 0},
            variants_per_app=variants,
        )
        for node in _tree("web-app-wordpress#0")["nodes"]:
            if not node["reason"].startswith("pin by "):
                continue
            carrier, _, index = node["reason"].removeprefix("pin by ").partition("#")
            with self.subTest(node=node["role"]):
                self.assertIn(carrier, resolved.include)
                self.assertEqual(resolved.active_index.get(carrier, 0), int(index))

    def test_json_and_yaml_round_trip_to_the_same_structure(self) -> None:
        built = _tree("web-app-wordpress#0")
        self.assertEqual(json.loads(json.dumps(built)), built)
        self.assertEqual(load_yaml_str(dump_yaml_str(built)), built)

    def test_a_malformed_token_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            tree.parse_token("web-app-wordpress#x")

    def test_negative_control_a_variant_the_role_lacks_is_rejected(self) -> None:
        count = len(
            get_variants(roles_dir=ROLES_DIR, readonly=True)["web-app-wordpress"]
        )
        with self.assertRaisesRegex(ValueError, rf"must be 0\.\.{count - 1}"):
            _tree(f"web-app-wordpress#{count}")


if __name__ == "__main__":
    unittest.main()
