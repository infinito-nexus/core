from __future__ import annotations

import json
import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VARIANTS

from .test_realm_import_json import (
    CLIENT_APPS,
    ROLE_DIR,
    ROLE_SERVICES,
    ROLE_VARS,
    organizations_context,
    render,
)

FLOW = ROLE_VARS["KEYCLOAK_ORGANIZATION_FLOW"]
SCOPE = ROLE_VARS["KEYCLOAK_WORKSPACE_ROLES_SCOPE"]
CLAIM = ROLE_VARS["KEYCLOAK_WORKSPACE_ROLES_CLAIM"]
WORKSPACES = ROLE_VARS["KEYCLOAK_WORKSPACES_CLIENT_ID"]
CLIENT_ROLE_MAPPER = "oidc-usermodel-client-role-mapper"
STOCK_MAPPER_CONFIG = {
    "usermodel.clientRoleMapping.clientId": WORKSPACES,
    "usermodel.clientRoleMapping.rolePrefix": "",
    "multivalued": "true",
    "claim.name": CLAIM,
    "access.token.claim": "true",
    "id.token.claim": "true",
    "userinfo.token.claim": "true",
}
FLOWS = ("standardFlowEnabled", "implicitFlowEnabled", "directAccessGrantsEnabled")


def realm(enabled: bool) -> dict:
    """
    Args:
        enabled: the organizations switch.

    Returns:
        The parsed realm import with every client-declaring app.
    """
    return json.loads(
        render([], client_apps=CLIENT_APPS, overrides=organizations_context(enabled))
    )


def organization_execution(realm: dict) -> str:
    """
    Args:
        realm: the parsed realm import.

    Returns:
        The requirement of the ``organization`` execution of the browser sub-flow.
    """
    flow = next(f for f in realm["authenticationFlows"] if f["alias"] == FLOW)
    return next(
        e["requirement"]
        for e in flow["authenticationExecutions"]
        if e.get("authenticator") == "organization"
    )


def switch_findings(realm: dict, enabled: bool) -> list[str]:
    """
    Args:
        realm: the parsed realm import.
        enabled: the switch the realm was rendered with.

    Returns:
        What keeps ``realm`` from following the organizations switch.
    """
    want = ("DISABLED", True) if enabled else ("ALTERNATIVE", False)
    have = (organization_execution(realm), realm["organizationsEnabled"])
    return [] if have == want else [f"expected {want}, found {have}"]


def every_mapper(realm: dict) -> list[dict]:
    """
    Args:
        realm: the parsed realm import.

    Returns:
        Every protocol mapper of every client and client scope.
    """
    return [
        mapper
        for entity in realm["clients"] + realm["clientScopes"]
        for mapper in entity.get("protocolMappers", [])
    ]


def claim_findings(realm: dict) -> list[str]:
    """
    Args:
        realm: the parsed realm import.

    Returns:
        What keeps ``realm`` from writing the flat claim with one stock mapper only.
    """
    scopes = [s for s in realm["clientScopes"] if s["name"] == SCOPE]
    if len(scopes) != 1:
        return [f"{len(scopes)} client scopes are named {SCOPE}"]
    mappers = scopes[0].get("protocolMappers", [])
    findings = [
        f"mapper {m['name']} is {m['protocolMapper']}"
        for m in mappers
        if m["protocolMapper"] != CLIENT_ROLE_MAPPER
    ]
    if len(mappers) != 1:
        findings.append(f"{len(mappers)} mappers in {SCOPE}")
    for mapper in mappers:
        findings.extend(
            f"{key} is {mapper['config'].get(key)!r}"
            for key, value in STOCK_MAPPER_CONFIG.items()
            if mapper["config"].get(key) != value
        )
    findings.extend(
        f"script mapper {m['name']}"
        for m in every_mapper(realm)
        if "script" in m["protocolMapper"]
    )
    return findings


class TestOrganizationsSwitch(unittest.TestCase):
    def test_services_declare_the_switch_off(self) -> None:
        self.assertIs(ROLE_SERVICES["keycloak"]["organizations"]["enabled"], False)

    def test_variant_zero_turns_the_switch_on(self) -> None:
        variants = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_VARIANTS))
        switches = [
            v.get("services", {})
            .get("keycloak", {})
            .get("organizations", {})
            .get("enabled")
            for v in variants
        ]
        self.assertIs(switches[0], True)
        self.assertNotIn(True, switches[1:])

    def test_organizations_follow_their_switch(self) -> None:
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.assertEqual(switch_findings(realm(enabled), enabled), [])

    def test_the_switch_check_catches_an_enabled_login_step(self) -> None:
        on = realm(True)
        flow = next(f for f in on["authenticationFlows"] if f["alias"] == FLOW)
        for execution in flow["authenticationExecutions"]:
            if execution.get("authenticator") == "organization":
                execution["requirement"] = "ALTERNATIVE"
        self.assertTrue(switch_findings(on, True))

    def test_the_switch_check_catches_organizations_left_off(self) -> None:
        on = realm(True)
        on["organizationsEnabled"] = False
        self.assertTrue(switch_findings(on, True))

    def test_without_the_switch_no_workspace_entity_joins_the_realm(self) -> None:
        off = realm(False)
        self.assertNotIn(SCOPE, {s["name"] for s in off["clientScopes"]})
        client_ids = {c["clientId"] for c in off["clients"]}
        self.assertNotIn(WORKSPACES, client_ids)
        self.assertNotIn(ROLE_VARS["KEYCLOAK_WORKSPACE_MEMBERS_CLIENT_ID"], client_ids)


class TestFlatClaim(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.realm = realm(True)

    def test_the_flat_claim_uses_a_stock_mapper(self) -> None:
        self.assertEqual(claim_findings(self.realm), [])

    def test_the_claim_check_catches_a_script_mapper(self) -> None:
        planted = json.loads(json.dumps(self.realm))
        scope = next(s for s in planted["clientScopes"] if s["name"] == SCOPE)
        scope["protocolMappers"].append(
            {
                "name": "flat",
                "protocolMapper": "oidc-script-based-protocol-mapper",
                "config": {},
            }
        )
        self.assertTrue(claim_findings(planted))

    def test_the_claim_check_catches_a_prefixed_or_single_valued_claim(self) -> None:
        for key, value in (
            ("usermodel.clientRoleMapping.rolePrefix", "ws:"),
            ("multivalued", "false"),
            ("userinfo.token.claim", "false"),
        ):
            with self.subTest(key=key):
                planted = json.loads(json.dumps(self.realm))
                scope = next(s for s in planted["clientScopes"] if s["name"] == SCOPE)
                scope["protocolMappers"][0]["config"][key] = value
                self.assertTrue(claim_findings(planted))

    def test_the_workspaces_client_enables_no_flow(self) -> None:
        client = next(c for c in self.realm["clients"] if c["clientId"] == WORKSPACES)
        self.assertEqual(
            [flow for flow in (*FLOWS, "serviceAccountsEnabled") if client[flow]], []
        )
        self.assertEqual(client["redirectUris"], [])


if __name__ == "__main__":
    unittest.main()
