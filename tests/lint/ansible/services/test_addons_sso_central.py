"""Lint: single sign-on reaches Keycloak through the central ``sso`` service only.

Every role's OIDC or SAML client addon bridges the role's ``sso`` service
block, which the shared Keycloak realm satisfies centrally. An
addon that bridges a ``keycloak``, ``oidc``, ``openid`` or ``saml`` key instead
would wire a second, per-role SSO path beside the central one, so such a bridge
key fails here.
"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_DIR_META_ADDONS

from . import PROJECT_ROOT

CENTRAL_SSO_KEY = "sso"

NON_CENTRAL_SSO_KEYS: frozenset[str] = frozenset({"keycloak", "oidc", "openid", "saml"})


def non_central_sso_problems(roles_dir: Path) -> list[str]:
    """Return one line per addon bridge that bypasses the central ``sso`` service.

    Args:
        roles_dir: the repository's ``roles`` directory.
    """
    problems: list[str] = []
    for addon_file in sorted(roles_dir.glob(f"*/{ROLE_DIR_META_ADDONS}/*.yml")):
        spec = load_yaml_any(str(addon_file), default_if_missing={}) or {}
        bridges = spec.get("bridges") if isinstance(spec, Mapping) else None
        if not isinstance(bridges, list):
            continue
        role = addon_file.relative_to(roles_dir).parts[0]
        problems.extend(
            f"{role}: {ROLE_DIR_META_ADDONS}/{addon_file.name} bridges {key!r}; "
            f"bridge {CENTRAL_SSO_KEY!r}, which the central Keycloak realm serves"
            for key in bridges
            if str(key).lower() in NON_CENTRAL_SSO_KEYS
        )
    return problems


class TestAddonsSsoCentral(unittest.TestCase):
    def test_no_addon_bridges_sso_around_the_central_service(self) -> None:
        problems = non_central_sso_problems(PROJECT_ROOT / "roles")
        self.assertEqual(
            [],
            problems,
            f"addon(s) bypassing the central sso service ({len(problems)}):\n  "
            + "\n  ".join(problems),
        )

    def test_the_rule_reports_each_non_central_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            addons = roles_dir / "web-app-a" / ROLE_DIR_META_ADDONS
            addons.mkdir(parents=True)
            (addons / "central.yml").write_text("bridges: [sso, ldap]\n", "utf-8")
            (addons / "direct.yml").write_text("bridges: [keycloak]\n", "utf-8")
            (addons / "protocol.yml").write_text("bridges: [sso, OIDC]\n", "utf-8")
            (addons / "plain.yml").write_text("mechanism: plugin\n", "utf-8")

            problems = non_central_sso_problems(roles_dir)

        self.assertEqual(2, len(problems), problems)
        self.assertTrue(any("direct.yml bridges 'keycloak'" in p for p in problems))
        self.assertTrue(any("protocol.yml bridges 'OIDC'" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
