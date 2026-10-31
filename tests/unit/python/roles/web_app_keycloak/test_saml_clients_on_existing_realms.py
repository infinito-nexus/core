import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2 import Environment

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-keycloak"
VARS = ROLE / ROLE_FILE_VARS_MAIN

SMTP = {"host": "mail.example", "password": "pw"}
REALM = {
    "clients": [
        {"clientId": "account", "protocol": "openid-connect"},
        {"clientId": "cymais.cloud", "protocol": "openid-connect"},
        {"clientId": "stalwart-webui", "protocol": "openid-connect"},
        {"clientId": "https://crm.example/saml/metadata", "protocol": "saml"},
    ],
    "clientScopes": [{"name": "rbac"}],
    "smtpServer": SMTP,
}


def render(name: str, declared_client_ids: list[str]):
    """Resolve one variable of the role's ``vars/main.yml`` against ``REALM``.

    Args:
        name: the variable.
        declared_client_ids: ``KEYCLOAK_DECLARED_CLIENT_IDS``.
    """
    declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
    inputs = {
        "KEYCLOAK_DICTIONARY_REALM": REALM,
        "KEYCLOAK_CLIENT_ID": "cymais.cloud",
        "KEYCLOAK_DECLARED_CLIENT_IDS": declared_client_ids,
        "KEYCLOAK_REALM": "cymais",
    }
    templar = Templar(loader=DataLoader(), variables={**declared, **inputs})
    return templar.template(declared[name])


class TestSamlClientsReachExistingRealms(unittest.TestCase):
    def test_only_saml_clients_of_the_realm_dictionary_are_selected(self):
        template = load_yaml_any(str(VARS))["KEYCLOAK_SAML_CLIENT_IDS"]
        expression = template.strip().removeprefix("{{").removesuffix("}}")
        selected = Environment(autoescape=True).compile_expression(expression)(
            KEYCLOAK_DICTIONARY_REALM=REALM
        )
        self.assertEqual(selected, ["https://crm.example/saml/metadata"])

    def test_the_existing_realm_reconcile_covers_saml_clients(self):
        clients = render("KEYCLOAK_SETTINGS_SPEC", [])["clients"]
        self.assertIn(
            "https://crm.example/saml/metadata", [c["clientId"] for c in clients]
        )


class TestSettingsSpec(unittest.TestCase):
    def test_main_declared_and_saml_clients_are_converged_built_ins_are_not(self):
        clients = render("KEYCLOAK_SETTINGS_SPEC", ["stalwart-webui"])["clients"]
        self.assertEqual(
            [c["clientId"] for c in clients],
            ["cymais.cloud", "stalwart-webui", "https://crm.example/saml/metadata"],
        )

    def test_both_realms_get_the_mail_settings_of_the_realm_dictionary(self):
        realms = render("KEYCLOAK_SETTINGS_SPEC", [])["realms"]
        self.assertEqual(
            realms,
            [
                {"realm": "cymais", "desired": {"smtpServer": SMTP}},
                {"realm": "master", "desired": {"smtpServer": SMTP}},
            ],
        )

    def test_the_client_scopes_of_the_realm_dictionary_are_passed_on(self):
        spec = render("KEYCLOAK_SETTINGS_SPEC", [])
        self.assertEqual(spec["clientScopes"], [{"name": "rbac"}])

    def test_a_declared_client_the_dictionary_lacks_is_reported_missing(self):
        missing = render("KEYCLOAK_SETTINGS_MISSING_CLIENT_IDS", ["ghost", "account"])
        self.assertEqual(missing, ["ghost"])

    def test_nothing_is_missing_when_every_client_is_declared_in_the_dictionary(self):
        self.assertEqual(
            render("KEYCLOAK_SETTINGS_MISSING_CLIENT_IDS", ["stalwart-webui"]), []
        )


if __name__ == "__main__":
    unittest.main()
