from __future__ import annotations

import importlib.util
import re
import unittest

from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
    select_autoescape,
)

from plugins.filter.logout_domains import FilterModule as LogoutDomainsFilter
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TEMPL_COMPOSE

APP = "web-svc-logout"
ROLE = PROJECT_ROOT / "roles" / APP
KEYCLOAK = PROJECT_ROOT / "roles" / "web-app-keycloak"
ENV_TEMPLATES = (
    ROLE / "templates" / "env.j2",
    PROJECT_ROOT / "roles" / "sys-svc-container" / "templates" / "env.j2",
)
CONTAINER_TEMPLATES = (*ENV_TEMPLATES, ROLE / ROLE_FILE_TEMPL_COMPOSE)
VHOST_TEMPLATES = (
    ROLE / "templates" / "logout-proxy.conf.j2",
    ROLE / "templates" / "proxy.conf.j2",
)
SERVED_LOCATIONS = ["= /logout", "^~ /backchannel/"]
BASIC_ENV_KEYS = {"LOGOUT_PORT", "TZ", "LANG"}
GATE_ENV_KEYS = {"LOGOUT_GATE_ISSUER", "LOGOUT_GATE_JWKS_URL", "LOGOUT_GATE_CLIENTS"}
GATE_KEYCLOAK_VALUES = {"OIDC.CLIENT.ISSUER_URL", "OIDC.CLIENT.CERTS"}
KEYCLOAK_REFERENCE = re.compile(
    r"\bOIDC(?:\.[A-Z_]+)+|\bKEYCLOAK_[A-Z0-9_]+|web-app-keycloak"
)
CREDENTIAL = re.compile(r"secrets\.credentials\.([a-z0-9_]+)")
ENV_KEY = re.compile(r"(?m)^([A-Z][A-Z0-9_]*)=")
LOCATION = re.compile(r"(?m)^\s*location\s+([^{]+?)\s*\{")
GATE_LOCATION = re.compile(r"(?ms)^location \^~ /backchannel/ \{(?P<body>.*?)^\}")


