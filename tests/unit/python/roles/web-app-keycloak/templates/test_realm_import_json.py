from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
import unittest
import unittest.mock as mock

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.account_policy import (
    account_max_length,
    load_policies,
    username_patterns,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles/web-app-keycloak"
IMPORT_DIR = ROLE_DIR / "templates/import"
ORGANIZATIONS_SPEC = ROLE_DIR / "files/playwright/test-organizations.js"
ROLE_VARS = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
ROLE_SERVICES = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SERVICES))
ADMIN_EVENTS_DAYS = ROLE_SERVICES["keycloak"]["events"]["admin"]["expiration_days"]
REALM_VARIABLES = (
    "KEYCLOAK_REALM_ACCESS_TOKEN_LIFESPAN",
    "KEYCLOAK_REALM_TOTP_ENABLED",
    "KEYCLOAK_REALM_TOTP_ENFORCED",
    "KEYCLOAK_REALM_OTP_POLICY_TYPE",
    "KEYCLOAK_REALM_OTP_POLICY_ALGORITHM",
    "KEYCLOAK_REALM_OTP_POLICY_DIGITS",
    "KEYCLOAK_REALM_OTP_POLICY_PERIOD",
    "KEYCLOAK_REALM_OTP_POLICY_LOOK_AHEAD_WINDOW",
    "KEYCLOAK_REALM_OTP_POLICY_INITIAL_COUNTER",
    "KEYCLOAK_REALM_OTP_POLICY_CODE_REUSABLE",
)


def realm_context(realm_overrides: dict | None = None) -> dict:
    """Resolve the role's realm variables through ``vars/main.yml`` from ``meta/services.yml``.

    Args:
        realm_overrides: values replacing those below ``services.keycloak.realm``,
            keyed by their dotted path below it.
    """
    services = copy.deepcopy(ROLE_SERVICES)
    for path, value in (realm_overrides or {}).items():
        *parents, leaf = path.split(".")
        target = services["keycloak"]["realm"]
        for parent in parents:
            target = target[parent]
        target[leaf] = value

    def lookup(name, _application_id, path):
        assert name == "config", name
        value = {"services": services}
        for part in path.split("."):
            value = value[part]
        return value

    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
    env.filters["bool"] = bool
    return {
        name: env.compile_expression(
            ROLE_VARS[name].strip().removeprefix("{{").removesuffix("}}")
        )(lookup=lookup, application_id="web-app-keycloak")
        for name in REALM_VARIABLES
    }


LDAP_VARS = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/12_ldap.yml"))
OIDC_VARS = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/11_oidc.yml"))
LDAP_USER_ATTRIBUTES = {
    **LDAP_VARS["LDAP"]["USER"]["ATTRIBUTES"],
    "ID": "uid",
}


def profile_attributes() -> list[dict]:
    """Render the role's profile registry against the directory attribute names."""
    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
    ldap = {"USER": {"ATTRIBUTES": LDAP_USER_ATTRIBUTES}}
    return [
        {**entry, "ldap": env.from_string(entry["ldap"]).render(LDAP=ldap)}
        for entry in ROLE_VARS["KEYCLOAK_PROFILE_ATTRIBUTES"]
    ]


