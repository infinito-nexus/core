from __future__ import annotations

import importlib.util
import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

APP = "web-svc-logout"
ROLE = PROJECT_ROOT / "roles" / APP
KEYCLOAK = PROJECT_ROOT / "roles" / "web-app-keycloak"
ENV_TEMPLATES = (
    ROLE / "templates" / "env.j2",
    PROJECT_ROOT / "roles" / "sys-svc-container" / "templates" / "env.j2",
)
VHOST_TEMPLATES = (
    ROLE / "templates" / "logout-proxy.conf.j2",
    ROLE / "templates" / "proxy.conf.j2",
)
SERVED_LOCATIONS = ["= /logout"]
KEYCLOAK_COUPLING = re.compile(r"KEYCLOAK|OIDC|SECRET|CLIENT|REALM|TOKEN")
ENV_KEY = re.compile(r"(?m)^([A-Z][A-Z0-9_]*)=")
LOCATION = re.compile(r"(?m)^\s*location\s+([^{]+?)\s*\{")


def _load_filter(path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OIDC_CLIENTS = _load_filter(
    KEYCLOAK / "filter_plugins" / "oidc_clients.py", "logout_oidc_clients"
)
LOGOUT_DOMAINS = (
    _load_filter(ROLE / "filter_plugins" / "domain_filters.py", "logout_domain_filters")
    .FilterModule()
    .filters()["logout_domains"]
)


def services(role) -> dict:
    return load_yaml_any(str(role / ROLE_FILE_META_SERVICES))


def env_keys(sources: list[str]) -> set[str]:
    """Return every key the conductor's env file can hold.

    Args:
        sources: the raw text of the env template and of every template it includes.
    """
    return {key for source in sources for key in ENV_KEY.findall(source)}


def keycloak_coupled(keys: set[str]) -> list[str]:
    """Return the env keys that would tie the conductor to Keycloak.

    Args:
        keys: the env keys of the conductor.
    """
    return sorted(key for key in keys if KEYCLOAK_COUPLING.search(key))


def served_locations(sources: list[str]) -> list[str]:
    """Return the nginx locations the conductor's vhost templates declare.

    Args:
        sources: the raw text of the role's vhost templates.
    """
    return [match.strip() for source in sources for match in LOCATION.findall(source)]


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
        self.keys = env_keys([read_text(str(path)) for path in ENV_TEMPLATES])

    def test_the_env_file_holds_only_the_port_and_the_container_basics(self) -> None:
        self.assertEqual(self.keys, {"LOGOUT_PORT", "TZ", "LANG"})

    def test_no_env_key_ties_the_conductor_to_keycloak(self) -> None:
        self.assertEqual(keycloak_coupled(self.keys), [])

    def test_a_client_secret_in_the_env_file_is_caught(self) -> None:
        self.assertEqual(
            keycloak_coupled(self.keys | {"LOGOUT_EVERYWHERE_CLIENT_SECRET"}),
            ["LOGOUT_EVERYWHERE_CLIENT_SECRET"],
        )


class TestLogoutConductorServesNoNewRoute(unittest.TestCase):
    def setUp(self) -> None:
        self.locations = served_locations(
            [read_text(str(path)) for path in VHOST_TEMPLATES]
        )

    def test_the_vhost_serves_only_the_logout_endpoint(self) -> None:
        self.assertEqual(self.locations, SERVED_LOCATIONS)

    def test_an_everywhere_route_is_caught(self) -> None:
        source = read_text(str(VHOST_TEMPLATES[0])) + "\nlocation = /everywhere {\n}\n"
        self.assertEqual(
            served_locations([source]), [*SERVED_LOCATIONS, "= /everywhere"]
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

    def test_keycloak_with_the_logout_service_on_would_be_swept(self) -> None:
        self.applications["web-app-keycloak"]["services"] = {
            "logout": {"enabled": True}
        }
        self.assertIn(
            "auth.example.test",
            LOGOUT_DOMAINS(self.applications, list(self.applications)),
        )


if __name__ == "__main__":
    unittest.main()
