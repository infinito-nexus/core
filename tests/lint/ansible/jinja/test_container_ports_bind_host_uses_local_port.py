"""Lint: a ``container_ports`` term bound to DOCKER_BIND_HOST publishes ``ports.local``.

In swarm ``container_ports`` drops a bound term only when it resolves
``ports.local``; one that falls back to ``ports.public`` stays on the routing
mesh, and the swarm ingress guard exempts public ports, so it would stay open on
every node. Terms whose service or protocol is not a literal are not checked.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_CALL = re.compile(r"lookup\(\s*'container_ports'\s*,(.*?)\)\s*(?:\||\}\})", re.DOTALL)
_LIST_TERM = re.compile(
    r"""\[\s*['"]([\w-]+)['"]\s*,\s*['"]([\w-]+)['"]\s*,\s*DOCKER_BIND_HOST\s*\]"""
)
_DICT_TERM = re.compile(r"\{([^{}]*)\}")
_DICT_IP = re.compile(r"""['"]ip['"]\s*:\s*DOCKER_BIND_HOST\b""")
_DICT_KEY = r"""['"]{key}['"]\s*:\s*['"]([\w-]+)['"]"""


def _bound_terms(text: str) -> list[tuple[str, str]]:
    """Returns ``(service, protocol)`` of every literal term bound to DOCKER_BIND_HOST."""
    terms: list[tuple[str, str]] = []
    for args in _CALL.findall(text):
        terms.extend(_LIST_TERM.findall(args))
        for term in _DICT_TERM.findall(args):
            if not _DICT_IP.search(term):
                continue
            service = re.search(_DICT_KEY.format(key="service"), term)
            protocol = re.search(_DICT_KEY.format(key="protocol"), term)
            if service and protocol:
                terms.append((service.group(1), protocol.group(1)))
    return terms


def _declares_local(services: object, service: str, protocol: str) -> bool | None:
    """Returns whether ``service`` declares ``ports.local.<protocol>``; None if unknown."""
    if not isinstance(services, dict) or not isinstance(services.get(service), dict):
        return None
    ports = services[service].get("ports")
    local = ports.get("local") if isinstance(ports, dict) else None
    return isinstance(local, dict) and protocol in local


class TestContainerPortsBindHostUsesLocalPort(unittest.TestCase):
    def test_bound_terms_resolve_a_local_port(self):
        roles_dir = PROJECT_ROOT / "roles"
        violations: list[str] = []
        for raw_path, text in iter_project_files_with_content(extensions=(".j2",)):
            path = Path(raw_path)
            if "container_ports" not in text or roles_dir not in path.parents:
                continue
            services_file = (
                roles_dir
                / path.relative_to(roles_dir).parts[0]
                / ROLE_FILE_META_SERVICES
            )
            services = load_yaml_any(services_file) if services_file.is_file() else None
            for service, protocol in _bound_terms(text):
                if _declares_local(services, service, protocol) is False:
                    violations.append(
                        f"{path.relative_to(PROJECT_ROOT)}: [{service!r}, {protocol!r}, "
                        f"DOCKER_BIND_HOST] has no services.{service}.ports.local.{protocol}"
                    )
        self.assertEqual(violations, [], "\n".join(violations))

    def test_detects_a_bound_term_without_local_port(self):
        text = "{{ lookup('container_ports', ['web', 'http', DOCKER_BIND_HOST]) | indent(4) }}"
        services = {
            "web": {"ports": {"public": {"http": 80}, "internal": {"http": 8080}}}
        }
        (service, protocol), *_ = _bound_terms(text)
        self.assertIs(_declares_local(services, service, protocol), False)

    def test_dict_term_with_bind_host_is_checked(self):
        text = (
            "{{ lookup('container_ports', {'service': 'lk', 'protocol': 'ws', "
            "'ip': DOCKER_BIND_HOST}) | indent(4) }}"
        )
        self.assertEqual(_bound_terms(text), [("lk", "ws")])


if __name__ == "__main__":
    unittest.main()
