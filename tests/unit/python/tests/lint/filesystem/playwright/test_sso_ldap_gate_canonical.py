"""Fixtures and negative controls for the canonical sso/ldap gate lint."""

from __future__ import annotations

import unittest

from tests.lint.filesystem.playwright import test_persona_specs as lint

HEADER = (
    'const { test } = require("@playwright/test");\n'
    'const gating = require("./service-gating");\n'
    'const ssoEnabled = gating.isServiceEnabled("sso");\n'
)
SKIP_ON_SSO = '  test.skip(ssoEnabled, "SSO owns the login");'
REASON = "the flavor, not the service, decides here"


def _findings(text: str, *siblings: str) -> list[tuple[int, str]]:
    return lint.findings_in(text, lint.bindings_in([text, *siblings]))


def _gate(body: str) -> str:
    return HEADER + (
        'test("biber: scenario", async ({ page }) => {\n'
        f"{body}\n"
        '  await page.goto("/");\n'
        "});\n"
    )


class TestSsoLdapGateCanonicalFixtures(unittest.TestCase):
    def test_a_bare_skip_on_an_sso_flag_fails(self) -> None:
        self.assertEqual([(5, "ssoEnabled")], _findings(_gate(SKIP_ON_SSO)))

    def test_the_canonical_helper_passes(self) -> None:
        text = _gate('  gating.skipUnlessServiceDisabled("sso");')
        self.assertEqual([], _findings(text))

    def test_a_skip_on_is_service_enabled_ldap_fails(self) -> None:
        text = _gate('  test.skip(isServiceEnabled("ldap"), "LDAP login");')
        self.assertEqual([(5, 'isServiceEnabled("ldap")')], _findings(text))

    def test_a_negated_shared_env_flag_fails(self) -> None:
        text = _gate('  test.skip(!shared.env.ldapEnabled, "LDAP off");')
        self.assertEqual([(5, "!shared.env.ldapEnabled")], _findings(text))

    def test_a_multi_line_skip_fails_on_its_opening_line(self) -> None:
        text = _gate('  test.skip(\n    shared.env.oidcEnabled,\n    "SSO on",\n  );')
        self.assertEqual([(5, "shared.env.oidcEnabled")], _findings(text))

    def test_a_value_rendered_only_with_sso_fails(self) -> None:
        binding = "const issuer = decode(process.env.OIDC_ISSUER_URL);\n"
        text = binding + _gate('  test.skip(!issuer, "SSO not enabled");')
        self.assertEqual([(6, "!issuer")], _findings(text))

    def test_a_derived_value_bound_in_a_sibling_module_fails(self) -> None:
        sibling = (
            "module.exports = {\n"
            "  env: {\n"
            '    viaKeycloak: isServiceEnabled("sso"),\n'
            "  },\n"
            "};\n"
        )
        text = _gate('  test.skip(!shared.env.viaKeycloak, "no Keycloak");')
        expected = [(5, "!shared.env.viaKeycloak")]
        self.assertEqual(expected, _findings(text, sibling))

    def test_an_if_wrapping_an_unconditional_skip_fails(self) -> None:
        text = _gate('  if (!isServiceEnabled("ldap")) test.skip();')
        self.assertEqual([(5, '!isServiceEnabled("ldap")')], _findings(text))

    def test_an_if_block_wrapping_a_true_skip_fails(self) -> None:
        text = _gate('  if (env.ssoEnabled) {\n    test.skip(true, "SSO on");\n  }')
        self.assertEqual([(6, "env.ssoEnabled")], _findings(text))

    def test_a_fixme_on_an_sso_flag_fails(self) -> None:
        text = _gate('  test.fixme(ssoEnabled, "broken with SSO");')
        self.assertEqual([(5, "ssoEnabled")], _findings(text))

    def test_a_design_gate_passes(self) -> None:
        text = _gate('  test.skip(!galleryEnabled(), "gallery is off");')
        self.assertEqual([], _findings(text))

    def test_the_split_realm_topology_predicate_passes(self) -> None:
        text = _gate('  test.skip(isSplitRealmOidc(), "onion OIDC issuer");')
        self.assertEqual([], _findings(text))

    def test_a_reason_naming_sso_does_not_make_the_gate_an_sso_gate(self) -> None:
        text = _gate('  test.skip(isOnionTarget(), "no SSO or LDAP over Tor");')
        self.assertEqual([], _findings(text))

    def test_a_declared_skipped_test_is_no_gate(self) -> None:
        text = HEADER + 'test.skip("sso: pending", async ({ page }) => {});\n'
        self.assertEqual([], _findings(text))

    def test_an_apostrophe_in_a_comment_does_not_hide_a_gate(self) -> None:
        text = _gate("  // Exception: the form isn't rendered\n" + SKIP_ON_SSO)
        self.assertEqual([(6, "ssoEnabled")], _findings(text))

    def test_a_reasoned_marker_on_the_same_line_suppresses(self) -> None:
        text = _gate(f"{SKIP_ON_SSO} // nocheck: {lint.RULE} -- {REASON}")
        self.assertEqual([], _findings(text))

    def test_a_reasoned_marker_on_the_line_above_suppresses(self) -> None:
        text = _gate(f"  // nocheck: {lint.RULE} -- {REASON}\n{SKIP_ON_SSO}")
        self.assertEqual([], _findings(text))

    def test_a_bare_marker_grants_nothing(self) -> None:
        text = _gate(f"{SKIP_ON_SSO} // nocheck: {lint.RULE}")
        self.assertEqual([(5, "ssoEnabled")], _findings(text))

    def test_a_marker_for_another_rule_grants_nothing(self) -> None:
        text = _gate(f"{SKIP_ON_SSO} // nocheck: unguarded-env-default -- {REASON}")
        self.assertEqual([(5, "ssoEnabled")], _findings(text))


if __name__ == "__main__":
    unittest.main()
