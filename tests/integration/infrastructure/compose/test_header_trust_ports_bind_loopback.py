"""Integration test: production compose publishes header-trust backends on loopback.

A role that logs a user in from a proxy-set identity header trusts whoever
reaches its port, so the port must stay on loopback outside the dev stack.
This renders every ``container_ports`` call of each detected header-trust
role's real ``compose.yml.j2`` with Ansible's Templar, against the real
applications, in compose, with ``DOCKER_BIND_HOST`` resolved from
``group_vars/all/00_general.yml`` for a host that is not a container. A
published port on ``0.0.0.0``, or without a host address, which Docker binds
to every interface, fails it.
"""

from __future__ import annotations

import re
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.lookup.applications import _reset_cache_for_tests
from utils.cache.files import read_text
from utils.roles.header_trust import header_trust_roles
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
GENERAL_VARS = PROJECT_ROOT / "group_vars/all/00_general.yml"
LOOPBACK = "127.0.0.1"

_EXPRESSION = re.compile(
    r"\{\{((?:(?!\{\{|\}\}).)*?lookup\(\s*'container_ports'(?:(?!\}\}).)*)\}\}",
    re.DOTALL,
)
_SHORT = re.compile(r'^\s*-\s*"([^"]*)"\s*$')
_LONG = re.compile(r"^\s*(?:-\s*)?published:\s*(\S+)\s*$")


def _bind_host_expression() -> object:
    return DataLoader().load_from_file(str(GENERAL_VARS), trusted_as_template=True)[
        "DOCKER_BIND_HOST"
    ]


def _variables(role: str, *, in_container: bool) -> dict:
    declared = DataLoader().load_from_file(
        str(ROLES_DIR / role / ROLE_FILE_VARS_MAIN), trusted_as_template=True
    )
    return {
        **(declared or {}),
        "applications": {},
        "users": {},
        "DOMAIN_PRIMARY": "infinito.test",
        "SYSTEM_EMAIL_DOMAIN": "infinito.test",
        "DIR_COMPOSITIONS": "/opt/compose/",
        "group_names": sorted(header_trust_roles(ROLES_DIR)),
        "DEPLOYMENT_MODE": "compose",
        "application_id": role,
        "networks": {"internet": {"ip4": "198.51.100.7", "ip6": "", "dns": ""}},
        "DOCKER_IN_CONTAINER": in_container,
        "DOCKER_BIND_HOST": _bind_host_expression(),
    }


def port_expressions(template: str) -> list[str]:
    """Every ``{{ ... }}`` expression of *template* that calls ``container_ports``.

    Args:
        template: the source of a ``compose.yml.j2``.
    """
    return ["{{" + body + "}}" for body in _EXPRESSION.findall(template)]


def render_ports(role: str, *, in_container: bool = False) -> list[str]:
    """The rendered ``ports``/``expose`` blocks of *role*'s compose template.

    Args:
        role: a role directory name under ``roles/``.
        in_container: the ``DOCKER_IN_CONTAINER`` the bind host resolves from.
    """
    template = read_text(str(ROLES_DIR / role / ROLE_FILE_TEMPL_COMPOSE))
    templar = Templar(
        loader=DataLoader(), variables=_variables(role, in_container=in_container)
    )
    return [
        str(templar.template(_trust_as_template(expression)))
        for expression in port_expressions(template)
    ]


def binding_problems(block: str) -> list[str]:
    """Every published port of a rendered block that is not bound to loopback.

    Args:
        block: one rendered ``container_ports`` block.
    """
    if block.lstrip().startswith("expose:"):
        return []
    problems: list[str] = []
    for line in block.splitlines():
        short = _SHORT.match(line)
        if short:
            mapping = short.group(1)
            if not mapping.startswith(f"{LOOPBACK}:") or mapping.count(":") != 2:
                problems.append(mapping)
            continue
        long = _LONG.match(line)
        if long:
            problems.append(f"published: {long.group(1)} without host_ip")
    return problems


def _mappings(block: str) -> list[str]:
    return [
        match.group(1) for line in block.splitlines() if (match := _SHORT.match(line))
    ]


class TestHeaderTrustPortsBindLoopback(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _reset_cache_for_tests()
        cls.roles = sorted(header_trust_roles(ROLES_DIR))
        cls.rendered = {role: render_ports(role) for role in cls.roles}

    def test_header_trust_roles_are_detected(self) -> None:
        self.assertTrue(self.roles, "no header-trust role detected")

    def test_every_role_publishes_through_container_ports(self) -> None:
        for role in self.roles:
            with self.subTest(role=role):
                self.assertTrue(
                    any(_mappings(block) for block in self.rendered[role]),
                    f"{role}: {ROLE_FILE_TEMPL_COMPOSE} renders no published port, "
                    "so this test would pass over it",
                )

    def test_production_compose_binds_every_port_to_loopback(self) -> None:
        findings = [
            f"{role}: {problem}"
            for role in self.roles
            for block in self.rendered[role]
            for problem in binding_problems(block)
        ]
        self.assertEqual(
            [],
            findings,
            "a header-trust backend published beside loopback hands its trusted "
            "identity header to every client that reaches the host",
        )


class TestTheCheckCatchesWhatItGuards(unittest.TestCase):
    def test_an_all_interfaces_address_is_reported(self) -> None:
        self.assertEqual(
            binding_problems('ports:\n  - "0.0.0.0:8080:80"'), ["0.0.0.0:8080:80"]
        )

    def test_a_port_without_a_host_address_is_reported(self) -> None:
        for block in ('ports:\n  - "8080:80"', 'ports:\n  - "80"'):
            with self.subTest(block=block):
                self.assertTrue(binding_problems(block))

    def test_a_long_syntax_port_is_reported(self) -> None:
        block = (
            "ports:\n  - target: 80\n    published: 8080\n"
            "    protocol: tcp\n    mode: host"
        )
        self.assertEqual(binding_problems(block), ["published: 8080 without host_ip"])

    def test_a_loopback_port_passes(self) -> None:
        self.assertEqual(binding_problems('ports:\n  - "127.0.0.1:8080:80/tcp"'), [])

    def test_the_dev_stack_bind_host_is_reported_on_a_real_role(self) -> None:
        role = min(header_trust_roles(ROLES_DIR))
        findings = [
            problem
            for block in render_ports(role, in_container=True)
            for problem in binding_problems(block)
        ]
        self.assertTrue(
            findings,
            f"{role}: rendered with DOCKER_IN_CONTAINER true the ports must bind "
            "0.0.0.0, otherwise the render ignores DOCKER_BIND_HOST",
        )

    def test_the_expression_finder_reads_one_call_per_expression(self) -> None:
        template = (
            "    {{ lookup('container_ports', ['a', 'http', DOCKER_BIND_HOST]) "
            "| indent(4) }}\n"
            "    image: {{ IMAGE }}\n"
            "    {{ lookup('container_ports', {'service': 'b', 'protocol': 'http', "
            "'ip': DOCKER_BIND_HOST}) | indent(4) }}\n"
        )
        self.assertEqual(len(port_expressions(template)), 2)


if __name__ == "__main__":
    unittest.main()
