"""Lint: header-trust ports stay off every interface outside the role render.

The rendered production compose of every header-trust backend is proven by
``tests/integration/infrastructure/compose/test_header_trust_ports_bind_loopback.py``.
This lint covers the two publishers that render does not reach: the SSO
sidecar's port and the outer dev ``compose.yml``.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.header_trust import header_trust_roles
from utils.roles.mapping import ROLE_FILE_META_SERVICES

ROLES_DIR = PROJECT_ROOT / "roles"
SSO_SIDECAR = ROLES_DIR / "web-app-keycloak/templates/sso_proxy/container.yml.j2"
OUTER_COMPOSE = PROJECT_ROOT / "compose.yml"

_OUTER_PORT = re.compile(r'"\$\{INFINITO_BIND_IP[^}]*\}:(\d+)(?:-(\d+))?:')


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
    def test_the_sso_sidecar_port_carries_docker_bind_host(self) -> None:
        self.assertRegex(
            read_text(str(SSO_SIDECAR)),
            r"-\s*\{\{\s*DOCKER_BIND_HOST\s*\}\}:\{\{",
            "the oauth2-proxy sidecar relays identity headers to the backend, "
            "so its published port must bind DOCKER_BIND_HOST",
        )

    def test_the_outer_dev_compose_publishes_no_header_trust_port(self) -> None:
        local: dict[int, str] = {}
        for role in sorted(header_trust_roles(ROLES_DIR)):
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
