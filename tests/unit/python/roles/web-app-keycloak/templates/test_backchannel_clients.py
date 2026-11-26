from __future__ import annotations

import importlib.util
import json
import re
import unittest
import unittest.mock as mock
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_DOMAINS,
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT
from .test_realm_import_json import CONTEXT, render

if TYPE_CHECKING:
    from pathlib import Path

CLIENT_TEMPLATES = sorted(
    PROJECT_ROOT.glob("roles/*/templates/keycloak/clients.json.j2")
)
BACKCHANNEL_LOGOUT_URL = "backchannel.logout.url"
SERVICE_ACCOUNT_SCOPE = "service_account"
ONION = "a" * 56 + ".onion"
SHARED_CLIENT_ID = CONTEXT["KEYCLOAK_CLIENT_ID"]
CLIENT_ID_CONSUMERS = (
    "roles/*/templates/**/*.j2",
    "roles/*/vars/*.yml",
    "roles/*/tasks/**/*.yml",
    f"roles/*/{ROLE_FILE_META_FORMS}",
)
CLIENT_ID_LOOKUP = re.compile(
    r"lookup\(\s*'config'\s*,\s*[^,()]+,\s*'services\.sso\.oidc\.clients\.\w+'\s*"
    r"(?P<tail>[,)])(?P<fallback>\s*\|\s*default\b)?"
)
CLIENT_KEY_READ = re.compile(r"services\.sso\.oidc\.clients(?:\.|'\)\.)(?P<key>\w+)")
SHARED_CLIENT_ID_READ = re.compile(r"OIDC\.CLIENT\.ID\b")
KEYCLOAK_FRAGMENT = ("templates", "keycloak", "clients.json.j2")
SSO_OIDC_PLUGIN = "user_oidc"
NEXTCLOUD = "web-app-nextcloud"
OPENCLOUD = "web-app-opencloud"
OPENPOST = "web-app-openpost"
OPENTALK = "web-app-opentalk"
OPENTALK_CLIENT_TASKS = (
    PROJECT_ROOT / "roles" / OPENTALK / "tasks/02_keycloak_client.yml"
)
XWIKI = "web-app-xwiki"
MATRIX = "web-app-matrix"
LOGOUT_GATE = "web-svc-logout"
LOGOUT_GATE_PATH = "/backchannel/"
USER_OIDC_BACKCHANNEL_PATH = "/index.php/apps/user_oidc/backchannel-logout/"
UPSTREAM_BACKCHANNEL_ENDPOINTS = {
    MATRIX: ("synapse", "/_synapse/client/oidc/backchannel_logout"),
    "web-app-mediawiki": ("", "/rest.php/pluggableauth/v1/logout"),
    NEXTCLOUD: ("", USER_OIDC_BACKCHANNEL_PATH + "keycloak"),
    OPENCLOUD: ("", "/backchannel_logout"),
    OPENPOST: ("", "/api/v1/auth/oidc/instance/backchannel-logout"),
    OPENTALK: ("", "/v1/auth/logout"),
    "web-app-openwebui": ("", "/oauth/backchannel-logout"),
    XWIKI: ("", "/oidc/authenticator/backchannel_logout"),
    "web-app-zammad": ("", "/auth/openid_connect/backchannel_logout"),
}
NEXTCLOUD_ADMIN_GROUP = "admin"
RBAC_GROUP_ROOT = "roles"
GROUP_MAPPER = "oidc-group-membership-mapper"
CLIENT_ROLE_MAPPER = "oidc-usermodel-client-role-mapper"
TOKEN_FLAGS = ("id.token.claim", "access.token.claim", "userinfo.token.claim")


def resolved(node):
    """A ``meta/services.yml`` node, with a single Jinja expression evaluated.

    Args:
        node: the raw node; a ``{{ ... }}`` string renders through the stubbed
            lookups to its native value.
    """
    if isinstance(node, str) and node.lstrip().startswith("{{"):
        return NativeEnvironment().from_string(node).render(lookup=lookup)
    return node


def role_config(role: str, path: str):
    """Resolve ``lookup('config', role, path)`` for a ``services.*`` path.

    Args:
        role: role directory name.
        path: dotted path below the role's config, starting with ``services.``.
    """
    head, _, rest = path.partition(".")
    if head != "services":
        raise AssertionError(f"unexpected config path {path!r} for {role}")
    node = load_yaml_any(str(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES))
    for key in rest.split("."):
        node = resolved(node)[key]
    return resolved(node)


