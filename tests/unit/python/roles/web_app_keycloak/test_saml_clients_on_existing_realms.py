import json
import unittest
import unittest.mock as mock

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2 import Environment

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-keycloak"
VARS = ROLE / ROLE_FILE_VARS_MAIN

SMTP = {"host": "mail.example", "password": "pw"}
OTP_POLICY = {
    "otpPolicyType": "hotp",
    "otpPolicyAlgorithm": "HmacSHA256",
    "otpPolicyInitialCounter": 2,
    "otpPolicyDigits": 8,
    "otpPolicyLookAheadWindow": 3,
    "otpPolicyPeriod": 60,
    "otpPolicyCodeReusable": True,
}
REALM = {
    "clients": [
        {"clientId": "account", "protocol": "openid-connect"},
        {"clientId": "cymais.cloud", "protocol": "openid-connect"},
        {"clientId": "stalwart-webui", "protocol": "openid-connect"},
        {"clientId": "https://crm.example/saml/metadata", "protocol": "saml"},
    ],
    "clientScopes": [{"name": "rbac"}],
    "smtpServer": SMTP,
    "verifyEmail": True,
    "loginWithEmailAllowed": True,
    "duplicateEmailsAllowed": False,
    "adminEventsEnabled": True,
    "adminPermissionsEnabled": True,
    "organizationsEnabled": False,
    "accessTokenLifespan": 600,
    "attributes": {"adminEventsExpiration": "31536000", "frontendUrl": ""},
    **OTP_POLICY,
}
WORKSPACE_CLIENTS = [
    {"clientId": "workspaces", "protocol": "openid-connect"},
    {"clientId": "workspace-members", "protocol": "openid-connect"},
]


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
        "KEYCLOAK_PROXY_CLIENTS": [],
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


class TestDeclaredClientMappersReachExistingRealms(unittest.TestCase):
    def test_only_declared_clients_with_mappers_are_selected(self):
        mapper = {
            "name": "roles",
            "protocolMapper": "oidc-usermodel-client-role-mapper",
        }
        realm = {
            **REALM,
            "clients": [
                {"clientId": "account", "protocolMappers": [mapper]},
                {"clientId": "stalwart-webui"},
                {"clientId": "nextcloud-user-oidc", "protocolMappers": [mapper]},
            ],
        }
        with mock.patch.dict(globals(), {"REALM": realm}):
            selected = render(
                "KEYCLOAK_DECLARED_MAPPER_CLIENT_IDS",
                ["stalwart-webui", "nextcloud-user-oidc"],
            )
        self.assertEqual(["nextcloud-user-oidc"], selected)

    def test_no_declared_client_selects_nothing(self):
        self.assertEqual([], render("KEYCLOAK_DECLARED_MAPPER_CLIENT_IDS", []))


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
                {
                    "realm": "cymais",
                    "desired": {
                        "smtpServer": SMTP,
                        "verifyEmail": True,
                        "loginWithEmailAllowed": True,
                        "duplicateEmailsAllowed": False,
                        "adminEventsEnabled": True,
                        "adminPermissionsEnabled": True,
                        "organizationsEnabled": False,
                        "accessTokenLifespan": 600,
                        "attributes": {"adminEventsExpiration": "31536000"},
                        **OTP_POLICY,
                    },
                },
                {"realm": "master", "desired": {"smtpServer": SMTP}},
            ],
        )

    def test_an_existing_realm_converges_to_the_verify_email_flag_of_the_dictionary(
        self,
    ):
        for flag in (True, False):
            with self.subTest(verify_email=flag):
                realm = {**REALM, "verifyEmail": flag}
                with mock.patch.dict(globals(), {"REALM": realm}):
                    desired = render("KEYCLOAK_SETTINGS_SPEC", [])["realms"][0][
                        "desired"
                    ]
                self.assertIs(desired["verifyEmail"], flag)

    def test_an_existing_realm_converges_to_the_organizations_flag_of_the_dictionary(
        self,
    ):
        for flag in (True, False):
            with self.subTest(organizations=flag):
                realm = {**REALM, "organizationsEnabled": flag}
                with mock.patch.dict(globals(), {"REALM": realm}):
                    desired = render("KEYCLOAK_SETTINGS_SPEC", [])["realms"][0][
                        "desired"
                    ]
                self.assertIs(desired["organizationsEnabled"], flag)

    def test_the_workspace_clients_of_the_dictionary_are_converged(self):
        realm = {**REALM, "clients": REALM["clients"] + WORKSPACE_CLIENTS}
        with mock.patch.dict(globals(), {"REALM": realm}):
            clients = render("KEYCLOAK_SETTINGS_SPEC", [])["clients"]
        self.assertEqual(
            [c["clientId"] for c in clients],
            [
                "cymais.cloud",
                "https://crm.example/saml/metadata",
                "workspaces",
                "workspace-members",
            ],
        )

    def test_without_workspace_clients_in_the_dictionary_none_is_converged(self):
        ids = render("KEYCLOAK_SETTINGS_CLIENT_IDS", [])
        self.assertEqual(ids, ["cymais.cloud", "https://crm.example/saml/metadata"])

    def test_the_master_realm_gets_no_verify_email_flag(self):
        master = render("KEYCLOAK_SETTINGS_SPEC", [])["realms"][1]["desired"]
        self.assertNotIn("verifyEmail", master)

    def test_an_existing_realm_turns_on_admin_events_and_admin_permissions(self):
        desired = render("KEYCLOAK_SETTINGS_SPEC", [])["realms"][0]["desired"]
        self.assertIs(desired["adminEventsEnabled"], True)
        self.assertIs(desired["adminPermissionsEnabled"], True)

    def test_an_existing_realm_converges_only_the_admin_events_expiration(self):
        desired = render("KEYCLOAK_SETTINGS_SPEC", [])["realms"][0]["desired"]
        self.assertEqual({"adminEventsExpiration": "31536000"}, desired["attributes"])

    def test_an_existing_realm_converges_to_the_otp_policy_of_the_dictionary(self):
        desired = render("KEYCLOAK_SETTINGS_SPEC", [])["realms"][0]["desired"]
        for field, value in OTP_POLICY.items():
            with self.subTest(field=field):
                self.assertEqual(json.dumps(value), json.dumps(desired[field]))

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