def _load_filter(path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OIDC_CLIENTS = _load_filter(
    KEYCLOAK / "filter_plugins" / "oidc_clients.py", "logout_oidc_clients"
)
LOGOUT_DOMAINS = LogoutDomainsFilter().filters()["logout_domains"]


def services(role) -> dict:
    return load_yaml_any(str(role / ROLE_FILE_META_SERVICES))


def env_keys(sources: list[str]) -> set[str]:
    """Return every key the conductor's env file can hold.

    Args:
        sources: the raw text of the env template and of every template it includes.
    """
    return {key for source in sources for key in ENV_KEY.findall(source)}


def keycloak_references(sources: list[str]) -> set[str]:
    """Return every Keycloak value the conductor's container templates read.

    Args:
        sources: the raw text of the container's env and compose templates.
    """
    return {ref for source in sources for ref in KEYCLOAK_REFERENCE.findall(source)}


def credentials_read(sources: list[str]) -> set[str]:
    """Return the names of the credentials the conductor's env file reads.

    Args:
        sources: the raw text of the env template and of every template it includes.
    """
    return {name for source in sources for name in CREDENTIAL.findall(source)}


def served_locations(sources: list[str]) -> list[str]:
    """Return the nginx locations the conductor's vhost templates declare.

    Args:
        sources: the raw text of the role's vhost templates.
    """
    return [match.strip() for source in sources for match in LOCATION.findall(source)]


def rendered_gate_vhost() -> str:
    """
    Returns:
        The extra configuration the conductor's proxy template hands the
        generic vhost, rendered with stubbed lookups and includes.
    """
    stubs = {
        "roles/sys-svc-proxy/templates/vhost/basic.conf.j2": (
            "{{ webserver_extra_configuration }}"
        ),
        "roles/sys-svc-proxy/templates/headers/forwarded_base.conf.j2": "",
        "roles/sys-svc-proxy/templates/headers/identity_request_strips.conf.j2": "",
        "roles/sys-svc-proxy/templates/headers/upstream_strips.conf.j2": "",
    }
    answers = {
        "config": 8080,
        "asset": "/bootstrap.js",
        "proxy_pass": "proxy_pass http://127.0.0.1:8080;",
    }
    env = Environment(
        loader=ChoiceLoader([DictLoader(stubs), FileSystemLoader(str(PROJECT_ROOT))]),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["network_of"] = lambda _domain: "clearnet"
    env.filters["labelled"] = lambda value, _label, _separator: value
    env.globals["lookup"] = lambda name, *_terms, **_options: answers[name]
    return env.get_template(str(VHOST_TEMPLATES[1].relative_to(PROJECT_ROOT))).render(
        application_id=APP,
        domain="logout.example.test",
        front_proxy_domain="logout.example.test",
        LOGOUT_INSTANCES=[{"network": "clearnet", "label": ""}],
        LOGOUT_CONDUCTOR_BOOTSTRAP_UPSTREAM="/bootstrap-upstream.js",
        proxy_internal_port=80,
    )


class TestLogoutConductorOwnsNoKeycloakClient(unittest.TestCase):
    def test_the_role_declares_no_sso_service(self) -> None:
        self.assertNotIn("sso", services(ROLE))

    def test_keycloak_imports_no_client_of_the_role(self) -> None:
        applications = {APP: {"services": services(ROLE)}}
        self.assertEqual(OIDC_CLIENTS.kc_declared_client_apps(applications, [APP]), [])

    def test_a_declared_client_would_be_imported(self) -> None:
        applications = {
            APP: {"services": {"sso": {"oidc": {"clients": {"logout": APP}}}}}
        }
        self.assertEqual(
            OIDC_CLIENTS.kc_declared_client_apps(applications, [APP]), [APP]
        )


class TestLogoutConductorHoldsNoKeycloakSecret(unittest.TestCase):
    def setUp(self) -> None:
        self.sources = [read_text(str(path)) for path in ENV_TEMPLATES]

    def test_the_env_file_holds_the_port_the_basics_and_the_gate(self) -> None:  # nocheck: test.text-presence -- trust-boundary allowlist: the exact set of env keys across the env templates  # fmt: skip
        self.assertEqual(env_keys(self.sources), BASIC_ENV_KEYS | GATE_ENV_KEYS)

    def test_the_env_file_reads_only_the_gate_keys_as_credentials(self) -> None:  # nocheck: test.text-presence -- trust-boundary allowlist: the exact set of credentials the env templates read  # fmt: skip
        self.assertEqual(credentials_read(self.sources), {"logout_gate_key"})

    def test_the_keycloak_client_secret_in_the_env_file_is_caught(self) -> None:
        leaked = [*self.sources, "LOGOUT_GATE_SECRET={{ OIDC.CLIENT.SECRET }}"]
        self.assertEqual(
            keycloak_references(leaked) - GATE_KEYCLOAK_VALUES, {"OIDC.CLIENT.SECRET"}
        )

    def test_a_client_secret_credential_in_the_env_file_is_caught(self) -> None:
        leaked = [
            *self.sources,
            "LOGOUT_GATE_SECRET={{ lookup('config', app, 'secrets.credentials.client_secret') }}",
        ]
        self.assertEqual(credentials_read(leaked), {"logout_gate_key", "client_secret"})


class TestLogoutConductorCallsKeycloakOnlyForItsPublicKeys(unittest.TestCase):
    def setUp(self) -> None:
        self.sources = [read_text(str(path)) for path in CONTAINER_TEMPLATES]

    def test_the_container_reads_only_the_issuer_and_jwks_of_keycloak(self) -> None:  # nocheck: test.text-presence -- trust-boundary allowlist: the exact set of Keycloak values the container templates read  # fmt: skip
        self.assertEqual(keycloak_references(self.sources), GATE_KEYCLOAK_VALUES)

    def test_a_token_endpoint_call_is_caught(self) -> None:
        calling = [*self.sources, "LOGOUT_GATE_TOKEN_URL={{ OIDC.CLIENT.TOKEN_URL }}"]
        self.assertEqual(
            keycloak_references(calling) - GATE_KEYCLOAK_VALUES,
            {"OIDC.CLIENT.TOKEN_URL"},
        )

    def test_an_admin_api_call_is_caught(self) -> None:
        calling = [
            *self.sources,
            "LOGOUT_GATE_ADMIN_URL={{ lookup('tls', 'web-app-keycloak', 'url.origin') }}/admin",
        ]
        self.assertEqual(
            keycloak_references(calling) - GATE_KEYCLOAK_VALUES, {"web-app-keycloak"}
        )


class TestLogoutConductorServesOnlyTheGateAsNewRoute(unittest.TestCase):
    def setUp(self) -> None:
        self.sources = [read_text(str(path)) for path in VHOST_TEMPLATES]

    def test_the_vhost_serves_the_logout_endpoint_and_the_gate_only(self) -> None:  # nocheck: test.text-presence -- trust-boundary allowlist: the exact list of locations the vhost templates declare  # fmt: skip
        self.assertEqual(served_locations(self.sources), SERVED_LOCATIONS)

    def test_the_gate_admits_post_only(self) -> None:
        gate = GATE_LOCATION.search(rendered_gate_vhost())
        self.assertIsNotNone(gate)
        self.assertRegex(gate.group("body"), r"limit_except POST \{\s*deny all;\s*\}")

    def test_a_second_new_route_is_caught(self) -> None:
        widened = [*self.sources, "location = /everywhere {\n}\n"]
        self.assertEqual(
            served_locations(widened), [*SERVED_LOCATIONS, "= /everywhere"]
        )


class TestLogoutConductorSweepsNoKeycloakOrigin(unittest.TestCase):
    def setUp(self) -> None:
        self.applications = {
            "web-app-keycloak": {
                "domains": {"canonical": ["auth.example.test"]},
                "services": services(KEYCLOAK),
            },
            "web-app-matrix": {
                "domains": {"canonical": ["matrix.example.test"]},
                "services": {"logout": {"enabled": True}},
            },
        }

    def test_keycloak_keeps_the_logout_service_off(self) -> None:
        self.assertIs(services(KEYCLOAK)["logout"]["enabled"], False)

    def test_the_sweep_never_targets_keycloak(self) -> None:
        self.assertEqual(
            LOGOUT_DOMAINS(self.applications, list(self.applications)),
            ["matrix.example.test"],
        )

    def test_keycloak_with_the_logout_service_on_would_be_swept(self) -> None:  # nocheck: test.text-presence -- runs the logout_domains filter on planted applications  # fmt: skip
        self.applications["web-app-keycloak"]["services"] = {
            "logout": {"enabled": True}
        }
        self.assertIn(
            "auth.example.test",
            LOGOUT_DOMAINS(self.applications, list(self.applications)),
        )


if __name__ == "__main__":
    unittest.main()
