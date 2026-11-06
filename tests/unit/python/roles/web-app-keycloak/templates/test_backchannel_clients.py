from __future__ import annotations

import json
import re
import unittest
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

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
)
CLIENT_ID_LOOKUP = re.compile(
    r"lookup\(\s*'config'\s*,\s*[^,()]+,\s*'services\.sso\.oidc\.clients\.\w+'\s*"
    r"(?P<tail>[,)])(?P<fallback>\s*\|\s*default\b)?"
)


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
        node = node[key]
    return node


def canonical_origin(app: str, key: str = "") -> str:
    """The clearnet origin the stub serves an application, or one canonical of it.

    Args:
        app: application id.
        key: named canonical domain, empty for the primary one.
    """
    return f"https://{key + '.' if key else ''}{app}.example.com"


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
    if name == "config":
        return role_config(*args)
    if name == "canonical_url":
        return canonical_origin(*args)
    if name == "tls":
        return canonical_origin(args[0])
    if name == "network_urls":
        return onion_sibling(args[0])
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
    env.filters["regex_replace"] = lambda value, pattern, repl="": re.sub(
        pattern, repl, str(value)
    )
    source = env.get_template(str(template.relative_to(PROJECT_ROOT))).render(
        lookup=lookup, **CONTEXT
    )
    return json.loads(f"[{source}]")


def backchannel_findings(client: dict) -> list[str]:
    """What keeps one back-channel client from ending sessions safely and on every network.

    Args:
        client: a client representation that carries a back-channel logout URL.
    """
    attributes = client["attributes"]
    url = urlsplit(attributes[BACKCHANNEL_LOGOUT_URL])
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

    def test_a_confidential_client_reuses_the_shared_secret(self) -> None:
        for client in self.backchannel:
            with self.subTest(client=client["clientId"]):
                self.assertFalse(client["publicClient"])
                self.assertEqual(client["secret"], CONTEXT["OIDC"]["CLIENT"]["SECRET"])

    def test_the_matrix_client_logs_out_on_the_synapse_origin(self) -> None:
        client = next(
            c
            for clients in self.clients.values()
            for c in clients
            if c["clientId"]
            == role_config("web-app-matrix", "services.sso.oidc.clients.synapse")
        )
        self.assertEqual(
            client["attributes"][BACKCHANNEL_LOGOUT_URL],
            canonical_origin("web-app-matrix", "synapse")
            + "/_synapse/client/oidc/backchannel_logout",
            "Synapse receives logout tokens on this path of its own origin",
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
        role = PROJECT_ROOT / "roles" / "web-app-nextcloud"
        services = load_yaml_any(str(role / ROLE_FILE_META_SERVICES))
        self.assertNotIn("clients", services["sso"]["oidc"])
        self.assertFalse((role / "templates" / "keycloak" / "clients.json.j2").exists())

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


class TestPerAppClientIdsFailLoudly(unittest.TestCase):
    def setUp(self) -> None:
        self.consumers = client_id_consumers()

    def test_the_scan_sees_the_synapse_client_id(self) -> None:
        self.assertIn(f"roles/web-app-matrix/{ROLE_FILE_VARS_MAIN}", self.consumers)
        self.assertIn(
            "roles/web-app-matrix/templates/keycloak/clients.json.j2", self.consumers
        )

    def test_no_per_app_client_id_falls_back_to_another_client(self) -> None:
        self.assertEqual(silent_client_fallbacks(self.consumers), [])

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
