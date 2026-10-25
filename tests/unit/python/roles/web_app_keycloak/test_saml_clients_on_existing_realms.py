import unittest

from jinja2 import Environment

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-keycloak"
VARS = ROLE / ROLE_FILE_VARS_MAIN
ROUTINES = ROLE / "tasks" / "03_manager_ops" / "update_routines.yml"

REALM = {
    "clients": [
        {"clientId": "account", "protocol": "openid-connect"},
        {"clientId": "cymais.cloud", "protocol": "openid-connect"},
        {"clientId": "https://crm.example/saml/metadata", "protocol": "saml"},
    ]
}


class TestSamlClientsReachExistingRealms(unittest.TestCase):
    def test_only_saml_clients_of_the_realm_dictionary_are_selected(self):
        template = load_yaml_any(str(VARS))["KEYCLOAK_SAML_CLIENT_IDS"]
        expression = template.strip().removeprefix("{{").removesuffix("}}")
        selected = Environment(autoescape=True).compile_expression(expression)(
            KEYCLOAK_DICTIONARY_REALM=REALM
        )
        self.assertEqual(selected, ["https://crm.example/saml/metadata"])

    def test_the_existing_realm_reconcile_loops_over_saml_clients(self):
        task = next(
            t
            for t in load_yaml_any(str(ROUTINES))
            if "10_declared_client.yml" in str(t.get("include_tasks", ""))
        )
        self.assertIn("KEYCLOAK_SAML_CLIENT_IDS", task["loop"])


if __name__ == "__main__":
    unittest.main()