def oidc_clients_filters():
    spec = importlib.util.spec_from_file_location(
        "oidc_clients",
        PROJECT_ROOT / "roles/web-app-keycloak/filter_plugins/oidc_clients.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def declarations(apps: list[str]) -> dict:
    """The ``services.sso.oidc`` declarations of the deployed apps, resolved.

    Args:
        apps: the deployed role directory names.
    """
    return {
        app: {
            "services": {
                "sso": {
                    "oidc": {
                        key: resolved(value)
                        for key, value in role_config(app, "services.sso.oidc").items()
                    }
                }
            }
        }
        for app in apps
    }


def declared_client_apps(apps: list[str]) -> list[str]:
    """What Keycloak's ``kc_declared_client_apps`` filter makes of the declarations.

    Args:
        apps: the deployed role directory names.
    """
    return oidc_clients_filters().kc_declared_client_apps(declarations(apps), apps)


def declared_client_role_grants(apps: list[str]) -> list[dict]:
    """What Keycloak's ``kc_declared_client_role_grants`` filter makes of the declarations.

    Args:
        apps: the deployed role directory names, all with RBAC groups in the run.
    """
    return oidc_clients_filters().kc_declared_client_role_grants(
        declarations(apps), apps, RBAC_GROUP_ROOT
    )


def group_claim_mapper() -> dict:
    """The group membership mapper of the RBAC client scope, as the realm renders it."""
    realm = json.loads(render([]))
    scope = next(
        s
        for s in realm["clientScopes"]
        if s["name"] == CONTEXT["KEYCLOAK_RBAC_GROUP_CLAIM"]
    )
    return next(
        m for m in scope["protocolMappers"] if m["protocolMapper"] == GROUP_MAPPER
    )


def client_role_claim_findings(client: dict, group_mapper: dict) -> list[str]:
    """What keeps a client's role mapper from adding its roles to the group claim.

    Keycloak 26.8.2 adds a client role list to a collection the claim already
    holds and replaces anything else (``AbstractUserRoleMappingMapper.mapClaim``,
    services/.../oidc/mappers/AbstractUserRoleMappingMapper.java:111-116); a
    mapper that is not multivalued hands it one String
    (``OIDCAttributeMapperHelper.mapAttributeValue``, :176-180), which replaces
    the group paths.

    Args:
        client: the client representation carrying the mapper.
        group_mapper: the group membership mapper that writes the claim first.
    """
    mappers = [
        m
        for m in client.get("protocolMappers", [])
        if m["protocolMapper"] == CLIENT_ROLE_MAPPER
    ]
    if len(mappers) != 1:
        return [f"{len(mappers)} client role mappers instead of one"]
    config = mappers[0]["config"]
    findings = []
    if config.get("usermodel.clientRoleMapping.clientId") != client["clientId"]:
        findings.append("the mapper reads the roles of another client")
    if config.get("usermodel.clientRoleMapping.rolePrefix"):
        findings.append("a role prefix renames the Nextcloud group")
    if config.get("claim.name") != group_mapper["config"]["claim.name"]:
        findings.append("the mapper writes another claim than the group claim")
    if config.get("multivalued") != "true":
        findings.append("the mapper is not multivalued and replaces the group paths")
    findings.extend(
        f"{flag} differs from the group claim"
        for flag in TOKEN_FLAGS
        if config.get(flag) != group_mapper["config"].get(flag)
    )
    return findings


def canonical_origin(app: str, key: str = "") -> str:
    """The clearnet origin the stub serves an application, or one canonical of it.

    Args:
        app: application id.
        key: named canonical domain, empty for the primary one.
    """
    return f"https://{key + '.' if key else ''}{app}.example.com"


def primary_domain_key(app: str) -> str:
    """The named canonical domain ``lookup('tls', app, 'url.origin')`` serves.

    Args:
        app: application id.

    Returns:
        The first key of a named ``canonical`` map in the role's meta/domains.yml,
        empty for a role with a single canonical domain.
    """
    path = PROJECT_ROOT / "roles" / app / ROLE_FILE_META_DOMAINS
    canonical = load_yaml_any(str(path)).get("canonical") if path.is_file() else None
    return next(iter(canonical)) if isinstance(canonical, dict) else ""


def onion_sibling(url: str) -> list[str]:
    """
    Args:
        url: the URL lookup('network_urls') is asked for.

    Returns:
        The URL on the clearnet and on its onion sibling, canonical network first.
    """
    parts = urlsplit(url)
    onion = parts.netloc.removesuffix(".example.com") + "." + ONION
    return [url, f"http://{onion}{parts.path}"]


def lookup(name, *args, **_kwargs):
    """Stub the lookups an application's client fragment performs.

    Args:
        name: the lookup plugin the template asked for.
    """
    if name == "config" and str(args[1]).startswith("secrets.credentials."):
        return f"{args[0]}-{str(args[1]).rsplit('.', 1)[-1]}"
    if name == "config":
        return role_config(*args)
    if name == "canonical_url":
        return canonical_origin(*args)
    if name == "tls":
        return canonical_origin(args[0], primary_domain_key(args[0]))
    if name == "network_urls":
        return onion_sibling(args[0])
    if name == "sso_oidc_plugin":
        return SSO_OIDC_PLUGIN
    raise AssertionError(f"unexpected lookup {name}{args}")


def render_fragment(template: Path) -> list[dict]:
    """Render one ``templates/keycloak/clients.json.j2`` the way the realm includes it.

    Args:
        template: the fragment's path.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = bool
    env.filters["regex_replace"] = lambda value, pattern, repl="": re.sub(
        pattern, repl, str(value)
    )
    source = env.get_template(str(template.relative_to(PROJECT_ROOT))).render(
        lookup=lookup, **CONTEXT
    )
    return json.loads(f"[{source}]")


def opentalk_client_upserts() -> dict[bool, dict]:
    """The kcadm client upserts of OpenTalk, keyed by ``publicClient``.

    Returns:
        The frontend task under True and the controller task under False.
    """
    return {
        task["keycloak_kcadm_update"]["desired"]["publicClient"]: task
        for task in load_yaml_any(str(OPENTALK_CLIENT_TASKS))
        if task.get("keycloak_kcadm_update", {}).get("object_kind") == "client"
    }


def render_task_value(task: dict, value: str):
    """Render one value of an OpenTalk task with the task's own vars.

    Args:
        task: the task that carries the value.
        value: the raw value, a Jinja expression.
    """
    env = NativeEnvironment()
    context = {"lookup": lookup, "application_id": OPENTALK}
    for name, raw in task.get("vars", {}).items():
        context[name] = env.from_string(raw).render(**context)
    return env.from_string(value).render(**context)


def gated(role: str) -> bool:
    """Tell whether a role's receiver sits behind the logout gate.

    Args:
        role: role directory name.
    """
    return role_config(role, "services.sso.oidc").get("backchannel_logout_gate") is True


def logout_gate_url(role: str) -> str:
    """Return the logout gate URL Keycloak sends a gated role's logout tokens to.

    Args:
        role: role directory name.
    """
    return canonical_origin(LOGOUT_GATE) + LOGOUT_GATE_PATH + role


def logout_receiver(url: str) -> str:
    """Return the receiver a back-channel logout URL reaches, through the gate or not.

    Args:
        url: a client's back-channel logout URL.
    """
    gate = canonical_origin(LOGOUT_GATE) + LOGOUT_GATE_PATH
    if not url.startswith(gate):
        return url
    role = url.removeprefix(gate)
    return lookup("tls", role) + role_config(
        role, "services.sso.oidc.backchannel_logout_path"
    )


def endpoint_findings(role: str, url: str) -> list[str]:
    """What keeps a back-channel logout URL off its role's upstream endpoint.

    Args:
        role: role directory name of the client fragment.
        url: the client's back-channel logout URL.
    """
    key, path = UPSTREAM_BACKCHANNEL_ENDPOINTS[role]
    findings = []
    if gated(role) and url != logout_gate_url(role):
        findings.append(f"{url} skips the logout gate {logout_gate_url(role)}")
    if not gated(role) and logout_receiver(url) != url:
        findings.append(f"{url} reaches the logout gate, which serves no {role}")
    if (
        logout_receiver(url)
        != canonical_origin(role, key or primary_domain_key(role)) + path
    ):
        findings.append(f"{url} does not reach the upstream endpoint {path}")
    return findings


def backchannel_findings(client: dict) -> list[str]:
    """What keeps one back-channel client from ending sessions safely and on every network.

    Args:
        client: a client representation that carries a back-channel logout URL.
    """
    attributes = client["attributes"]
    url = urlsplit(logout_receiver(attributes[BACKCHANNEL_LOGOUT_URL]))
    origin = f"{url.scheme}://{url.netloc}"
    siblings = onion_sibling(origin)
    post_logout = attributes.get("post.logout.redirect.uris", "").split("##")
    findings = []
    if client["frontchannelLogout"] is not False:
        findings.append("frontchannelLogout is not false")
    if client["serviceAccountsEnabled"] is not False:
        findings.append("serviceAccountsEnabled is not false")
    if attributes.get("backchannel.logout.session.required") != "true":
        findings.append("backchannel.logout.session.required is not 'true'")
    if client["webOrigins"] != siblings:
        findings.append(
            f"webOrigins {client['webOrigins']} are not the canonical origin and its siblings {siblings}"
        )
    findings.extend(
        f"no redirect URI on the network sibling {sibling}"
        for sibling in siblings
        if not any(uri.startswith(sibling + "/") for uri in client["redirectUris"])
    )
    findings.extend(
        f"no post-logout redirect URI on the network sibling {sibling}"
        for sibling in siblings
        if not any(uri.startswith(sibling + "/") for uri in post_logout)
    )
    return findings


def credential_findings(client: dict) -> list[str]:
    """What hands a per-app client a credential the realm did not hold before.

    Args:
        client: the per-app client's representation.
    """
    if client["publicClient"]:
        return ["the public client carries a secret"] if "secret" in client else []
    if client.get("secret") != CONTEXT["OIDC"]["CLIENT"]["SECRET"]:
        return ["the confidential client does not reuse the shared secret"]
    return []


def shared_client_findings(client: dict) -> list[str]:
    """What turns the shared client away from the front-channel sweep per network.

    Args:
        client: the shared client's representation.
    """
    attributes = client["attributes"]
    findings = []
    if BACKCHANNEL_LOGOUT_URL in attributes:
        findings.append("the shared client carries a back-channel logout URL")
    if client["frontchannelLogout"] is not True:
        findings.append("frontchannelLogout is not true")
    if (
        attributes.get("frontchannel.logout.url")
        != CONTEXT["KEYCLOAK_FRONTCHANNEL_LOGOUT_URL"]
    ):
        findings.append("the conductor is not the front-channel logout URL")
    if attributes.get("frontchannel.logout.session.required") != "true":
        findings.append("frontchannel.logout.session.required is not 'true'")
    return findings


def shared_client() -> dict:
    realm = json.loads(render([]))
    return next(c for c in realm["clients"] if c["clientId"] == SHARED_CLIENT_ID)


def foreign_app_scopes(role: str) -> set[str]:
    """The application scopes of the shared client that belong to other applications.

    Args:
        role: role directory name of the client fragment.
    """
    scopes = role_config("web-app-keycloak", "services.keycloak.scopes")
    own = scopes.get(role.removeprefix("web-app-"))
    return {scope for scope in scopes.values() if scope != own}


def claim_findings(client: dict, shared: dict, foreign_scopes: set[str]) -> list[str]:
    """What keeps a per-app client from handing its app the claims of the shared client.

    Args:
        client: the per-app client's representation.
        shared: the shared client's representation.
        foreign_scopes: the application scopes of the shared client that other
            applications read.
    """
    granted = {*client["defaultClientScopes"], *client["optionalClientScopes"]}
    findings = [
        f"default scope {scope} of the shared client is no default scope"
        for scope in shared["defaultClientScopes"]
        if scope != SERVICE_ACCOUNT_SCOPE and scope not in client["defaultClientScopes"]
    ]
    findings.extend(
        f"optional scope {scope} of the shared client is missing"
        for scope in shared["optionalClientScopes"]
        if scope not in foreign_scopes and scope not in granted
    )
    own_mappers = client.get("protocolMappers", [])
    findings.extend(
        f"protocol mapper {mapper['name']} of the shared client is missing"
        for mapper in shared.get("protocolMappers", [])
        if mapper not in own_mappers
    )
    return findings


def client_id_consumers() -> dict[str, str]:
    sources = {}
    for pattern in CLIENT_ID_CONSUMERS:
        for path in PROJECT_ROOT.glob(pattern):
            source = read_text(str(path))
            if CLIENT_ID_LOOKUP.search(source):
                sources[str(path.relative_to(PROJECT_ROOT))] = source
    return sources


def role_client_readers(role: str) -> dict[str, str]:
    """The files of one role that may read its client ids, its Keycloak fragment excluded.

    Args:
        role: role directory name.
    """
    return {
        str(path.relative_to(PROJECT_ROOT)): read_text(str(path))
        for pattern in CLIENT_ID_CONSUMERS
        for path in PROJECT_ROOT.glob(pattern.replace("*", role, 1))
        if path.parts[-3:] != KEYCLOAK_FRAGMENT
    }


def unread_client_keys(role: str, sources: dict[str, str]) -> list[str]:
    """Return the declared clients of a role that no file outside its fragment reads.

    Args:
        role: role directory name.
        sources: the role's files outside its Keycloak fragment, keyed by path.
    """
    read = {
        match.group("key")
        for source in sources.values()
        for match in CLIENT_KEY_READ.finditer(source)
    }
    return sorted(set(role_config(role, "services.sso.oidc.clients")) - read)


def shared_client_id_reads(sources: dict[str, str]) -> list[str]:
    """Return every read of the shared client id in a role's files.

    Args:
        sources: the role's files outside its Keycloak fragment, keyed by path.
    """
    return [
        f"{path}: {match.group(0)}"
        for path, source in sources.items()
        for match in SHARED_CLIENT_ID_READ.finditer(source)
    ]


def silent_client_fallbacks(sources: dict[str, str]) -> list[str]:
    """Return every per-app client id lookup that would not fail on a missing entry.

    Args:
        sources: role files keyed by their path.
    """
    return [
        f"{path}: {match.group(0)}"
        for path, source in sources.items()
        for match in CLIENT_ID_LOOKUP.finditer(source)
        if match.group("tail") == "," or match.group("fallback")
    ]


class TestBackchannelClients(unittest.TestCase):
    def setUp(self) -> None:
        self.clients = {
            template: render_fragment(template) for template in CLIENT_TEMPLATES
        }
        self.backchannel = [
            client
            for clients in self.clients.values()
            for client in clients
            if BACKCHANNEL_LOGOUT_URL in client["attributes"]
        ]

    def test_matrix_ships_a_backchannel_client(self) -> None:
        templates = {
            template.parts[-4]
            for template, clients in self.clients.items()
            if any(BACKCHANNEL_LOGOUT_URL in c["attributes"] for c in clients)
        }
        self.assertIn("web-app-matrix", templates)

    def test_every_backchannel_client_is_safe_and_reaches_every_network(self) -> None:
        self.assertTrue(self.backchannel)
        for client in self.backchannel:
            with self.subTest(client=client["clientId"]):
                self.assertEqual(backchannel_findings(client), [])

    def test_no_client_of_an_application_runs_a_service_account(self) -> None:
        for clients in self.clients.values():
            for client in clients:
                with self.subTest(client=client["clientId"]):
                    self.assertIs(client["serviceAccountsEnabled"], False)

    def test_a_backchannel_client_is_public_or_reuses_the_shared_secret(self) -> None:
        for client in self.backchannel:
            with self.subTest(client=client["clientId"]):
                self.assertEqual(credential_findings(client), [])

    def test_a_secret_on_a_public_client_or_a_new_secret_fails_the_check(
        self,
    ) -> None:
        self.assertEqual(
            credential_findings({"publicClient": True, "secret": "another"}),
            ["the public client carries a secret"],
        )
        self.assertEqual(
            credential_findings({"publicClient": False, "secret": "another"}),
            ["the confidential client does not reuse the shared secret"],
        )

    def test_every_backchannel_client_logs_out_on_its_upstream_endpoint(self) -> None:
        for template, clients in self.clients.items():
            role = template.parts[-4]
            for client in clients:
                if BACKCHANNEL_LOGOUT_URL not in client["attributes"]:
                    continue
                with self.subTest(role=role):
                    self.assertIn(role, UPSTREAM_BACKCHANNEL_ENDPOINTS)
                    self.assertEqual(
                        endpoint_findings(
                            role, client["attributes"][BACKCHANNEL_LOGOUT_URL]
                        ),
                        [],
                    )

    def test_every_gated_client_sends_its_logout_tokens_through_the_gate(
        self,
    ) -> None:
        gated_clients = {
            template.parts[-4]: client
            for template, clients in self.clients.items()
            for client in clients
            if BACKCHANNEL_LOGOUT_URL in client["attributes"]
            and gated(template.parts[-4])
        }
        self.assertIn(XWIKI, gated_clients)
        for role, client in gated_clients.items():
            with self.subTest(role=role):
                self.assertEqual(
                    client["clientId"],
                    role_config(role, "services.sso.oidc.clients.web"),
                )
                self.assertEqual(
                    client["attributes"][BACKCHANNEL_LOGOUT_URL], logout_gate_url(role)
                )

    def test_a_gated_role_signs_in_with_its_own_client_only(self) -> None:
        roles = [
            template.parts[-4]
            for template, clients in self.clients.items()
            if any(BACKCHANNEL_LOGOUT_URL in c["attributes"] for c in clients)
            and gated(template.parts[-4])
        ]
        self.assertIn(XWIKI, roles)
        for role in roles:
            with self.subTest(role=role):
                self.assertEqual(shared_client_id_reads(role_client_readers(role)), [])

    def test_a_gated_role_that_keeps_the_shared_client_id_is_caught(self) -> None:
        path = f"roles/web-app-x/{ROLE_FILE_VARS_MAIN}"
        sources = {path: 'X_ID: "{{ OIDC.CLIENT.ID }}"'}
        self.assertEqual(shared_client_id_reads(sources), [f"{path}: OIDC.CLIENT.ID"])

    def test_a_gated_client_that_skips_the_gate_fails_the_check(self) -> None:
        direct = canonical_origin(XWIKI) + UPSTREAM_BACKCHANNEL_ENDPOINTS[XWIKI][1]
        self.assertEqual(
            endpoint_findings(XWIKI, direct),
            [f"{direct} skips the logout gate {logout_gate_url(XWIKI)}"],
        )

    def test_a_gate_url_of_another_role_fails_the_check(self) -> None:
        foreign = logout_gate_url("web-app-matrix")
        self.assertEqual(len(endpoint_findings(XWIKI, foreign)), 2)

    def test_a_role_the_gate_does_not_serve_cannot_use_the_gate(self) -> None:
        self.assertFalse(gated(OPENCLOUD))
        self.assertIn(
            f"{logout_gate_url(OPENCLOUD)} reaches the logout gate, which serves no {OPENCLOUD}",
            endpoint_findings(OPENCLOUD, logout_gate_url(OPENCLOUD)),
        )

    def test_synapse_receives_logout_tokens_through_the_gate(self) -> None:
        (client,) = render_fragment(
            PROJECT_ROOT / "roles" / MATRIX / "templates/keycloak/clients.json.j2"
        )
        self.assertTrue(
            gated(MATRIX),
            "Synapse 1.165.0 answers a logout token whose kid is not in the JWKS "
            "with a 500: _verify_jwt lets authlib's ValueError past the JoseError "
            "handler of handle_backchannel_logout",
        )
        self.assertEqual(
            client["attributes"][BACKCHANNEL_LOGOUT_URL], logout_gate_url(MATRIX)
        )
        self.assertEqual(
            primary_domain_key(MATRIX),
            UPSTREAM_BACKCHANNEL_ENDPOINTS[MATRIX][0],
            "the gate forwards to lookup('tls', ..., 'url.origin'), the first "
            "canonical domain, which must stay the Synapse one",
        )

    def test_a_gated_client_with_the_origins_of_the_gate_fails_the_check(
        self,
    ) -> None:
        (client,) = render_fragment(
            PROJECT_ROOT / "roles" / XWIKI / "templates/keycloak/clients.json.j2"
        )
        gate_origins = onion_sibling(canonical_origin(LOGOUT_GATE))
        siblings = onion_sibling(canonical_origin(XWIKI))
        self.assertEqual(
            backchannel_findings({**client, "webOrigins": gate_origins}),
            [
                f"webOrigins {gate_origins} are not the canonical origin and its siblings {siblings}"
            ],
        )

    def test_the_opencloud_web_client_is_public(self) -> None:
        (client,) = render_fragment(
            PROJECT_ROOT / "roles" / OPENCLOUD / "templates/keycloak/clients.json.j2"
        )
        self.assertEqual(
            client["clientId"], role_config(OPENCLOUD, "services.sso.oidc.clients.web")
        )
        self.assertIs(
            client["publicClient"],
            True,
            "OpenCloud Web signs in from the browser and cannot keep a secret",
        )

    def test_the_openpost_client_logs_out_at_its_instance_provider_directly(
        self,
    ) -> None:
        (client,) = render_fragment(
            PROJECT_ROOT / "roles" / OPENPOST / "templates/keycloak/clients.json.j2"
        )
        self.assertFalse(
            gated(OPENPOST),
            "OpenPost v7.42.2 checks a logout token with go-oidc v3.21.0 VerifyLogout "
            "(signature, iss, aud, exp, jti, events, no nonce) and answers every "
            "failure with a 400, so its receiver needs no logout gate",
        )
        self.assertEqual(
            client["attributes"][BACKCHANNEL_LOGOUT_URL],
            canonical_origin(OPENPOST) + UPSTREAM_BACKCHANNEL_ENDPOINTS[OPENPOST][1],
        )
        self.assertIs(
            client["publicClient"],
            False,
            "OpenPost authenticates its code exchange with OPENPOST_OIDC_CLIENT_SECRET",
        )
        self.assertEqual(credential_findings(client), [])
        self.assertEqual(
            shared_client_id_reads(role_client_readers(OPENPOST)),
            [],
            "OpenPost must sign in through openpost-web, or no logout token names its sessions",
        )

    def test_every_backchannel_client_hands_its_app_the_claims_of_the_shared_client(
        self,
    ) -> None:
        shared = shared_client()
        for template, clients in self.clients.items():
            for client in clients:
                if BACKCHANNEL_LOGOUT_URL not in client["attributes"]:
                    continue
                with self.subTest(client=client["clientId"]):
                    self.assertEqual(
                        claim_findings(
                            client, shared, foreign_app_scopes(template.parts[-4])
                        ),
                        [],
                    )

    def test_a_client_without_the_group_claim_scope_fails_the_claims_check(
        self,
    ) -> None:
        group_scope = CONTEXT["KEYCLOAK_RBAC_GROUP_CLAIM"]
        client = {
            **self.backchannel[0],
            "defaultClientScopes": [
                scope
                for scope in self.backchannel[0]["defaultClientScopes"]
                if scope != group_scope
            ],
        }
        self.assertEqual(
            claim_findings(client, shared_client(), foreign_app_scopes("web-app-x")),
            [f"default scope {group_scope} of the shared client is no default scope"],
        )

    def test_a_client_without_its_app_scope_fails_the_claims_check(self) -> None:
        nextcloud = role_config(
            "web-app-keycloak", "services.keycloak.scopes.nextcloud"
        )
        self.assertEqual(
            claim_findings(
                self.backchannel[0],
                shared_client(),
                foreign_app_scopes("web-app-nextcloud"),
            ),
            [f"optional scope {nextcloud} of the shared client is missing"],
        )

    def test_a_client_without_a_mapper_of_the_shared_client_fails_the_claims_check(
        self,
    ) -> None:
        mapper = {
            "name": "username",
            "protocolMapper": "oidc-usermodel-property-mapper",
        }
        shared = {**shared_client(), "protocolMappers": [mapper]}
        self.assertEqual(
            claim_findings(
                self.backchannel[0], shared, foreign_app_scopes("web-app-x")
            ),
            ["protocol mapper username of the shared client is missing"],
        )

    def test_a_frontchannel_client_fails_the_backchannel_check(self) -> None:
        client = {
            **self.backchannel[0],
            "frontchannelLogout": True,
            "serviceAccountsEnabled": True,
        }
        self.assertEqual(len(backchannel_findings(client)), 2)

    def test_a_client_that_forgets_the_onion_sibling_fails_the_check(self) -> None:
        canonical = self.backchannel[0]["webOrigins"][0]
        client = {
            **self.backchannel[0],
            "webOrigins": [canonical],
            "attributes": {
                **self.backchannel[0]["attributes"],
                "post.logout.redirect.uris": canonical + "/*",
            },
        }
        siblings = onion_sibling(canonical)
        self.assertEqual(
            backchannel_findings(client),
            [
                f"webOrigins {[canonical]} are not the canonical origin and its siblings {siblings}",
                f"no post-logout redirect URI on the network sibling {siblings[1]}",
            ],
        )


class TestOpenTalkFrontendClient(unittest.TestCase):
    def setUp(self) -> None:
        upserts = opentalk_client_upserts()
        self.frontend = upserts[True]
        self.controller = upserts[False]["keycloak_kcadm_update"]["desired"]

    def test_the_frontend_client_logs_out_on_the_controller(self) -> None:
        desired = self.frontend["keycloak_kcadm_update"]["desired"]
        key, path = UPSTREAM_BACKCHANNEL_ENDPOINTS[OPENTALK]
        self.assertEqual(
            render_task_value(
                self.frontend, desired["attributes"][BACKCHANNEL_LOGOUT_URL]
            ),
            canonical_origin(OPENTALK, key) + path,
        )
        self.assertEqual(
            desired["attributes"]["backchannel.logout.session.required"], "true"
        )
        self.assertIs(desired["frontchannelLogout"], False)
        self.assertIs(desired["serviceAccountsEnabled"], False)

    def test_the_controller_client_receives_no_logout_tokens(self) -> None:
        self.assertNotIn(BACKCHANNEL_LOGOUT_URL, self.controller["attributes"])


class TestSharedClientStaysOnTheSweep(unittest.TestCase):
    def test_the_shared_client_keeps_the_sweep_per_network(self) -> None:
        self.assertEqual(shared_client_findings(shared_client()), [])

    def test_a_backchannel_url_on_the_shared_client_fails_the_check(self) -> None:
        client = shared_client()
        client["attributes"][BACKCHANNEL_LOGOUT_URL] = "https://shared.example.com/"
        self.assertEqual(
            shared_client_findings(client),
            ["the shared client carries a back-channel logout URL"],
        )


class TestAppsDecidedWithoutBackchannelUrl(unittest.TestCase):
    def test_nextcloud_stays_on_the_shared_client(self) -> None:
        for plugin in ("oidc_login", "sociallogin", ""):
            with (
                self.subTest(plugin=plugin),
                mock.patch.dict(globals(), {"SSO_OIDC_PLUGIN": plugin}),
            ):
                self.assertEqual(
                    role_config(NEXTCLOUD, "services.sso.oidc.clients"), {}
                )
                self.assertEqual(declared_client_apps([NEXTCLOUD]), [])

    def test_user_oidc_brings_the_own_nextcloud_client(self) -> None:
        self.assertEqual(declared_client_apps([NEXTCLOUD]), [NEXTCLOUD])
        (client,) = render_fragment(
            PROJECT_ROOT / "roles" / NEXTCLOUD / "templates/keycloak/clients.json.j2"
        )
        self.assertEqual(
            client["clientId"],
            role_config(NEXTCLOUD, "services.sso.oidc.clients.user_oidc"),
        )
        self.assertEqual(
            client["attributes"][BACKCHANNEL_LOGOUT_URL],
            canonical_origin(NEXTCLOUD) + USER_OIDC_BACKCHANNEL_PATH + "keycloak",
            "user_oidc receives logout tokens per provider identifier",
        )
        self.assertEqual(backchannel_findings(client), [])
        self.assertEqual(
            claim_findings(client, shared_client(), foreign_app_scopes(NEXTCLOUD)),
            [],
        )

    def test_the_default_plugins_render_the_realm_byte_identically(self) -> None:
        without_nextcloud = render([])
        for plugin in ("oidc_login", "sociallogin"):
            with (
                self.subTest(plugin=plugin),
                mock.patch.dict(globals(), {"SSO_OIDC_PLUGIN": plugin}),
            ):
                self.assertEqual(declared_client_role_grants([NEXTCLOUD]), [])
                self.assertEqual(
                    render([], client_apps=declared_client_apps([NEXTCLOUD])),
                    without_nextcloud,
                )

    def test_the_stalwart_clients_carry_no_backchannel_logout_url(self) -> None:
        clients = render_fragment(
            PROJECT_ROOT
            / "roles"
            / "web-app-stalwart"
            / "templates"
            / "keycloak"
            / "clients.json.j2"
        )
        self.assertEqual(
            sorted(
                role_config("web-app-stalwart", f"services.sso.oidc.clients.{name}")
                for name in ("webui", "webmail")
            ),
            sorted(client["clientId"] for client in clients),
        )
        for client in clients:
            with self.subTest(client=client["clientId"]):
                self.assertIs(client["frontchannelLogout"], False)
                self.assertNotIn(BACKCHANNEL_LOGOUT_URL, client["attributes"])


class TestNextcloudAdminClientRole(unittest.TestCase):
    def setUp(self) -> None:
        (self.client,) = render_fragment(
            PROJECT_ROOT / "roles" / NEXTCLOUD / "templates/keycloak/clients.json.j2"
        )
        self.group_mapper = group_claim_mapper()

    def test_the_rbac_administrator_group_gets_the_admin_client_role(self) -> None:
        self.assertEqual(
            declared_client_role_grants([NEXTCLOUD]),
            [
                {
                    "client_id": self.client["clientId"],
                    "role": NEXTCLOUD_ADMIN_GROUP,
                    "group_path": f"/{RBAC_GROUP_ROOT}/{NEXTCLOUD}/administrator",
                }
            ],
        )

    def test_the_grant_targets_the_group_sociallogin_maps_to_admin(self) -> None:
        sociallogin = read_text(
            str(PROJECT_ROOT / "roles" / NEXTCLOUD / "meta/addons/sociallogin.yml")
        )
        self.assertIn(
            "'/' ~ lookup('rbac_group_path', application_id=application_id, "
            "role='administrator'): 'admin'",
            sociallogin,
        )
        (grant,) = declared_client_role_grants([NEXTCLOUD])
        self.assertEqual(grant["role"], NEXTCLOUD_ADMIN_GROUP)

    def test_the_admin_role_joins_the_group_claim_instead_of_replacing_it(
        self,
    ) -> None:
        self.assertEqual(self.group_mapper["config"]["multivalued"], "true")
        self.assertEqual(client_role_claim_findings(self.client, self.group_mapper), [])

    def test_a_single_valued_role_mapper_fails_the_claim_check(self) -> None:
        client = json.loads(json.dumps(self.client))
        client["protocolMappers"][0]["config"]["multivalued"] = "false"
        self.assertEqual(
            client_role_claim_findings(client, self.group_mapper),
            ["the mapper is not multivalued and replaces the group paths"],
        )

    def test_a_role_mapper_on_another_claim_or_client_fails_the_check(self) -> None:
        client = json.loads(json.dumps(self.client))
        config = client["protocolMappers"][0]["config"]
        config["claim.name"] = "nextcloud_roles"
        config["usermodel.clientRoleMapping.clientId"] = SHARED_CLIENT_ID
        config["usermodel.clientRoleMapping.rolePrefix"] = "nextcloud-"
        config["userinfo.token.claim"] = "false"
        self.assertEqual(
            client_role_claim_findings(client, self.group_mapper),
            [
                "the mapper reads the roles of another client",
                "a role prefix renames the Nextcloud group",
                "the mapper writes another claim than the group claim",
                "userinfo.token.claim differs from the group claim",
            ],
        )

    def test_a_client_without_the_role_mapper_fails_the_check(self) -> None:
        client = {**self.client, "protocolMappers": []}
        self.assertEqual(
            client_role_claim_findings(client, self.group_mapper),
            ["0 client role mappers instead of one"],
        )

    def test_a_role_of_an_undeclared_client_grants_nothing(self) -> None:
        module = oidc_clients_filters()
        apps = {
            "web-app-x": {
                "services": {
                    "sso": {
                        "oidc": {
                            "clients": {"webui": "x-webui"},
                            "client_roles": {
                                "webmail": {"admin": "administrator"},
                                "webui": "administrator",
                            },
                        }
                    }
                }
            }
        }
        self.assertEqual(
            module.kc_declared_client_role_grants(apps, ["web-app-x"], "roles"), []
        )
        self.assertEqual(module.kc_declared_client_role_grants(apps, [], "roles"), [])


class TestPerAppClientIdsFailLoudly(unittest.TestCase):
    def setUp(self) -> None:
        self.consumers = client_id_consumers()

    def test_the_scan_sees_the_synapse_client_id(self) -> None:  # nocheck: test.text-presence -- non-vacuity check of the repository-wide client id scan  # fmt: skip
        self.assertIn(f"roles/web-app-matrix/{ROLE_FILE_VARS_MAIN}", self.consumers)
        self.assertIn(
            "roles/web-app-matrix/templates/keycloak/clients.json.j2", self.consumers
        )

    def test_no_per_app_client_id_falls_back_to_another_client(self) -> None:
        self.assertEqual(silent_client_fallbacks(self.consumers), [])

    def test_every_declared_client_is_read_outside_its_fragment(self) -> None:
        for template in CLIENT_TEMPLATES:
            role = template.parts[-4]
            with self.subTest(role=role):
                self.assertEqual(
                    unread_client_keys(role, role_client_readers(role)), []
                )

    def test_a_declared_client_its_app_never_reads_is_caught(self) -> None:
        self.assertEqual(
            unread_client_keys(
                OPENCLOUD,
                {"templates/env.j2": "WEB_OIDC_CLIENT_ID={{ OIDC.CLIENT.ID }}"},
            ),
            ["web"],
        )

    def test_a_lookup_with_a_fallback_is_caught(self) -> None:
        sources = {
            "default-argument": "{{ lookup('config', application_id, 'services.sso.oidc.clients.synapse', OIDC.CLIENT.ID) }}",
            "default-filter": "{{ lookup('config', application_id, 'services.sso.oidc.clients.synapse') | default(OIDC.CLIENT.ID) }}",
            "strict": "{{ lookup('config', application_id, 'services.sso.oidc.clients.synapse') }}",
        }
        self.assertEqual(
            [finding.split(":")[0] for finding in silent_client_fallbacks(sources)],
            ["default-argument", "default-filter"],
        )


if __name__ == "__main__":
    unittest.main()
