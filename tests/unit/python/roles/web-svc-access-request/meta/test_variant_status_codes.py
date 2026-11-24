from __future__ import annotations

import unittest

import yaml

from utils.cache.files import read_text
from utils.domains.default_primary import default_domain_primary
from utils.roles.applications.status_codes import DEFAULT_OK, declared_status_codes
from utils.roles.mapping import ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

APP = "web-svc-access-request"
VARIANTS = PROJECT_ROOT / "roles" / APP / ROLE_FILE_META_VARIANTS
DOMAIN = f"access.{default_domain_primary()}"
SIGN_IN_PAGE = 401


def _variants() -> list[dict]:
    return yaml.safe_load(read_text(str(VARIANTS)))


def _expected_at_root(variant: dict) -> list[int]:
    """Args:
        variant: one entry of the role's ``meta/variants.yml``.

    Returns:
        The codes the health checks expect at ``/``: the declared codes for
        the canonical domain, or ``DEFAULT_OK`` when the variant declares
        none, as ``sys-ctl-hlth-webserver`` resolves them.
    """
    applications = {
        APP: {
            "domains": {"canonical": [DOMAIN]},
            "server": variant.get("server", {}),
        }
    }
    return declared_status_codes(applications, APP, DOMAIN) or list(DEFAULT_OK)


def _gated(variant: dict) -> bool:
    return bool(variant["services"]["sso"]["enabled"])


class TestVariantStatusCodes(unittest.TestCase):
    def test_every_variant_without_the_gate_expects_the_sign_in_page(self) -> None:
        gateless = [variant for variant in _variants() if not _gated(variant)]
        self.assertTrue(gateless, "the matrix must exercise the service without SSO")
        for variant in gateless:
            self.assertEqual(
                [SIGN_IN_PAGE],
                _expected_at_root(variant),
                "without the oauth2-proxy gate identity.py finds no session "
                "header and app.py answers / with the 401 sign-in page",
            )

    def test_every_variant_behind_the_gate_keeps_the_default(self) -> None:
        gated = [variant for variant in _variants() if _gated(variant)]
        self.assertTrue(gated, "the matrix must exercise the service behind SSO")
        for variant in gated:
            self.assertEqual(list(DEFAULT_OK), _expected_at_root(variant))
            self.assertNotIn(SIGN_IN_PAGE, _expected_at_root(variant))

    def test_a_gateless_variant_without_the_declaration_rejects_the_sign_in_page(
        self,
    ) -> None:
        gateless = next(variant for variant in _variants() if not _gated(variant))
        undeclared = {key: value for key, value in gateless.items() if key != "server"}
        self.assertNotIn(SIGN_IN_PAGE, _expected_at_root(undeclared))


if __name__ == "__main__":
    unittest.main()