def role_filters() -> dict:
    """Load the role's own Jinja filters the realm import relies on."""
    spec = importlib.util.spec_from_file_location(
        "keycloak_ldap_filters", ROLE_DIR / "filter_plugins/ldap_filters.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FilterModule().filters()


def secondary_pattern(domain: str) -> str:
    """Render the role's secondary address pattern for a mailbox domain."""
    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
    env.filters["regex_escape"] = re.escape
    return env.from_string(ROLE_VARS["KEYCLOAK_EMAIL_SECONDARY_PATTERN"]).render(
        KEYCLOAK_EMAIL_DOMAIN=domain
    )


def usage_context() -> dict:
    """Resolve the usage client's names through ``vars/main.yml``, switch off."""
    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
    client_id = ROLE_VARS["KEYCLOAK_USAGE_CLIENT_ID"]
    return {
        "KEYCLOAK_USAGE_CLIENT_ENABLED": False,
        "KEYCLOAK_USAGE_CLIENT_ID": client_id,
        "KEYCLOAK_USAGE_CLIENT_SECRET": "d" * 64,
        "KEYCLOAK_USAGE_CLIENT_ROLES": ROLE_VARS["KEYCLOAK_USAGE_CLIENT_ROLES"],
        "KEYCLOAK_USAGE_SERVICE_ACCOUNT": env.from_string(
            ROLE_VARS["KEYCLOAK_USAGE_SERVICE_ACCOUNT"]
        ).render(KEYCLOAK_USAGE_CLIENT_ID=client_id),
        "KEYCLOAK_CONSOLE_ROLE_CLIENT": ROLE_VARS["KEYCLOAK_CONSOLE_ROLE_CLIENT"],
    }


ORGANIZATION_VARIABLES = (
    "KEYCLOAK_ORGANIZATIONS_ENABLED",
    "KEYCLOAK_ORGANIZATION_EXECUTION",
    "KEYCLOAK_WORKSPACES_CLIENT_ID",
    "KEYCLOAK_WORKSPACE_ROLES_SCOPE",
    "KEYCLOAK_WORKSPACE_ROLES_CLAIM",
    "KEYCLOAK_WORKSPACE_MEMBERS_CLIENT_ID",
    "KEYCLOAK_WORKSPACE_MEMBERS_CLIENT_SECRET",
    "KEYCLOAK_WORKSPACE_MEMBERS_CLIENT_ROLES",
    "KEYCLOAK_WORKSPACE_MEMBERS_SERVICE_ACCOUNT",
    "KEYCLOAK_EXPORT_CLIENT_ID",
    "KEYCLOAK_EXPORT_CLIENT_SECRET",
    "KEYCLOAK_EXPORT_CLIENT_ROLES",
    "KEYCLOAK_EXPORT_SERVICE_ACCOUNT",
    "KEYCLOAK_EXPORT_RECIPIENT_ATTRIBUTE",
    "KEYCLOAK_EXPORT_RECIPIENT_PATTERN",
    "KEYCLOAK_STORE_FIXTURE_CLIENT_ID",
    "KEYCLOAK_STORE_FIXTURE_CLIENT_SECRET",
    "KEYCLOAK_STORE_FIXTURE_ENABLED",
)
MEMBERS_CLIENT_SECRET = "e" * 64
EXPORT_CLIENT_SECRET = "f" * 64
STORE_FIXTURE_CLIENT_SECRET = "a" * 64


def organizations_context(enabled: bool, invite_client_id: str | None = None) -> dict:
    """
    Args:
        enabled: value of ``services.keycloak.organizations.enabled``.
        invite_client_id: value of ``services.semaphore.workspaces.invite_client_id``
            of ``web-app-semaphore``.

    Returns:
        The organization variables of ``vars/main.yml``, resolved.
    """
    config = {
        "services": {
            "keycloak": {"organizations": {"enabled": enabled}},
            "semaphore": {"workspaces": {"invite_client_id": invite_client_id}},
        },
        "secrets": {
            "credentials": {
                "workspace_members_client_secret": MEMBERS_CLIENT_SECRET,
                "export_client_secret": EXPORT_CLIENT_SECRET,
                "store_fixture_client_secret": STORE_FIXTURE_CLIENT_SECRET,
            }
        },
    }

    def lookup(name, _application_id, path):
        assert name == "config", name
        value = config
        for part in path.split("."):
            value = value[part]
        return value

    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
    env.filters["bool"] = bool
    resolved: dict = {}
    for name in ORGANIZATION_VARIABLES:
        value = ROLE_VARS[name]
        scope = {"lookup": lookup, "application_id": "web-app-keycloak", **resolved}
        if isinstance(value, str) and re.fullmatch(r"\{\{[^{}]*\}\}", value.strip()):
            expression = value.strip().removeprefix("{{").removesuffix("}}")
            value = env.compile_expression(expression)(**scope)
        elif isinstance(value, str):
            value = env.from_string(value).render(**scope)
        resolved[name] = value
    return resolved


APP_URL = "https://suite.crm.example.com"
ONION_URL = "http://suite.crm." + "a" * 56 + ".onion"

CONTEXT = {
    "KEYCLOAK_REALM": "example.com",
    "KEYCLOAK_REALM_URL": "https://auth.example.com/realms/example.com",
    "KEYCLOAK_CLIENT_ID": "example.com",
    "KEYCLOAK_REDIRECT_URIS": ["https://suite.crm.example.com/*"],
    "KEYCLOAK_WEB_ORIGINS": ["https://suite.crm.example.com"],
    "KEYCLOAK_POST_LOGOUT_URIS": "+",
    "KEYCLOAK_FRONTCHANNEL_LOGOUT_URL": "https://logout.example.com",
    "KEYCLOAK_RBAC_GROUP_CLAIM": "groups",
    "KEYCLOAK_RECAPTCHA_KEY": "",
    "KEYCLOAK_RECAPTCHA_SECRET": "",
    "KEYCLOAK_RECAPTCHA_ENABLED": False,
    **realm_context({"totp_enabled": False, "totp_enforced": False}),
    "KEYCLOAK_LDAP_ENABLED": True,
    "KEYCLOAK_MOODLE_ENABLED": True,
    "KEYCLOAK_RESERVED_USERNAMES_REGEX": "^(root|admin)$",
    "IAM_USERNAME_MAX_LENGTH": 15,
    "IAM_ACCOUNT_MAX_LENGTH": 20,
    "IAM_USERNAME_PATTERNS": ["[a-z0-9_]+", "[a-y0-9]+"],
    "KEYCLOAK_LDAP_USER_OBJECT_CLASSES": "inetOrgPerson, organizationalPerson",
    "KEYCLOAK_LDAP_CMP_NAME": "ldap",
    "KEYCLOAK_LDAP_URL": "ldap://openldap:389",
    "KEYCLOAK_LDAP_BIND_DN": "cn=admin,dc=example,dc=com",
    "KEYCLOAK_LDAP_BIND_PW": "secret",
    "KEYCLOAK_LDAP_CONNECTION_POOLING": "true",
    "KEYCLOAK_LDAP_SYNC_CHANGES_PERIOD": "86400",
    "KEYCLOAK_LDAP_SYNC_FULL_PERIOD": "604800",
    "KEYCLOAK_RBAC_GROUP_NAME": "groups",
    "KEYCLOAK_PROFILE_ATTRIBUTES": profile_attributes(),
    "KEYCLOAK_PROFILE_GROUPS": ROLE_VARS["KEYCLOAK_PROFILE_GROUPS"],
    "KEYCLOAK_PROFILE_MAPPER_PREFIX": ROLE_VARS["KEYCLOAK_PROFILE_MAPPER_PREFIX"],
    "KEYCLOAK_EMAIL_POLICY": "external",
    "KEYCLOAK_EMAIL_MAILBOX": False,
    "KEYCLOAK_EMAIL_SMTP": False,
    "KEYCLOAK_EMAIL_VERIFY": False,
    "KEYCLOAK_EMAIL_UPDATE_ENABLED": False,
    "KEYCLOAK_EMAIL_SECONDARY_REQUIRED": True,
    "KEYCLOAK_EMAIL_DOMAIN": "example.com",
    "KEYCLOAK_EMAIL_SECONDARY_PATTERN": secondary_pattern("example.com"),
    "KEYCLOAK_EMAIL_POLICY_ATTRIBUTE": ROLE_VARS["KEYCLOAK_EMAIL_POLICY_ATTRIBUTE"],
    "KEYCLOAK_EMAIL_MAILBOX_ATTRIBUTE": OIDC_VARS["_oidc_email_mailbox_attribute"],
    "KEYCLOAK_REGISTRATION_ALLOWED": ROLE_VARS["KEYCLOAK_REGISTRATION_ALLOWED"],
    "KEYCLOAK_ADMIN_EVENTS_EXPIRATION": ADMIN_EVENTS_DAYS * 86400,
    **usage_context(),
    **organizations_context(False),
    "KEYCLOAK_PROXY_CLIENTS": [],
    "LDAP_ONLY": False,
    "OIDC": {
        "CLIENT": {"SECRET": "s3cret", "ID": "example.com"},
        "ATTRIBUTES": {
            "USERNAME": "preferred_username",
            "NEXTCLOUD_UID": OIDC_VARS["defaults_oidc"]["ATTRIBUTES"]["NEXTCLOUD_UID"],
        },
        "EMAIL": {"CLAIM_SOURCE": "email"},
    },
    "LDAP": {
        "DN": {
            "OU": {
                "USERS": "ou=users,dc=example,dc=com",
                "ROLES": "ou=roles,dc=example,dc=com",
            }
        },
        "RBAC": {
            "FLAVORS": ["groupOfNames"],
            "MEMBER_ATTRIBUTE": LDAP_VARS["LDAP"]["RBAC"]["MEMBER_ATTRIBUTE"],
        },
        "USER": {"ATTRIBUTES": LDAP_USER_ATTRIBUTES},
    },
}


def path_join(parts):
    head, *tail = list(parts)
    return "/".join([head.rstrip("/"), *[p.strip("/") for p in tail]])


class _EchoKeys(dict):
    def __missing__(self, key):
        return key


def fake_lookup(name, *_args, **_kwargs):
    """Stub the lookups the realm import performs.

    Args:
        name: the lookup plugin the template asked for; a ``config`` path
            answers with its last segment, and a ``...clients`` mapping answers
            every client key with the key itself.
    """
    if name == "email":
        return {"enabled": False}
    if name == "config":
        key = str(_args[-1]).rsplit(".", 1)[-1]
        return _EchoKeys() if key == "clients" else key
    if name == "network_urls":
        return [_args[0]]
    return APP_URL


def onion_sibling(url: str) -> list[str]:
    """
    Args:
        url: the URL lookup('network_urls') is asked for.

    Returns:
        The URL on clearnet and on the onion sibling of the SAML app's host.
    """
    if not url.startswith(APP_URL):
        return [url]
    return [url, ONION_URL + url.removeprefix(APP_URL)]


def render(
    saml_apps: list[str],
    client_apps: list[str] | None = None,
    network_urls=None,
    overrides: dict | None = None,
    roots: list[str] | None = None,
    answer=None,
) -> str:
    """
    Args:
        saml_apps: KEYCLOAK_SAML_APPS.
        client_apps: KEYCLOAK_DECLARED_CLIENT_APPS.
        network_urls: answer of lookup('network_urls', url); None serves one network.
        overrides: context values replacing those of CONTEXT.
        roots: template roots searched after the project root, for fixture roles.
        answer: lookup stub replacing fake_lookup; None keeps it.
    """

    def lookup(name, *args, **kwargs):
        if name == "network_urls" and network_urls is not None:
            return network_urls(*args)
        return (answer or fake_lookup)(name, *args, **kwargs)

    env = Environment(
        loader=FileSystemLoader([str(IMPORT_DIR), str(PROJECT_ROOT), *(roots or [])]),
        trim_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["path_join"] = path_join
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = bool
    env.filters["regex_replace"] = lambda value, pattern, repl="": re.sub(
        pattern, repl, str(value)
    )
    env.filters.update(role_filters())
    return env.get_template("realm.json.j2").render(
        KEYCLOAK_SAML_APPS=saml_apps,
        KEYCLOAK_DECLARED_CLIENT_APPS=client_apps or [],
        lookup=lookup,
        application_id="web-app-keycloak",
        DOMAIN_PRIMARY="example.com",
        **{**CONTEXT, **(overrides or {})},
    )


def username_pattern() -> re.Pattern[str]:
    realm = json.loads(render([]))
    provider = realm["components"]["org.keycloak.userprofile.UserProfileProvider"]
    profile = json.loads(provider[0]["config"]["kc.user.profile.config"][0])
    username = next(
        attribute
        for attribute in profile["attributes"]
        if attribute["name"] == "username"
    )
    return re.compile(username["validations"]["pattern"]["pattern"])


def organizations_probe_usernames() -> tuple[list[str], int]:
    """Returns:
    every username test-organizations.js creates in Keycloak, and the number
    of createProbeUser call sites, so a call the parse misses shows up.
    """
    source = read_text(str(ORGANIZATIONS_SPEC))
    prefix = re.search(
        r'^const PROBE_PREFIX = "([^"]*)";$', source, re.MULTILINE
    ).group(1)
    names = re.findall(r'await createProbeUser\(\s*kc,\s*"([^"]+)"', source)
    lists = re.findall(
        r"for \(const name of \[([^\]]*)\]\) \{\s*users\[name\] = await createProbeUser",
        source,
    )
    for listed in lists:
        names += re.findall(r'"([^"]+)"', listed)
    covered = len(re.findall(r'await createProbeUser\(\s*kc,\s*"', source)) + len(lists)
    sites = len(re.findall(r"await createProbeUser\(", source))
    return [prefix + name for name in names], sites - covered


class TestRealmImportJson(unittest.TestCase):
    def test_app_declared_clients_join_the_realm(self) -> None:
        """An app in KEYCLOAK_DECLARED_CLIENT_APPS ships its own client fragment."""
        realm = json.loads(render([], client_apps=["web-app-stalwart"]))
        client_ids = [c["clientId"] for c in realm["clients"]]
        self.assertIn("webui", client_ids)
        self.assertIn("webmail", client_ids)

    def test_no_declaring_apps_means_no_extra_clients(self) -> None:
        with_apps = json.loads(render([], client_apps=["web-app-stalwart"]))
        without = json.loads(render([]))
        self.assertEqual(len(with_apps["clients"]) - len(without["clients"]), 2)

    def test_realm_is_valid_json_without_saml_apps(self) -> None:
        realm = json.loads(render([]))
        client_ids = [c["clientId"] for c in realm["clients"]]
        self.assertNotIn(path_join([APP_URL, "saml/metadata"]), client_ids)

    def test_the_declarative_profile_declares_uidnumber(self) -> None:
        """Keycloak drops writes to an attribute the profile does not declare, and
        the unmanaged-attribute policy is DISABLED by default, so an undeclared
        uidNumber leaves the mattermost-id mapper with nothing to emit and the
        OIDC callback fails on a user id of 0."""
        realm = json.loads(render([]))
        provider = realm["components"]["org.keycloak.userprofile.UserProfileProvider"]
        profile = json.loads(provider[0]["config"]["kc.user.profile.config"][0])
        declared = {attribute["name"] for attribute in profile["attributes"]}
        self.assertIn("uidNumber", declared)

    def test_only_admins_see_and_set_the_nextcloud_user_id(self) -> None:
        attribute = profile_of(json.loads(render([])))[
            CONTEXT["OIDC"]["ATTRIBUTES"]["NEXTCLOUD_UID"]
        ]
        self.assertEqual(
            attribute["permissions"], {"view": ["admin"], "edit": ["admin"]}
        )
        self.assertFalse(attribute["multivalued"])

    def test_every_profile_attribute_has_an_ldap_mapper(self) -> None:
        realm = json.loads(render([]))
        ldap = realm["components"]["org.keycloak.storage.UserStorageProvider"][0]
        mappers = {
            m["name"]: m["config"]
            for m in ldap["subComponents"][
                "org.keycloak.storage.ldap.mappers.LDAPStorageMapper"
            ]
        }
        prefix = CONTEXT["KEYCLOAK_PROFILE_MAPPER_PREFIX"]
        for attribute in CONTEXT["KEYCLOAK_PROFILE_ATTRIBUTES"]:
            config = mappers[prefix + attribute["name"]]
            self.assertEqual(config["ldap.attribute"], [attribute["ldap"]])
            self.assertEqual(config["user.model.attribute"], [attribute["name"]])

    def test_profile_mappers_do_not_depend_on_moodle(self) -> None:
        context = {**CONTEXT, "KEYCLOAK_MOODLE_ENABLED": False}
        with mock.patch.dict(CONTEXT, context):
            realm = json.loads(render([]))
        ldap = realm["components"]["org.keycloak.storage.UserStorageProvider"][0]
        names = {
            m["name"]
            for m in ldap["subComponents"][
                "org.keycloak.storage.ldap.mappers.LDAPStorageMapper"
            ]
        }
        self.assertIn(CONTEXT["KEYCLOAK_PROFILE_MAPPER_PREFIX"] + "country", names)
        self.assertNotIn("moodle:country", names)

    def test_contact_fields_are_user_editable_and_organization_fields_are_not(
        self,
    ) -> None:
        realm = json.loads(render([]))
        provider = realm["components"]["org.keycloak.userprofile.UserProfileProvider"]
        profile = json.loads(provider[0]["config"]["kc.user.profile.config"][0])
        attributes = {a["name"]: a for a in profile["attributes"]}
        self.assertEqual(
            attributes["phoneNumber"]["permissions"]["edit"], ["admin", "user"]
        )
        self.assertEqual(attributes["department"]["permissions"]["edit"], ["admin"])
        self.assertEqual(attributes["nextcloudQuota"]["permissions"]["edit"], ["admin"])
        self.assertEqual(
            {g["name"] for g in profile["groups"]},
            {"user-metadata", *CONTEXT["KEYCLOAK_PROFILE_GROUPS"]},
        )

    def test_the_username_length_follows_the_platform_limit(self) -> None:
        """Registration must admit the longest account name, so the profile
        carries IAM_ACCOUNT_MAX_LENGTH rather than Keycloak's own 255. Agent
        names reach that ceiling; humans stay under IAM_USERNAME_MAX_LENGTH by
        the users lint."""
        realm = json.loads(render([]))
        provider = realm["components"]["org.keycloak.userprofile.UserProfileProvider"]
        profile = json.loads(provider[0]["config"]["kc.user.profile.config"][0])
        username = next(
            attribute
            for attribute in profile["attributes"]
            if attribute["name"] == "username"
        )
        self.assertEqual(
            username["validations"]["length"]["max"],
            CONTEXT["IAM_ACCOUNT_MAX_LENGTH"],
        )

    def test_the_username_pattern_admits_only_what_every_app_accepts(self) -> None:
        pattern = username_pattern()
        self.assertTrue(pattern.match("alice19"))
        for refused in ("root", "al0ce", "alice_x", "zoe", "Alice"):
            with self.subTest(username=refused):
                self.assertIsNone(pattern.match(refused))

    def test_the_username_pattern_admits_the_agent_form(self) -> None:
        pattern = username_pattern()
        for agent in ("mant0alice", "cnsl0a1b2c3"):
            with self.subTest(username=agent):
                self.assertTrue(pattern.match(agent))
        for refused in (
            "mant0al0ce",
            "mant00alice",
            "man0alice",
            "0mantalice",
            "mant0",
            "mant0Alice",
            "mant0al_ce",
        ):
            with self.subTest(username=refused):
                self.assertIsNone(pattern.match(refused))

    def test_the_organizations_probe_users_pass_the_platform_username_rule(
        self,
    ) -> None:
        policies = load_policies(PROJECT_ROOT / "roles")
        realm = json.loads(
            render(
                [],
                overrides={
                    "IAM_USERNAME_PATTERNS": username_patterns(policies),
                    "IAM_ACCOUNT_MAX_LENGTH": account_max_length(policies),
                },
            )
        )
        username = profile_of(realm)["username"]["validations"]
        pattern = re.compile(username["pattern"]["pattern"])
        probes, unparsed = organizations_probe_usernames()
        self.assertEqual(unparsed, 0, "every createProbeUser call must name its user")
        self.assertGreater(len(probes), 0)
        for probe in probes:
            with self.subTest(username=probe):
                self.assertIsNotNone(pattern.match(probe))
                self.assertLessEqual(len(probe), username["length"]["max"])

    def test_only_an_admin_may_change_an_email_address(self) -> None:
        realm = json.loads(render([]))
        provider = realm["components"]["org.keycloak.userprofile.UserProfileProvider"]
        profile = json.loads(provider[0]["config"]["kc.user.profile.config"][0])
        email = next(
            attribute
            for attribute in profile["attributes"]
            if attribute["name"] == "email"
        )
        self.assertEqual(
            email["permissions"]["edit"],
            ["admin"],
            "applications resolve their account by this address and the realm does "
            "not verify a change, so a self-service edit takes over whichever account "
            "the typed address names",
        )
        self.assertEqual(email["permissions"]["view"], ["admin", "user"])

    def test_realm_is_valid_json_with_one_saml_app(self) -> None:
        realm = json.loads(render(["web-app-suitecrm"]))
        clients = {c["clientId"]: c for c in realm["clients"]}
        client = clients[path_join([APP_URL, "saml/metadata"])]
        self.assertEqual(client["protocol"], "saml")
        self.assertEqual(client["redirectUris"], [path_join([APP_URL, "saml/acs"])])

    def test_saml_client_accepts_the_assertion_consumer_of_every_network_sibling(
        self,
    ) -> None:
        realm = json.loads(render(["web-app-suitecrm"], network_urls=onion_sibling))
        client = next(c for c in realm["clients"] if c.get("protocol") == "saml")
        self.assertEqual(
            client["redirectUris"],
            [path_join([APP_URL, "saml/acs"]), path_join([ONION_URL, "saml/acs"])],
            "Keycloak checks the AssertionConsumerServiceURL of the request against "
            "redirectUris, so an onion login names an ACS it must list",
        )
        self.assertEqual(
            client["attributes"]["saml_assertion_consumer_url_post"],
            path_join([APP_URL, "saml/acs"]),
        )

    def test_realm_is_valid_json_with_several_saml_apps(self) -> None:
        realm = json.loads(render(["web-app-suitecrm", "web-app-other"]))
        saml = [c for c in realm["clients"] if c.get("protocol") == "saml"]
        self.assertEqual(len(saml), 2)

    def test_saml_client_asserts_groups_and_every_profile_attribute(self) -> None:
        realm = json.loads(render(["web-app-suitecrm"]))
        client = next(c for c in realm["clients"] if c.get("protocol") == "saml")
        mappers = {m["name"]: m for m in client["protocolMappers"]}
        groups = mappers[CONTEXT["KEYCLOAK_RBAC_GROUP_CLAIM"]]
        self.assertEqual(groups["protocolMapper"], "saml-group-membership-mapper")
        self.assertEqual(groups["config"]["full.path"], "true")
        prefix = CONTEXT["KEYCLOAK_PROFILE_MAPPER_PREFIX"]
        for attribute in CONTEXT["KEYCLOAK_PROFILE_ATTRIBUTES"]:
            mapper = mappers[f"{prefix}{attribute['name']}"]
            self.assertEqual(mapper["protocolMapper"], "saml-user-attribute-mapper")
            self.assertEqual(mapper["config"]["user.attribute"], attribute["name"])
            self.assertEqual(mapper["config"]["attribute.name"], attribute["ldap"])

    def test_saml_client_omits_the_role_list_scope(self) -> None:
        realm = json.loads(render(["web-app-suitecrm"]))
        client = next(c for c in realm["clients"] if c.get("protocol") == "saml")
        self.assertEqual(client["defaultClientScopes"], [])

    def test_the_allowed_origins_mapper_stays_out_of_the_access_token(self) -> None:
        """The claim grows with every registered origin and rides along in
        X-Forwarded-Access-Token, where an app server's header limit ends the
        request; Keycloak's own CORS reads client.webOrigins, not the claim."""
        realm = json.loads(render([]))
        scope = next(s for s in realm["clientScopes"] if s["name"] == "web-origins")
        mapper = next(
            m
            for m in scope["protocolMappers"]
            if m["protocolMapper"] == "oidc-allowed-origins-mapper"
        )
        self.assertEqual(mapper["config"]["access.token.claim"], "false")
        self.assertEqual(mapper["config"]["introspection.token.claim"], "true")

    def test_saml_client_maps_the_username_attribute_the_app_reads(self) -> None:
        realm = json.loads(render(["web-app-suitecrm"]))
        client = next(c for c in realm["clients"] if c.get("protocol") == "saml")
        names = {
            m["config"]["attribute.name"]
            for m in client["protocolMappers"]
            if m["name"] == "username"
        }
        self.assertEqual(names, {CONTEXT["OIDC"]["ATTRIBUTES"]["USERNAME"]})


CLIENT_APPS = sorted(
    path.parts[-4]
    for path in PROJECT_ROOT.glob("roles/*/templates/keycloak/clients.json.j2")
)
OWN_CLIENT_SECRET = "oidc_client_secret"
REALM_MANAGEMENT = "realm-management"
EVENT_SETTINGS = {
    "eventsEnabled": False,
    "eventsListeners": ["jboss-logging"],
    "enabledEventTypes": [],
    "adminEventsEnabled": True,
    "adminEventsDetailsEnabled": False,
}


ALLOWED_ORIGINS_MAPPER = "oidc-allowed-origins-mapper"


def puts_allowed_origins_into_access_tokens(entity: dict) -> bool:
    """Whether a client or client scope writes allowed-origins into the access token.

    Args:
        entity: a client or client scope representation.
    """
    return any(
        mapper["protocolMapper"] == ALLOWED_ORIGINS_MAPPER
        and mapper["config"].get("access.token.claim") == "true"
        for mapper in entity.get("protocolMappers", [])
    )


def realm_managing_service_accounts(realm: dict) -> list[str]:
    """Return the service-account users of ``realm`` that hold a realm-management role.

    Args:
        realm: the parsed realm render.
    """
    return [
        user["username"]
        for user in realm["users"]
        if "serviceAccountClientId" in user
        and user.get("clientRoles", {}).get(REALM_MANAGEMENT)
    ]


class TestLogoutTrustBoundary(unittest.TestCase):
    def setUp(self) -> None:
        self.realm = json.loads(render([], client_apps=CLIENT_APPS))

    def test_every_client_renders_on_the_shared_or_its_own_credential(self) -> None:
        secrets = {
            client["secret"]
            for client in self.realm["clients"]
            if client.get("protocol") == "openid-connect" and "secret" in client
        }
        self.assertEqual(
            secrets, {CONTEXT["OIDC"]["CLIENT"]["SECRET"], OWN_CLIENT_SECRET}
        )

    def test_no_service_account_user_holds_a_realm_management_role(self) -> None:
        self.assertTrue(
            [u for u in self.realm["users"] if "serviceAccountClientId" in u],
            "the shared client's service account is part of the render",
        )
        self.assertEqual(realm_managing_service_accounts(self.realm), [])

    def test_a_realm_management_grant_to_a_service_account_is_caught(self) -> None:
        user = next(u for u in self.realm["users"] if "serviceAccountClientId" in u)
        user["clientRoles"] = {REALM_MANAGEMENT: ["manage-users"]}
        self.assertEqual(
            realm_managing_service_accounts(self.realm), [user["username"]]
        )

    def _shared_client(self) -> dict:
        return next(
            c
            for c in self.realm["clients"]
            if c["clientId"] == CONTEXT["KEYCLOAK_CLIENT_ID"]
        )

    def _web_origins_scope(self) -> dict:
        return next(s for s in self.realm["clientScopes"] if s["name"] == "web-origins")

    def test_the_shared_client_carries_no_mapper_of_its_own(self) -> None:
        self.assertNotIn("protocolMappers", self._shared_client())

    def test_the_shared_client_keeps_allowed_origins_out_of_its_tokens(self) -> None:
        self.assertFalse(puts_allowed_origins_into_access_tokens(self._shared_client()))

    def test_an_allowed_origins_mapper_on_the_shared_client_is_caught(self) -> None:
        client = self._shared_client()
        client["protocolMappers"] = [
            {
                "protocolMapper": ALLOWED_ORIGINS_MAPPER,
                "config": {"access.token.claim": "true"},
            }
        ]
        self.assertTrue(puts_allowed_origins_into_access_tokens(client))

    def test_the_web_origins_scope_keeps_allowed_origins_out_of_access_tokens(
        self,
    ) -> None:
        self.assertFalse(
            puts_allowed_origins_into_access_tokens(self._web_origins_scope())
        )

    def test_allowed_origins_in_the_web_origins_scope_is_caught(self) -> None:
        scope = self._web_origins_scope()
        for mapper in scope["protocolMappers"]:
            mapper["config"]["access.token.claim"] = "true"
        self.assertTrue(puts_allowed_origins_into_access_tokens(scope))

    def test_only_the_dashboard_client_puts_allowed_origins_into_access_tokens(
        self,
    ) -> None:
        self.assertEqual(
            [
                c["clientId"]
                for c in self.realm["clients"]
                if puts_allowed_origins_into_access_tokens(c)
            ],
            ["dashboard"],
            "the fake config lookup answers the last segment of the client path",
        )

    def test_no_logout_client_joins_the_realm(self) -> None:
        self.assertNotIn("web-svc-logout", CLIENT_APPS)
        client_ids = {client["clientId"] for client in self.realm["clients"]}
        self.assertFalse({cid for cid in client_ids if "logout" in cid})

    def test_the_realm_keeps_its_event_settings(self) -> None:
        self.assertEqual(
            {key: self.realm[key] for key in EVENT_SETTINGS}, EVENT_SETTINGS
        )
        self.assertNotIn("eventsExpiration", self.realm)

    def test_the_realm_enables_fine_grained_admin_permissions(self) -> None:
        self.assertIs(self.realm["adminPermissionsEnabled"], True)

    def test_the_account_api_stays_open_to_the_users_own_token(self) -> None:
        default_roles = next(
            role
            for role in self.realm["roles"]["realm"]
            if role["name"] == f"default-roles-{CONTEXT['KEYCLOAK_REALM']}"
        )
        self.assertIn(
            "manage-account", default_roles["composites"]["client"]["account"]
        )
        self.assertIn(
            "account", {client["clientId"] for client in self.realm["clients"]}
        )


MAILBOX = {
    "KEYCLOAK_EMAIL_POLICY": "mailbox",
    "KEYCLOAK_EMAIL_MAILBOX": True,
    "OIDC": {
        **CONTEXT["OIDC"],
        "EMAIL": {"CLAIM_SOURCE": OIDC_VARS["_oidc_email_mailbox_attribute"]},
    },
}
SMTP = {"KEYCLOAK_EMAIL_SMTP": True}
LDAP_PROVIDER = "org.keycloak.storage.UserStorageProvider"


def role_flag(name: str, context: dict) -> bool:
    """Render one of the role's boolean expressions from ``vars/main.yml``.

    Args:
        name: the variable, e.g. KEYCLOAK_EMAIL_VERIFY.
        context: the values its expression reads.
    """
    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
    env.filters["bool"] = bool
    return env.from_string(ROLE_VARS[name]).render(**context) == "True"


def realm_for(overrides: dict, saml_apps: list[str] | None = None) -> dict:
    context = {**CONTEXT, **overrides}
    return json.loads(
        render(
            saml_apps or [],
            overrides={
                **overrides,
                "KEYCLOAK_EMAIL_VERIFY": role_flag("KEYCLOAK_EMAIL_VERIFY", context),
                "KEYCLOAK_EMAIL_UPDATE_ENABLED": role_flag(
                    "KEYCLOAK_EMAIL_UPDATE_ENABLED", context
                ),
            },
        )
    )


def profile_of(realm: dict) -> dict:
    provider = realm["components"]["org.keycloak.userprofile.UserProfileProvider"]
    profile = json.loads(provider[0]["config"]["kc.user.profile.config"][0])
    return {attribute["name"]: attribute for attribute in profile["attributes"]}


def ldap_mappers_of(realm: dict) -> dict:
    provider = realm["components"]["org.keycloak.storage.UserStorageProvider"][0]
    return {
        mapper["name"]: mapper
        for mapper in provider["subComponents"][
            "org.keycloak.storage.ldap.mappers.LDAPStorageMapper"
        ]
    }


def email_scope_mappers_of(realm: dict) -> dict:
    scope = next(s for s in realm["clientScopes"] if s["name"] == "email")
    return {mapper["name"]: mapper for mapper in scope["protocolMappers"]}


def update_email_of(realm: dict) -> dict:
    return next(a for a in realm["requiredActions"] if a["alias"] == "UPDATE_EMAIL")


def email_verification_findings(realm: dict) -> list[str]:
    """What lets an unproven address into the ``email`` claim or holds a directory user.

    Args:
        realm: the rendered realm import; a mailbox realm emits the platform-owned
            mailbox with a hardcoded ``email_verified`` and passes.
    """
    scope = email_scope_mappers_of(realm)
    if scope["email verified"]["protocolMapper"] == "oidc-hardcoded-claim-mapper":
        return []
    findings = []
    if realm["verifyEmail"] is not True:
        findings.append(
            "verifyEmail is off, so a sign-in finishes with an unverified address"
        )
    if LDAP_PROVIDER in realm["components"]:
        provider = realm["components"][LDAP_PROVIDER][0]
        if provider["config"]["trustEmail"] != ["true"]:
            findings.append(
                "trustEmail is off, so every user the federation imports waits on VERIFY_EMAIL"
            )
    return findings


class TestEmailPolicy(unittest.TestCase):
    def test_an_external_realm_with_smtp_lets_the_user_change_the_primary_by_link(
        self,
    ) -> None:
        realm = realm_for({**SMTP, "KEYCLOAK_LDAP_ENABLED": False})
        email = profile_of(realm)["email"]
        self.assertEqual(email["permissions"]["edit"], ["admin", "user"])
        self.assertEqual(email["required"], {"roles": ["user"]})
        self.assertTrue(realm["verifyEmail"])
        self.assertTrue(update_email_of(realm)["enabled"])
        self.assertEqual(update_email_of(realm)["config"], {"verifyEmail": "true"})
        self.assertNotIn("mailbox", profile_of(realm))
        self.assertEqual(
            email_scope_mappers_of(realm)["email"]["config"]["user.attribute"], "email"
        )
        self.assertEqual(realm["attributes"]["infinitoEmailPolicy"], "external")

    def test_an_external_realm_with_ldap_keeps_the_primary_in_ldap_mail(
        self,
    ) -> None:
        mappers = ldap_mappers_of(realm_for(SMTP))
        self.assertEqual(
            mappers["email"]["config"]["ldap.attribute"],
            [LDAP_USER_ATTRIBUTES["MAIL"]],
        )
        self.assertNotIn("mailbox", mappers)

    def test_an_external_realm_without_smtp_leaves_the_address_to_admins(
        self,
    ) -> None:
        realm = realm_for({})
        self.assertEqual(profile_of(realm)["email"]["permissions"]["edit"], ["admin"])
        self.assertFalse(realm["verifyEmail"])
        self.assertFalse(update_email_of(realm)["enabled"])

    def test_a_mailbox_realm_keeps_the_primary_out_of_the_users_reach(self) -> None:
        realm = realm_for({**MAILBOX, **SMTP})
        profile = profile_of(realm)
        self.assertEqual(profile["mailbox"]["permissions"]["edit"], ["admin"])
        self.assertEqual(profile["mailbox"]["permissions"]["view"], ["admin", "user"])
        self.assertFalse(realm["verifyEmail"])
        self.assertEqual(update_email_of(realm)["config"], {"verifyEmail": "true"})
        mappers = ldap_mappers_of(realm)
        self.assertEqual(
            mappers["mailbox"]["config"]["ldap.attribute"],
            [LDAP_USER_ATTRIBUTES["MAIL"]],
        )
        self.assertEqual(mappers["mailbox"]["config"]["read.only"], ["true"])
        self.assertEqual(
            mappers["mailbox"]["config"]["always.read.value.from.ldap"], ["true"]
        )
        self.assertEqual(
            mappers["email"]["config"]["ldap.attribute"],
            [LDAP_USER_ATTRIBUTES["SECONDARY_MAIL"]],
        )
        self.assertEqual(realm["attributes"]["infinitoEmailPolicy"], "mailbox")

    def test_a_mailbox_realm_hands_apps_the_mailbox_as_verified_email(self) -> None:
        realm = realm_for({**MAILBOX, **SMTP}, saml_apps=["web-app-suitecrm"])
        scope = email_scope_mappers_of(realm)
        self.assertEqual(scope["email"]["config"]["user.attribute"], "mailbox")
        self.assertEqual(
            scope["email verified"]["protocolMapper"], "oidc-hardcoded-claim-mapper"
        )
        self.assertEqual(scope["email verified"]["config"]["claim.value"], "true")
        saml = next(c for c in realm["clients"] if c.get("protocol") == "saml")
        saml_email = next(m for m in saml["protocolMappers"] if m["name"] == "email")
        self.assertEqual(saml_email["protocolMapper"], "saml-user-attribute-mapper")
        self.assertEqual(saml_email["config"]["user.attribute"], "mailbox")

    def test_saml_carries_the_same_primary_as_the_oidc_email_claim(self) -> None:
        for name, overrides, attribute in (
            ("external", SMTP, "email"),
            ("external without smtp", {}, "email"),
            ("mailbox", {**MAILBOX, **SMTP}, "mailbox"),
        ):
            with self.subTest(policy=name):
                realm = realm_for(overrides, saml_apps=["web-app-suitecrm"])
                oidc = email_scope_mappers_of(realm)["email"]["config"]
                saml = next(c for c in realm["clients"] if c.get("protocol") == "saml")
                saml_email = next(
                    m for m in saml["protocolMappers"] if m["name"] == "email"
                )
                self.assertEqual(oidc["user.attribute"], attribute)
                self.assertEqual(saml_email["config"]["user.attribute"], attribute)

    def test_a_secondary_address_in_the_mailbox_domain_is_refused(self) -> None:
        email = profile_of(realm_for({**MAILBOX, **SMTP}))["email"]
        pattern = re.compile(email["validations"]["pattern"]["pattern"])
        self.assertIsNone(pattern.match("biber@example.com"))
        self.assertIsNone(pattern.match("Biber@EXAMPLE.COM"))
        self.assertIsNotNone(pattern.match("biber@example.org"))
        self.assertIsNotNone(pattern.match("biber@sub.example.com.evil"))

    def test_the_secondary_address_is_required_only_once_registration_is_open(
        self,
    ) -> None:
        closed = profile_of(realm_for({**MAILBOX, **SMTP}))["email"]
        self.assertNotIn("required", closed)
        opened = profile_of(
            realm_for({**MAILBOX, **SMTP, "KEYCLOAK_REGISTRATION_ALLOWED": True})
        )["email"]
        self.assertEqual(opened["required"], {"roles": ["user"]})
        switched_off = profile_of(
            realm_for(
                {
                    **MAILBOX,
                    **SMTP,
                    "KEYCLOAK_REGISTRATION_ALLOWED": True,
                    "KEYCLOAK_EMAIL_SECONDARY_REQUIRED": False,
                }
            )
        )["email"]
        self.assertNotIn("required", switched_off)

    def test_the_federation_trusts_the_directory_addresses_in_every_policy(
        self,
    ) -> None:
        for overrides in ({}, SMTP, {**MAILBOX, **SMTP}):
            with self.subTest(overrides=overrides):
                provider = realm_for(overrides)["components"][LDAP_PROVIDER][0]
                self.assertEqual(provider["config"]["trustEmail"], ["true"])

    def test_with_mail_no_unverified_address_reaches_the_email_claim(self) -> None:
        for name, overrides in (
            ("external with ldap", SMTP),
            ("external without ldap", {**SMTP, "KEYCLOAK_LDAP_ENABLED": False}),
            ("mailbox", {**MAILBOX, **SMTP}),
        ):
            with self.subTest(policy=name):
                self.assertEqual(email_verification_findings(realm_for(overrides)), [])

    def test_without_mail_the_realm_cannot_demand_a_verification(self) -> None:
        self.assertEqual(
            email_verification_findings(realm_for({})),
            ["verifyEmail is off, so a sign-in finishes with an unverified address"],
        )

    def test_an_untrusted_federation_fails_the_check(self) -> None:
        realm = realm_for(SMTP)
        realm["components"][LDAP_PROVIDER][0]["config"]["trustEmail"] = ["false"]
        self.assertEqual(
            email_verification_findings(realm),
            [
                "trustEmail is off, so every user the federation imports waits on VERIFY_EMAIL"
            ],
        )

    def test_no_policy_allows_duplicate_emails(self) -> None:
        for overrides in ({}, SMTP, {**MAILBOX, **SMTP}):
            with self.subTest(overrides=overrides):
                self.assertFalse(realm_for(overrides)["duplicateEmailsAllowed"])


EXPORT_RECIPIENT = ROLE_VARS["KEYCLOAK_EXPORT_RECIPIENT_ATTRIBUTE"]
EXPORT_PY = PROJECT_ROOT / "roles/web-app-semaphore/files/python/export.py"
BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
RECIPIENT = "age1" + (BECH32 * 2)[:58]
REFUSED_RECIPIENTS = (
    "",
    RECIPIENT[:-1],
    RECIPIENT + "q",
    RECIPIENT.upper(),
    RECIPIENT[:-1] + "b",
    RECIPIENT[:-1] + "1",
    "age2" + RECIPIENT[4:],
    f"{RECIPIENT} {RECIPIENT}",
    f"{RECIPIENT}\n",
    f" {RECIPIENT}",
)


def export_recipient_pattern() -> re.Pattern[str]:
    """
    Returns:
        ``RECIPIENT`` of the export script, which reads the attribute.
    """
    spec = importlib.util.spec_from_file_location("semaphore_export", EXPORT_PY)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.object(sys, "path", [str(EXPORT_PY.parent), *sys.path]):
        spec.loader.exec_module(module)
    return module.RECIPIENT


def organizations_realm(saml_apps: list[str] | None = None) -> dict:
    """
    Args:
        saml_apps: KEYCLOAK_SAML_APPS.

    Returns:
        The parsed realm import with organizations on.
    """
    return json.loads(render(saml_apps or [], overrides=organizations_context(True)))


def recipient_findings(realm: dict) -> list[str]:
    """
    Args:
        realm: the parsed realm import.

    Returns:
        What keeps ``export_recipient`` from one single-valued age recipient that
        only its user sets and admins see.
    """
    attribute = profile_of(realm).get(EXPORT_RECIPIENT)
    if attribute is None:
        return [f"the profile declares no {EXPORT_RECIPIENT}"]
    permissions = attribute["permissions"]
    findings = [] if permissions["edit"] == ["user"] else [f"edit is {permissions}"]
    if "admin" not in permissions["view"]:
        findings.append(f"view is {permissions['view']}")
    if attribute["multivalued"] is not False:
        findings.append("multivalued")
    pattern = re.compile(attribute["validations"]["pattern"]["pattern"])
    if not pattern.fullmatch(RECIPIENT):
        findings.append("the pattern refuses an age recipient")
    findings.extend(
        f"the pattern admits {value!r}"
        for value in REFUSED_RECIPIENTS
        if pattern.fullmatch(value)
    )
    return findings


def without_recipient(realm: dict, change) -> dict:
    """
    Args:
        realm: the parsed realm import.
        change: callable that edits the profile attribute list in place.

    Returns:
        A copy of ``realm`` whose user profile ``change`` edited.
    """
    planted = copy.deepcopy(realm)
    provider = planted["components"]["org.keycloak.userprofile.UserProfileProvider"]
    profile = json.loads(provider[0]["config"]["kc.user.profile.config"][0])
    change(profile["attributes"])
    provider[0]["config"]["kc.user.profile.config"] = [json.dumps(profile)]
    return planted


def recipient_of(attributes: list[dict]) -> dict:
    """
    Args:
        attributes: the attribute list of a user profile.

    Returns:
        Its ``export_recipient`` attribute.
    """
    return next(a for a in attributes if a["name"] == EXPORT_RECIPIENT)


class TestExportRecipient(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.realm = organizations_realm(["web-app-suitecrm"])

    def test_the_export_recipient_is_user_editable_only(self) -> None:
        self.assertEqual(recipient_findings(self.realm), [])

    def test_the_profile_admits_what_the_export_script_admits(self) -> None:
        script = export_recipient_pattern()
        pattern = re.compile(
            profile_of(self.realm)[EXPORT_RECIPIENT]["validations"]["pattern"][
                "pattern"
            ]
        )
        for value in (RECIPIENT, *REFUSED_RECIPIENTS):
            with self.subTest(value=value):
                self.assertEqual(
                    bool(pattern.fullmatch(value)), bool(script.fullmatch(value))
                )

    def test_the_check_catches_an_admin_edit(self) -> None:
        def admin_edit(attributes: list[dict]) -> None:
            recipient_of(attributes)["permissions"]["edit"] = ["admin", "user"]

        self.assertEqual(
            recipient_findings(without_recipient(self.realm, admin_edit)),
            ["edit is {'view': ['admin', 'user'], 'edit': ['admin', 'user']}"],
        )

    def test_the_check_catches_a_dropped_attribute(self) -> None:
        def drop(attributes: list[dict]) -> None:
            attributes.remove(recipient_of(attributes))

        self.assertEqual(
            recipient_findings(without_recipient(self.realm, drop)),
            [f"the profile declares no {EXPORT_RECIPIENT}"],
        )

    def test_the_check_catches_a_multivalued_or_loose_attribute(self) -> None:
        def multivalued(attributes: list[dict]) -> None:
            recipient_of(attributes)["multivalued"] = True

        def loose(attributes: list[dict]) -> None:
            recipient_of(attributes)["validations"]["pattern"]["pattern"] = "age1.*"

        for change in (multivalued, loose):
            with self.subTest(change=change.__name__):
                self.assertTrue(
                    recipient_findings(without_recipient(self.realm, change))
                )

    def test_without_organizations_no_recipient_is_declared(self) -> None:
        self.assertNotIn(EXPORT_RECIPIENT, profile_of(json.loads(render([]))))

    def test_the_recipient_reaches_neither_ldap_nor_saml(self) -> None:
        self.assertNotIn(
            EXPORT_RECIPIENT,
            [entry["name"] for entry in CONTEXT["KEYCLOAK_PROFILE_ATTRIBUTES"]],
        )
        self.assertFalse(
            [
                name
                for name, mapper in ldap_mappers_of(self.realm).items()
                if EXPORT_RECIPIENT in json.dumps(mapper)
            ]
        )
        saml = next(c for c in self.realm["clients"] if c.get("protocol") == "saml")
        self.assertNotIn(EXPORT_RECIPIENT, json.dumps(saml["protocolMappers"]))

    def test_an_existing_realm_gets_the_profile_of_the_render(self) -> None:
        init = load_yaml_any(str(ROLE_DIR / "tasks/02_init.yml"))
        facts = {
            name: value
            for task in init
            for name, value in (task.get("set_fact") or {}).items()
        }
        self.assertEqual(
            facts["KEYCLOAK_DICTIONARY_REALM_RAW"],
            "{{ lookup('template', 'import/realm.json.j2') }}",
        )
        self.assertIn(
            "KEYCLOAK_DICTIONARY_REALM.components['org.keycloak.userprofile.UserProfileProvider']",
            facts["KEYCLOAK_USER_PROFILE_OBJECT"],
        )
        (push,) = load_yaml_any(str(ROLE_DIR / "tasks/update/05_userprofile.yml"))
        self.assertIn("update users/profile", push["ansible.builtin.shell"])
        self.assertEqual(
            push["args"]["stdin"], "{{ KEYCLOAK_USER_PROFILE_OBJECT | to_json }}"
        )


def drifted_required_actions(desired: list, current: list) -> list:
    """Run the role's required-action drift filter on *desired* and *current*."""
    spec = importlib.util.spec_from_file_location(
        "keycloak_required_actions", ROLE_DIR / "filter_plugins/required_actions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.kc_drifted_required_actions(desired, current)


def otp_realm(realm_overrides: dict | None = None) -> dict:
    """Render the realm from ``meta/services.yml`` with *realm_overrides* applied.

    Args:
        realm_overrides: see ``realm_context``.
    """
    return json.loads(render([], overrides=realm_context(realm_overrides)))


OFFERED = {"totp_enforced": False}
DISABLED = {"totp_enabled": False, "totp_enforced": False}


def configure_totp(realm: dict) -> dict:
    return next(a for a in realm["requiredActions"] if a["alias"] == "CONFIGURE_TOTP")


def reconciled(realm: dict) -> list:
    return [
        a
        for a in realm["requiredActions"]
        if a["alias"] in ROLE_VARS["KEYCLOAK_RECONCILED_REQUIRED_ACTIONS"]
    ]


OTP_POLICY_DEFAULTS = {
    "otpPolicyType": "totp",
    "otpPolicyAlgorithm": "HmacSHA1",
    "otpPolicyDigits": 6,
    "otpPolicyPeriod": 30,
    "otpPolicyLookAheadWindow": 1,
    "otpPolicyInitialCounter": 0,
    "otpPolicyCodeReusable": False,
}


class TestTotpEnforcement(unittest.TestCase):
    def test_the_shipped_realm_sends_every_new_user_to_otp_enrollment(self) -> None:
        action = configure_totp(otp_realm())
        self.assertIs(True, action["enabled"])
        self.assertIs(True, action["defaultAction"])

    def test_an_override_offers_otp_without_forcing_it(self) -> None:
        action = configure_totp(otp_realm(OFFERED))
        self.assertIs(True, action["enabled"])
        self.assertIs(False, action["defaultAction"])

    def test_a_disabled_realm_does_not_offer_otp(self) -> None:
        action = configure_totp(otp_realm(DISABLED))
        self.assertIs(False, action["enabled"])
        self.assertIs(False, action["defaultAction"])

    def test_no_imported_user_starts_with_a_required_action(self) -> None:
        for overrides in ({}, OFFERED, DISABLED):
            for user in otp_realm(overrides)["users"]:
                with self.subTest(overrides=overrides, user=user["username"]):
                    self.assertEqual([], user["requiredActions"])

    def test_an_existing_realm_that_forces_otp_converges_to_offering_it(
        self,
    ) -> None:
        self.assertIn(
            "CONFIGURE_TOTP", ROLE_VARS["KEYCLOAK_RECONCILED_REQUIRED_ACTIONS"]
        )
        desired = reconciled(otp_realm(OFFERED))
        drifted = drifted_required_actions(desired, reconciled(otp_realm()))
        self.assertEqual(["CONFIGURE_TOTP"], [a["alias"] for a in drifted])
        self.assertIs(False, drifted[0]["defaultAction"])

    def test_an_existing_realm_that_offers_otp_converges_to_not_offering_it(
        self,
    ) -> None:
        desired = reconciled(otp_realm(DISABLED))
        drifted = drifted_required_actions(desired, reconciled(otp_realm(OFFERED)))
        self.assertEqual(["CONFIGURE_TOTP"], [a["alias"] for a in drifted])
        self.assertIs(False, drifted[0]["enabled"])

    def test_required_actions_converge_before_any_user_is_created_or_imported(
        self,
    ) -> None:
        routines = load_yaml_any(
            str(ROLE_DIR / "tasks/03_manager_ops/update_routines.yml")
        )
        includes = [
            str(task.get("include_tasks", ""))
            for routine in routines
            for task in routine.get("block", [routine])
        ]
        required = next(
            i for i, path in enumerate(includes) if "12_required_actions" in path
        )
        creators = [
            i
            for i, path in enumerate(includes)
            if any(step in path for step in ("06_users", "03_ldap", "14_email_policy"))
        ]
        self.assertTrue(creators)
        self.assertLess(required, min(creators))

    def test_an_existing_realm_converges_to_enforcing_otp(self) -> None:
        desired = reconciled(otp_realm())
        drifted = drifted_required_actions(desired, reconciled(otp_realm(OFFERED)))
        self.assertEqual(["CONFIGURE_TOTP"], [a["alias"] for a in drifted])
        self.assertIs(True, drifted[0]["defaultAction"])


class TestOtpPolicy(unittest.TestCase):
    def test_the_shipped_policy_is_the_authenticator_app_default(self) -> None:
        realm = otp_realm()
        self.assertEqual(
            OTP_POLICY_DEFAULTS, {field: realm[field] for field in OTP_POLICY_DEFAULTS}
        )
        self.assertIs(int, type(realm["otpPolicyDigits"]))
        self.assertIs(bool, type(realm["otpPolicyCodeReusable"]))

    def test_every_policy_key_of_the_services_config_reaches_the_realm(self) -> None:
        cases = {
            "otp_policy.type": ("otpPolicyType", "hotp"),
            "otp_policy.algorithm": ("otpPolicyAlgorithm", "HmacSHA512"),
            "otp_policy.digits": ("otpPolicyDigits", 8),
            "otp_policy.period": ("otpPolicyPeriod", 60),
            "otp_policy.look_ahead_window": ("otpPolicyLookAheadWindow", 3),
            "otp_policy.initial_counter": ("otpPolicyInitialCounter", 5),
            "otp_policy.code_reusable": ("otpPolicyCodeReusable", True),
        }
        for path, (field, value) in cases.items():
            with self.subTest(path=path):
                self.assertNotEqual(value, OTP_POLICY_DEFAULTS[field])
                realm = otp_realm({path: value})
                self.assertEqual(value, realm[field])
                self.assertEqual(
                    {f: v for f, v in OTP_POLICY_DEFAULTS.items() if f != field},
                    {f: realm[f] for f in OTP_POLICY_DEFAULTS if f != field},
                )


class TestAccessTokenLifespan(unittest.TestCase):
    def test_the_realm_renders_the_configured_lifespan(self) -> None:
        shipped = ROLE_SERVICES["keycloak"]["realm"]["access_token_lifespan_seconds"]
        self.assertEqual(300, shipped)
        self.assertEqual(shipped, otp_realm()["accessTokenLifespan"])

    def test_a_changed_lifespan_reaches_the_realm_as_an_integer(self) -> None:
        realm = otp_realm({"access_token_lifespan_seconds": 600})
        self.assertEqual(600, realm["accessTokenLifespan"])
        self.assertIs(int, type(realm["accessTokenLifespan"]))


class TestAdminEvents(unittest.TestCase):
    def test_the_expiration_renders_the_configured_days_in_seconds(self) -> None:
        env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
        env.filters["int"] = int
        days = env.from_string(
            ROLE_VARS["KEYCLOAK_ADMIN_EVENTS_EXPIRATION_DAYS"]
        ).render(
            application_id="web-app-keycloak",
            lookup=lambda _name, _app, path: (
                ADMIN_EVENTS_DAYS
                if path == "services.keycloak.events.admin.expiration_days"
                else None
            ),
        )
        rendered = env.from_string(
            ROLE_VARS["KEYCLOAK_ADMIN_EVENTS_EXPIRATION"]
        ).render(KEYCLOAK_ADMIN_EVENTS_EXPIRATION_DAYS=days)
        self.assertEqual(str(ADMIN_EVENTS_DAYS * 86400), rendered)

    def test_a_new_realm_imports_the_expiration(self) -> None:
        realm = json.loads(render([]))
        self.assertTrue(realm["adminEventsEnabled"])
        self.assertEqual(
            str(ADMIN_EVENTS_DAYS * 86400),
            realm["attributes"]["adminEventsExpiration"],
        )


if __name__ == "__main__":
    unittest.main()
