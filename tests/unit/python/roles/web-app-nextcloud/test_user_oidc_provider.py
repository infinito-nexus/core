"""The user_oidc provider registration of web-app-nextcloud.

The registration renders through the role's real ``vars/main.yml`` and the
real ``config`` lookup, with the plugin override in ``applications`` the way an
inventory or a variant sets it.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import unittest
from typing import Any

from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.reset import _reset_cache_for_tests
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = "web-app-nextcloud"
ROLE_DIR = PROJECT_ROOT / "roles" / ROLE
SSO = ("web-app-keycloak", "svc-db-openldap")
NEXTCLOUD_UID = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/11_oidc.yml"))[
    "defaults_oidc"
]["ATTRIBUTES"]["NEXTCLOUD_UID"]
OIDC = {
    "CLIENT": {
        "SECRET": "shared-secret",
        "DISCOVERY_DOCUMENT": "https://auth.example.com/realms/example.com/.well-known/openid-configuration",
        "LOGOUT_URL": "https://auth.example.com/realms/example.com/protocol/openid-connect/logout",
    },
    "ATTRIBUTES": {
        "USERNAME": "preferred_username",
        "NAME": "name",
        "EMAIL": "email",
        "NEXTCLOUD_UID": NEXTCLOUD_UID,
    },
}
RBAC = {"GROUP": {"CLAIM": "groups"}}
LDAP = {"USER": {"ATTRIBUTES": {"NEXTCLOUD_QUOTA": "nextcloudQuota"}}}
NEXTCLOUD_URL = "https://next.cloud.example.com"
NO_GROUPS_CLAIM = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SERVICES))["sso"]["oidc"][
    "no_groups_claim"
]
ADMIN_GROUP_PATH = "/roles/web-app-nextcloud/administrator"
HARDCODED_CLAIM_MAPPER = "oidc-hardcoded-claim-mapper"


def setUpModule() -> None:
    _reset_cache_for_tests()


def tearDownModule() -> None:
    _reset_cache_for_tests()


def renderer(plugin: str):
    """A renderer of the role's variable scope with SSO deployed.

    Args:
        plugin: the inventory override of ``services.sso.oidc.plugin``.

    Returns:
        A callable that renders one Jinja text in that scope.
    """
    loader = DataLoader()
    variables = {
        **loader.load_from_file(
            str(ROLE_DIR / ROLE_FILE_VARS_MAIN), trusted_as_template=True
        ),
        "group_names": sorted({ROLE, *SSO}),
        "applications": {ROLE: {"services": {"sso": {"oidc": {"plugin": plugin}}}}},
        "OIDC": OIDC,
        "RBAC": RBAC,
        "LDAP": LDAP,
        "NEXTCLOUD_URL": NEXTCLOUD_URL,
        "NEXTCLOUD_LOCAL_CID": "nextcloud",
    }
    templar = Templar(loader=loader, variables=variables)
    return lambda template: templar.template(trust_as_template(template))


def render(template: str, plugin: str) -> Any:
    return renderer(plugin)(template)


def secret_on_argv(command: str, secret: str) -> bool:
    """Whether a rendered command line carries *secret* where ``ps`` shows it.

    Args:
        command: the rendered shell command.
        secret: the client secret.
    """
    return secret in command


REGISTRATION = (
    "{{ {'options': NEXTCLOUD_USER_OIDC_OPTIONS,"
    " 'provider': NEXTCLOUD_USER_OIDC_PROVIDER,"
    " 'scope': lookup('config', 'web-app-keycloak', 'services.keycloak.scopes.nextcloud')} }}"
)


def provisioned_group_id(claim_value: str, options: list[str]) -> str | None:
    """The Nextcloud group id user_oidc v8.12.0 provisions for one groups claim value.

    Mirrors ``ProvisioningService::getSyncGroupsOfToken``: a plain string is
    the group id (lib/Service/ProvisioningService.php:703), the whitelist
    regex drops a value it does not match (:709-719), and
    ``LocalIdService::getId`` hashes the id while the provider's unique uid is
    on, its default, or prefixes it with the provider identifier
    (lib/Service/LocalIdService.php:20-40).

    Args:
        claim_value: one value of the groups claim.
        options: the ``occ user_oidc:provider`` options.
    """
    settings = dict(option.removeprefix("--").split("=", 1) for option in options)
    whitelist = settings.get("group-whitelist-regex", "")
    if whitelist and not re.search(whitelist, claim_value):
        return None
    if settings.get("unique-uid", "1") == "1":
        return hashlib.sha256(f"1_0_{claim_value}".encode()).hexdigest()
    if settings.get("provider-based-id", "0") == "1":
        return f"keycloak-{claim_value}"
    return claim_value


def own_client() -> dict:
    """
    Returns:
        The own Keycloak client of user_oidc, rendered the way the realm includes it.
    """
    fragments = importlib.import_module(
        "tests.unit.python.roles.web-app-keycloak.templates.test_backchannel_clients"
    )
    (client,) = fragments.render_fragment(
        ROLE_DIR / "templates/keycloak/clients.json.j2"
    )
    return client


def id_token(held: list[str], client: dict) -> dict:
    """
    Args:
        held: the group paths and client roles the account holds.
        client: the rendered client representation.

    Returns:
        The decoded ID token payload Keycloak sends, reduced to the
        claims user_oidc maps groups from: no group claim for an empty list,
        a JSON hardcoded claim parsed as written.
    """
    payload: dict[str, Any] = {}
    if held:
        payload[RBAC["GROUP"]["CLAIM"]] = list(held)
    for mapper in client["protocolMappers"]:
        config = mapper["config"]
        if mapper["protocolMapper"] != HARDCODED_CLAIM_MAPPER:
            continue
        if config.get("id.token.claim") != "true":
            continue
        value = config["claim.value"]
        if config.get("jsonType.label") == "JSON":
            value = json.loads(value)
        payload[config["claim.name"]] = value
    return payload


def synced_groups(payload: dict, options: list[str]) -> list[str] | None:
    """
    Args:
        payload: the decoded ID token.
        options: the ``occ user_oidc:provider`` options.

    Returns:
        The complete group set user_oidc provisions, the first present
        ``|`` alternative while nested claims are on, or None when user_oidc
        changes no group.
    """
    settings = dict(option.removeprefix("--").split("=", 1) for option in options)
    mapping = settings["mapping-groups"]
    alternatives = (
        mapping.split("|")
        if settings.get("resolve-nested-claims") == "1"
        else [mapping]
    )
    value = next(
        (payload[name.strip()] for name in alternatives if name.strip() in payload),
        None,
    )
    if value is None:
        return None
    return [
        group
        for group in (provisioned_group_id(item, options) for item in value)
        if group is not None
    ]


def registration_block() -> dict:
    (block,) = load_yaml_str(read_text(str(ROLE_DIR / "tasks/addons/user_oidc.yml")))
    return block


class TestUserOidcProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        user_oidc = renderer("user_oidc")
        registration = user_oidc(REGISTRATION)
        cls.options = list(registration["options"])
        cls.provider = registration["provider"]
        cls.app_scope = registration["scope"]
        shell = cls._upsert()["ansible.builtin.shell"]
        cls.command = user_oidc(shell["cmd"])
        cls.stdin = user_oidc(shell["stdin"])

    @staticmethod
    def _upsert() -> dict:
        return next(
            task
            for task in registration_block()["block"]
            if "ansible.builtin.shell" in task
        )

    def test_the_provider_is_registered_with_the_own_client(self) -> None:
        self.assertIn("--clientid=nextcloud-user-oidc", self.options)
        self.assertIn(
            f"--discoveryuri={OIDC['CLIENT']['DISCOVERY_DOCUMENT']}", self.options
        )
        self.assertIn(
            "--clientsecret-env=NC_USER_OIDC_CLIENT_SECRET", self.command.split()
        )
        self.assertIn("-e NC_USER_OIDC_CLIENT_SECRET", self.command)

    def test_the_client_secret_travels_on_stdin_and_never_on_argv(self) -> None:
        secret = OIDC["CLIENT"]["SECRET"]
        self.assertFalse(secret_on_argv(self.command, secret))
        self.assertEqual(secret, self.stdin)
        self.assertFalse(any(o.startswith("--clientsecret=") for o in self.options))

    def test_a_secret_option_on_the_command_line_is_caught(self) -> None:
        secret = OIDC["CLIENT"]["SECRET"]
        self.assertTrue(
            secret_on_argv(f"{self.command} --clientsecret={secret}", secret)
        )

    def test_an_existing_account_keeps_its_user_id(self) -> None:
        self.assertIn(f"--mapping-uid={NEXTCLOUD_UID}|preferred_username", self.options)
        self.assertIn("--resolve-nested-claims=1", self.options)
        self.assertIn("--unique-uid=0", self.options)

    def test_the_own_client_hands_user_oidc_the_mapped_user_id(self) -> None:
        (mapper,) = [
            m for m in own_client()["protocolMappers"] if m["name"] == "nextcloud uid"
        ]
        self.assertEqual("oidc-usermodel-attribute-mapper", mapper["protocolMapper"])
        expected = {
            "user.attribute": NEXTCLOUD_UID,
            "claim.name": NEXTCLOUD_UID,
            "multivalued": "false",
            "id.token.claim": "true",
            "access.token.claim": "true",
            "userinfo.token.claim": "true",
        }
        self.assertEqual(expected, {key: mapper["config"].get(key) for key in expected})

    def test_profile_quota_and_groups_come_from_the_claims(self) -> None:
        for option in (
            "--mapping-display-name=name",
            "--mapping-email=email",
            "--mapping-quota=nextcloudQuota",
            f"--mapping-groups=groups|{NO_GROUPS_CLAIM}",
            "--group-provisioning=1",
        ):
            with self.subTest(option=option):
                self.assertIn(option, self.options)
        scope = next(o for o in self.options if o.startswith("--scope=")).split()
        self.assertIn("groups", scope)
        self.assertIn(self.app_scope, scope)

    def test_the_admin_client_role_provisions_nextcloud_s_admin_group(self) -> None:
        roles = render(
            "{{ lookup('config', application_id, 'services.sso.oidc.client_roles') }}",
            "user_oidc",
        )
        self.assertEqual({"user_oidc": {"admin": "administrator"}}, roles)
        (role,) = roles["user_oidc"]
        self.assertEqual("admin", provisioned_group_id(role, self.options))
        self.assertEqual(
            "/roles/web-app-nextcloud/administrator",
            provisioned_group_id(
                "/roles/web-app-nextcloud/administrator", self.options
            ),
        )

    def test_a_hashed_or_filtered_group_id_misses_the_admin_group(self) -> None:
        base = [o for o in self.options if not o.startswith("--unique-uid=")]
        for extra in (
            ["--unique-uid=1"],
            ["--unique-uid=0", "--provider-based-id=1"],
            ["--unique-uid=0", "--group-whitelist-regex=^/roles/"],
        ):
            with self.subTest(options=extra):
                self.assertNotEqual(
                    "admin", provisioned_group_id("admin", base + extra)
                )

    def test_the_own_client_always_sends_an_empty_group_list(self) -> None:
        fragments = importlib.import_module(
            "tests.unit.python.roles.web-app-keycloak.templates.test_backchannel_clients"
        )
        group_mapper = fragments.group_claim_mapper()
        (mapper,) = [
            m
            for m in own_client()["protocolMappers"]
            if m["protocolMapper"] == HARDCODED_CLAIM_MAPPER
        ]
        config = mapper["config"]
        self.assertEqual(NO_GROUPS_CLAIM, config["claim.name"])
        self.assertEqual([], json.loads(config["claim.value"]))
        self.assertEqual("JSON", config["jsonType.label"])
        for flag in fragments.TOKEN_FLAGS:
            with self.subTest(flag=flag):
                self.assertEqual(group_mapper["config"].get(flag), config.get(flag))

    def test_the_empty_group_list_never_shadows_the_groups_claim(self) -> None:
        self.assertNotEqual(RBAC["GROUP"]["CLAIM"], NO_GROUPS_CLAIM)
        for separator in (".", "|"):
            with self.subTest(separator=separator):
                self.assertNotIn(separator, NO_GROUPS_CLAIM)
        payload = id_token([ADMIN_GROUP_PATH, "admin"], own_client())
        self.assertEqual(
            [ADMIN_GROUP_PATH, "admin"], synced_groups(payload, self.options)
        )

    def test_an_account_that_loses_its_last_group_leaves_admin(self) -> None:
        payload = id_token([], own_client())
        self.assertNotIn(RBAC["GROUP"]["CLAIM"], payload)
        self.assertEqual([], synced_groups(payload, self.options))

    def test_without_the_fallback_a_revoked_administrator_keeps_admin(self) -> None:
        payload = id_token([], own_client())
        groups_only = [
            option
            for option in self.options
            if not option.startswith("--mapping-groups=")
        ] + [f"--mapping-groups={RBAC['GROUP']['CLAIM']}"]
        self.assertIsNone(synced_groups(payload, groups_only))
        without_nested = [
            option
            for option in self.options
            if not option.startswith("--resolve-nested-claims=")
        ] + ["--resolve-nested-claims=0"]
        self.assertIsNone(synced_groups(payload, without_nested))
        client = own_client()
        client["protocolMappers"] = [
            m
            for m in client["protocolMappers"]
            if m["protocolMapper"] != HARDCODED_CLAIM_MAPPER
        ]
        self.assertIsNone(synced_groups(id_token([], client), self.options))

    def test_the_provider_identifier_is_the_one_keycloak_logs_out_on(self) -> None:
        self.assertEqual("keycloak", self.provider)

    def test_another_plugin_declares_no_client_to_register_with(self) -> None:
        self.assertEqual(
            {},
            render(
                "{{ lookup('config', application_id, 'services.sso.oidc.clients') }}",
                "oidc_login",
            ),
        )
        with self.assertRaises(AnsibleError):
            render("{{ NEXTCLOUD_USER_OIDC_OPTIONS }}", "oidc_login")

    def test_the_rbac_hook_revokes_the_client_role_groups_only_under_user_oidc(
        self,
    ) -> None:
        template = "{{ NEXTCLOUD_USER_OIDC_GROUP_ROLES }}"
        self.assertEqual({"admin": "administrator"}, render(template, "user_oidc"))
        self.assertEqual({}, render(template, "oidc_login"))

    def test_the_client_and_the_provider_switch_on_the_same_plugin(self) -> None:
        clients = "{{ lookup('config', application_id, 'services.sso.oidc.clients') }}"
        enabled = load_yaml_any(str(ROLE_DIR / "meta/addons/user_oidc.yml"))["enabled"]
        for plugin, expected in (
            ("user_oidc", ({"user_oidc": "nextcloud-user-oidc"}, True)),
            ("oidc_login", ({}, False)),
        ):
            with self.subTest(plugin=plugin):
                scope = renderer(plugin)
                self.assertEqual(expected, (scope(clients), scope(enabled)))

    def test_the_registration_is_one_idempotent_upsert(self) -> None:
        block = registration_block()
        self.assertEqual("IS_STACK_HOST | bool", block["when"])
        lookup, upsert = block["block"]
        self.assertEqual(
            "{{ NEXTCLOUD_DOCKER_EXEC_OCC }} user_oidc:provider"
            " {{ NEXTCLOUD_USER_OIDC_PROVIDER | quote }}",
            lookup["ansible.builtin.command"]["cmd"],
        )
        self.assertIs(False, lookup["failed_when"])
        self.assertIn(
            "user_oidc:provider {{ NEXTCLOUD_USER_OIDC_PROVIDER | quote }}",
            upsert["ansible.builtin.shell"]["cmd"],
        )
        self.assertEqual("{{ MASK_CREDENTIALS_IN_LOGS | bool }}", upsert["no_log"])
        self.assertTrue(
            upsert["ansible.builtin.shell"]["cmd"].endswith(
                " >&2 && " + lookup["ansible.builtin.command"]["cmd"]
            )
        )
        self.assertEqual(
            "nextcloud_user_oidc_provider_state.rc != 0"
            " or nextcloud_user_oidc_provider.stdout"
            " != nextcloud_user_oidc_provider_state.stdout",
            upsert["changed_when"],
        )


if __name__ == "__main__":
    unittest.main()
