from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

ROLES = PROJECT_ROOT / "roles"
HOSTNAME_LINE = re.compile(
    r"^\s*hostname:\s*['\"]?\{\{\s*(\w+)\s*\}\}['\"]?\s*$", re.MULTILINE
)
VAR_REFERENCE = re.compile(r"\A\{\{\s*(\w+)\s*\}\}\Z")
DOMAIN_SOURCES = ("container_hostname", "lookup('domain'", "lookup('tls'")
DOMAIN_HOSTNAME_XWIKI_VARS = {
    "container_hostname": "{{ lookup('container_hostname', application_id) }}",
    "XWIKI_HOSTNAME": "{{ container_hostname }}",
}
DOMAIN_HOSTNAME_XWIKI_COMPOSE = "  xwiki:\n    hostname: '{{ XWIKI_HOSTNAME}}'\n"


def gate_roles() -> list[str]:
    """
    Returns:
        The sorted roles whose meta/services.yml sets
        sso.oidc.backchannel_logout_gate.
    """
    roles = []
    for path in iter_project_files(extensions=("services.yml",)):
        relative = Path(path).relative_to(PROJECT_ROOT)
        if (
            len(relative.parts) != 4
            or relative.parts[0] != "roles"
            or "/".join(relative.parts[2:]) != ROLE_FILE_META_SERVICES
        ):
            continue
        sso = (load_yaml(path) or {}).get("sso") or {}
        if (sso.get("oidc") or {}).get("backchannel_logout_gate") is True:
            roles.append(relative.parts[1])
    return sorted(roles)


def hostname_sources(compose: str, variables: dict) -> list[str]:
    """
    Args:
        compose: the text of a role's templates/compose.yml.j2.
        variables: the mapping of that role's vars/main.yml.

    Returns:
        One expression per templated ``hostname:`` line: its value after
        following every bare reference to another role var.
    """
    sources = []
    for name in HOSTNAME_LINE.findall(compose):
        expression = "{{ " + name + " }}"
        followed = set()
        while (
            (match := VAR_REFERENCE.match(expression))
            and match.group(1) in variables
            and match.group(1) not in followed
        ):
            followed.add(match.group(1))
            expression = str(variables[match.group(1)]).strip()
        sources.append(expression)
    return sources


def names_the_canonical_domain(expression: str) -> bool:
    """
    Args:
        expression: one result of hostname_sources.

    Returns:
        Whether the expression derives the hostname from the role's domain.
    """
    return any(source in expression for source in DOMAIN_SOURCES)


class TestGateReceiverHostnames(unittest.TestCase):
    def test_the_scan_finds_the_gated_receivers(self) -> None:
        self.assertTrue(
            gate_roles(),
            "no role sets sso.oidc.backchannel_logout_gate, so the hostname check "
            "below would pass without looking at a single receiver",
        )

    def test_no_gated_receiver_takes_its_domain_as_container_hostname(self) -> None:
        for role in gate_roles():
            compose = ROLES / role / ROLE_FILE_TEMPL_COMPOSE
            if not compose.exists():
                continue
            variables = load_yaml(
                ROLES / role / ROLE_FILE_VARS_MAIN, default_if_missing={}
            )
            for expression in hostname_sources(
                read_text(str(compose)), variables or {}
            ):
                with self.subTest(role=role, hostname=expression):
                    self.assertFalse(
                        names_the_canonical_domain(expression),
                        f"{role}: the container hostname comes from {expression}, the "
                        "canonical domain. Docker adds a container's hostname to its DNS "
                        "names on every network it joins, so on the shared proxy network "
                        "the logout gate resolves the receiver URL to the app container "
                        "itself, finds nothing on 443, never reaches the seal in the proxy "
                        "and answers Keycloak's back-channel logout with 502; the app "
                        "session then outlives the Keycloak session",
                    )

    def test_the_check_flags_a_hostname_taken_from_the_domain(self) -> None:
        sources = hostname_sources(
            DOMAIN_HOSTNAME_XWIKI_COMPOSE, DOMAIN_HOSTNAME_XWIKI_VARS
        )
        self.assertEqual(len(sources), 1)
        self.assertTrue(names_the_canonical_domain(sources[0]))


if __name__ == "__main__":
    unittest.main()
