from __future__ import annotations

import unittest

from . import PROJECT_ROOT
from .test_backchannel_clients import (
    canonical_origin,
    onion_sibling,
    render_fragment,
    role_config,
)
from .test_realm_import_json import (
    ALLOWED_ORIGINS_MAPPER,
    CONTEXT,
    puts_allowed_origins_into_access_tokens,
)

TEMPLATE = PROJECT_ROOT / "roles/web-app-dashboard/templates/keycloak/clients.json.j2"
READ_SCOPES = {"profile", "roles", CONTEXT["KEYCLOAK_RBAC_GROUP_CLAIM"]}


def dashboard_client_findings(client: dict) -> list[str]:
    """What keeps the dashboard client from being a PKCE-only public token holder.

    Args:
        client: the dashboard client's representation.
    """
    attributes = client["attributes"]
    findings = []
    if client["publicClient"] is not True:
        findings.append("publicClient is not true")
    if client["serviceAccountsEnabled"] is not False:
        findings.append("serviceAccountsEnabled is not false")
    if client["standardFlowEnabled"] is not True:
        findings.append("the standard flow is off")
    if client["implicitFlowEnabled"] or client["directAccessGrantsEnabled"]:
        findings.append("a flow beside the standard flow is on")
    if attributes.get("pkce.code.challenge.method") != "S256":
        findings.append("PKCE S256 is not enforced")
    if not puts_allowed_origins_into_access_tokens(client):
        findings.append("its access tokens carry no allowed-origins")
    return findings


class TestDashboardClient(unittest.TestCase):
    def setUp(self) -> None:
        (self.client,) = render_fragment(TEMPLATE)

    def test_the_client_id_comes_from_the_dashboard_config(self) -> None:
        self.assertEqual(
            self.client["clientId"],
            role_config("web-app-dashboard", "services.sso.oidc.clients.dashboard"),
        )

    def test_it_is_a_public_pkce_client_whose_tokens_carry_allowed_origins(
        self,
    ) -> None:
        self.assertEqual(dashboard_client_findings(self.client), [])

    def test_its_one_mapper_is_the_allowed_origins_mapper(self) -> None:
        (mapper,) = self.client["protocolMappers"]
        self.assertEqual(mapper["protocolMapper"], ALLOWED_ORIGINS_MAPPER)
        self.assertEqual(mapper["config"]["access.token.claim"], "true")

    def test_every_network_sibling_may_sign_in_and_out(self) -> None:
        siblings = onion_sibling(canonical_origin("web-app-dashboard"))
        self.assertEqual(self.client["webOrigins"], siblings)
        redirects = [f"{origin}/*" for origin in siblings]
        self.assertEqual(self.client["redirectUris"], redirects)
        self.assertEqual(
            self.client["attributes"]["post.logout.redirect.uris"].split("##"),
            redirects,
        )

    def test_it_reads_the_claims_the_dashboard_relies_on(self) -> None:
        self.assertLessEqual(READ_SCOPES, set(self.client["defaultClientScopes"]))
        self.assertTrue(
            self.client["fullScopeAllowed"], "the account audience needs it"
        )

    def test_its_logout_still_runs_the_conductor_sweep(self) -> None:
        attributes = self.client["attributes"]
        self.assertTrue(self.client["frontchannelLogout"])
        self.assertEqual(
            attributes["frontchannel.logout.url"],
            CONTEXT["KEYCLOAK_FRONTCHANNEL_LOGOUT_URL"],
        )
        self.assertNotIn("backchannel.logout.url", attributes)

    def test_a_confidential_client_without_pkce_fails_the_check(self) -> None:
        client = {
            **self.client,
            "publicClient": False,
            "attributes": {
                **self.client["attributes"],
                "pkce.code.challenge.method": "",
            },
        }
        self.assertEqual(
            dashboard_client_findings(client),
            ["publicClient is not true", "PKCE S256 is not enforced"],
        )

    def test_a_client_whose_mapper_stays_out_of_the_access_token_fails_the_check(
        self,
    ) -> None:
        mapper = {
            **self.client["protocolMappers"][0],
            "config": {"access.token.claim": "false"},
        }
        client = {**self.client, "protocolMappers": [mapper]}
        self.assertEqual(
            dashboard_client_findings(client),
            ["its access tokens carry no allowed-origins"],
        )


if __name__ == "__main__":
    unittest.main()
