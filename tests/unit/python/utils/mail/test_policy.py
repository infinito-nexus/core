import unittest
import unittest.mock as mock

from utils.cache.yaml import load_yaml_any
from utils.mail import policy
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLES = PROJECT_ROOT / "roles"
SERVICES = ROLES / "web-app-keycloak" / ROLE_FILE_META_SERVICES


def _variables(*deployed):
    return {"groups": {role: ["host"] for role in deployed}}


def _overrides(value):
    return {
        "web-app-keycloak": {"services": {"keycloak": {"email": {"policy": value}}}}
    }


class TestDefaultPolicy(unittest.TestCase):
    def test_a_deployed_mail_provider_directory_and_keycloak_record_mailboxes(self):
        self.assertEqual(
            policy.default_policy(
                _variables("web-app-stalwart", "svc-db-openldap", "web-app-keycloak"),
                ROLES,
            ),
            "mailbox",
        )

    def test_without_keycloak_addresses_stay_external(self):
        self.assertEqual(
            policy.default_policy(
                _variables("web-app-stalwart", "svc-db-openldap"), ROLES
            ),
            "external",
        )

    def test_without_the_directory_addresses_stay_external(self):
        self.assertEqual(
            policy.default_policy(
                _variables("web-app-stalwart", "web-app-keycloak"), ROLES
            ),
            "external",
        )

    def test_no_inventory_hosts_means_external_addresses(self):
        self.assertEqual(policy.default_policy({}, ROLES), "external")

    def test_a_provider_on_any_host_of_the_cluster_counts(self):
        variables = {
            **_variables("web-app-mailu", "web-app-keycloak", "svc-db-openldap"),
            "MAIL_PROVIDER": "web-app-mailu",
            "group_names": ["web-app-keycloak"],
        }
        self.assertEqual(policy.default_policy(variables, ROLES), "mailbox")

    def test_without_the_provider_addresses_stay_external(self):
        with mock.patch(
            "utils.mail.provider.provider_roles", return_value=["web-app-stalwart"]
        ):
            self.assertEqual(
                policy.default_policy(
                    _variables("web-app-keycloak", "svc-db-openldap"), ROLES
                ),
                "external",
            )


class TestResolvePolicy(unittest.TestCase):
    def test_the_inventory_value_wins(self):
        self.assertEqual(policy.resolve_policy(_overrides(" mailbox ")), "mailbox")

    def test_without_inventory_value_addresses_stay_external(self):
        for overrides in ({}, {"web-app-keycloak": {"services": {"keycloak": {}}}}):
            with self.subTest(overrides=overrides):
                self.assertEqual(policy.resolve_policy(overrides), "external")

    def test_the_fallback_equals_the_role_default(self):
        services = load_yaml_any(str(SERVICES))
        self.assertEqual(
            services["keycloak"]["email"]["policy"], policy.resolve_policy({})
        )

    def test_an_unknown_or_templated_value_fails_loudly(self):
        for value in ("both", "{{ 'mailbox' }}"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy.resolve_policy(_overrides(value))


if __name__ == "__main__":
    unittest.main()
