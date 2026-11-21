"""Unit tests for the email policy filters of ``roles/web-app-keycloak``."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from ansible.errors import AnsibleFilterError

PLUGINS = (
    Path(__file__).parent / "../../../../../../roles/web-app-keycloak/filter_plugins"
).resolve()
POLICIES = ["mailbox", "external"]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, PLUGINS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestHeldEmailPolicy(unittest.TestCase):
    def setUp(self):
        self.m = _load("email_policy")

    def test_a_realm_without_the_attribute_holds_external_addresses(self):
        for realm in ({}, {"attributes": {}}, {"attributes": None}):
            with self.subTest(realm=realm):
                self.assertEqual(
                    self.m.kc_held_email_policy(realm, "infinitoEmailPolicy", POLICIES),
                    "external",
                )

    def test_a_recorded_policy_is_returned(self):
        realm = {"attributes": {"infinitoEmailPolicy": "mailbox"}}
        self.assertEqual(
            self.m.kc_held_email_policy(realm, "infinitoEmailPolicy", POLICIES),
            "mailbox",
        )

    def test_an_unknown_recorded_policy_fails(self):
        realm = {"attributes": {"infinitoEmailPolicy": "both"}}
        with self.assertRaises(AnsibleFilterError):
            self.m.kc_held_email_policy(realm, "infinitoEmailPolicy", POLICIES)


class TestEmailPolicyChange(unittest.TestCase):
    def setUp(self):
        self.change = _load("email_policy").kc_email_policy_change

    def test_an_agreeing_realm_is_kept(self):
        for policy in POLICIES:
            for switch in (False, True):
                with self.subTest(policy=policy, switch=switch):
                    self.assertEqual(self.change(policy, policy, switch), "keep")

    def test_a_deploy_never_switches_an_external_realm_on_its_own(self):
        with self.assertRaises(AnsibleFilterError) as ctx:
            self.change("external", "mailbox", False)
        self.assertIn("services.keycloak.email.switch", str(ctx.exception))

    def test_a_confirmed_switch_moves_an_external_realm_to_mailbox(self):
        self.assertEqual(self.change("external", "mailbox", True), "switch")

    def test_a_mailbox_realm_never_returns_to_external(self):
        for switch in (False, True):
            with self.subTest(switch=switch), self.assertRaises(AnsibleFilterError):
                self.change("mailbox", "external", switch)


class TestEmailSources(unittest.TestCase):
    def setUp(self):
        self.sources = _load("email_policy").kc_email_sources

    def test_the_address_keycloak_holds_wins_over_the_inventory(self):
        self.assertEqual(
            self.sources(
                {"biber": "confirmed@example.net", "mapache": ""},
                {"biber": "inventory@example.net", "mapache": "m@example.net", "x": ""},
            ),
            {"biber": "confirmed@example.net", "mapache": "m@example.net"},
        )


class TestProtocolMappers(unittest.TestCase):
    def setUp(self):
        self.m = _load("protocol_mappers")
        self.desired = [
            {
                "name": "email",
                "protocolMapper": "oidc-usermodel-attribute-mapper",
                "config": {"user.attribute": "mailbox", "claim.name": "email"},
            },
            {
                "name": "email verified",
                "protocolMapper": "oidc-hardcoded-claim-mapper",
                "config": {"claim.value": "true"},
            },
            {"name": "new", "protocolMapper": "x", "config": {}},
        ]

    def test_type_and_config_drift_are_found_and_extra_keys_ignored(self):
        current = [
            {
                "id": "1",
                "name": "email",
                "protocolMapper": "oidc-usermodel-attribute-mapper",
                "config": {"user.attribute": "email", "claim.name": "email"},
            },
            {
                "id": "2",
                "name": "email verified",
                "protocolMapper": "oidc-usermodel-property-mapper",
                "config": {"claim.value": "true"},
            },
            {"id": "3", "name": "foreign", "protocolMapper": "y", "config": {}},
        ]
        drifted = self.m.kc_drifted_protocol_mappers(current, self.desired)
        self.assertEqual([m["id"] for m in drifted], ["1", "2"])
        missing = self.m.kc_missing_protocol_mappers(self.desired, current, drifted)
        self.assertEqual(
            [m["name"] for m in missing], ["email", "email verified", "new"]
        )

    def test_converged_mappers_are_left_alone(self):
        current = [
            {**mapper, "id": str(index), "config": {**mapper["config"], "extra": "1"}}
            for index, mapper in enumerate(self.desired)
        ]
        drifted = self.m.kc_drifted_protocol_mappers(current, self.desired)
        self.assertEqual(drifted, [])
        self.assertEqual(
            self.m.kc_missing_protocol_mappers(self.desired, current, drifted), []
        )


class TestRequiredActions(unittest.TestCase):
    def setUp(self):
        self.drifted = _load("required_actions").kc_drifted_required_actions
        self.desired = [
            {
                "alias": "UPDATE_EMAIL",
                "name": "Update Email",
                "providerId": "UPDATE_EMAIL",
                "enabled": True,
                "defaultAction": False,
                "priority": 45,
                "config": {"verifyEmail": "true"},
            }
        ]

    def test_an_absent_or_drifted_action_is_converged(self):
        live = {**self.desired[0], "config": {}}
        for current in ([], [{**live, "enabled": False}], [live]):
            with self.subTest(current=current):
                self.assertEqual(self.drifted(self.desired, current), self.desired)

    def test_a_converged_action_is_left_alone(self):
        self.assertEqual(self.drifted(self.desired, list(self.desired)), [])


if __name__ == "__main__":
    unittest.main()
