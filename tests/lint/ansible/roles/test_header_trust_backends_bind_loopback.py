"""Lint: header-trust backends publish their ports on DOCKER_BIND_HOST only."""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.header_trust import header_trust_roles
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TEMPL_COMPOSE

ROLES_DIR = PROJECT_ROOT / "roles"
SSO_SIDECAR = ROLES_DIR / "web-app-keycloak/templates/sso_proxy/container.yml.j2"
GENERAL_VARS = PROJECT_ROOT / "group_vars/all/00_general.yml"
OUTER_COMPOSE = PROJECT_ROOT / "compose.yml"

_CALL = re.compile(r"lookup\(\s*'container_ports'\s*,(.*?)\)\s*(?:\||\}\})", re.DOTALL)
_LIST_TERM = re.compile(r"\[([^\[\]]*)\]")
_DICT_TERM = re.compile(r"\{([^{}]*)\}")
_DICT_IP = re.compile(r"""['"]ip['"]\s*:\s*DOCKER_BIND_HOST\b""")
_OUTER_PORT = re.compile(r'"\$\{INFINITO_BIND_IP[^}]*\}:(\d+)(?:-(\d+))?:')
_PRODUCTION_BIND = re.compile(
    r"""^DOCKER_BIND_HOST:\s*"\{\{\s*'0\.0\.0\.0'\s+if\s+DOCKER_IN_CONTAINER\s*\|\s*bool\s+else\s+'127\.0\.0\.1'\s*\}\}"\s""",
    re.MULTILINE,
)


def _roles() -> list[str]:
    return sorted(header_trust_roles(ROLES_DIR))


def _unbound_terms(text: str) -> list[str]:
    """Returns every container_ports term that publishes without DOCKER_BIND_HOST."""
    unbound: list[str] = []
    for args in _CALL.findall(text):
        for term in _LIST_TERM.findall(args):
            parts = [part.strip() for part in term.split(",")]
            if len(parts) != 3 or parts[2] != "DOCKER_BIND_HOST":
                unbound.append(f"[{term.strip()}]")
        unbound.extend(
            f"{{{term.strip()}}}"
            for term in _DICT_TERM.findall(args)
            if not _DICT_IP.search(term)
        )
    return unbound


def _local_ports(services: object) -> set[int]:
    """Returns every integer under a ``ports.local`` mapping of a services file."""
    found: set[int] = set()
    stack = [services]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        ports = node.get("ports")
        if isinstance(ports, dict) and isinstance(ports.get("local"), dict):
            found.update(
                value for value in ports["local"].values() if isinstance(value, int)
            )
        stack.extend(node.values())
    return found


def _outer_published_ports() -> set[int]:
    published: set[int] = set()
    for start, end in _OUTER_PORT.findall(read_text(str(OUTER_COMPOSE))):
        published.update(range(int(start), int(end or start) + 1))
    return published


class TestHeaderTrustBackendsBindLoopback(unittest.TestCase):
    def test_header_trust_roles_are_detected(self) -> None:
        self.assertTrue(
            _roles(), "no header-trust role detected; the lint would pass vacuously"
        )

    def test_every_published_port_carries_docker_bind_host(self) -> None:
        findings: list[str] = []
        for role in _roles():
            compose = ROLES_DIR / role / ROLE_FILE_TEMPL_COMPOSE
            text = read_text(str(compose))
            if not _CALL.search(text):
                findings.append(
                    f"{role}: {ROLE_FILE_TEMPL_COMPOSE} has no container_ports call"
                )
                continue
            findings.extend(f"{role}: {term}" for term in _unbound_terms(text))
        self.assertEqual(
            [],
            findings,
            "header-trust backends must publish only on DOCKER_BIND_HOST, "
            "else production compose binds them to every interface",
        )

    def test_the_sso_sidecar_port_carries_docker_bind_host(self) -> None:
        self.assertRegex(
            read_text(str(SSO_SIDECAR)),
            r"-\s*\{\{\s*DOCKER_BIND_HOST\s*\}\}:\{\{",
            "the oauth2-proxy sidecar relays identity headers to the backend, "
            "so its published port must bind DOCKER_BIND_HOST",
        )

    def test_production_compose_binds_loopback(self) -> None:
        self.assertRegex(
            read_text(str(GENERAL_VARS)),
            _PRODUCTION_BIND,
            "DOCKER_BIND_HOST must be 127.0.0.1 outside DOCKER_IN_CONTAINER",
        )

    def test_the_outer_dev_compose_publishes_no_header_trust_port(self) -> None:
        local: dict[int, str] = {}
        for role in _roles():
            services = load_yaml_any(str(ROLES_DIR / role / ROLE_FILE_META_SERVICES))
            local.update(dict.fromkeys(_local_ports(services), role))
        leaked = sorted(
            f"{port} ({local[port]})" for port in _outer_published_ports() & set(local)
        )
        self.assertEqual(
            [],
            leaked,
            "compose.yml publishes a header-trust backend port out of the dev container",
        )


if __name__ == "__main__":
    unittest.main()
