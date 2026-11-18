from __future__ import annotations

import re
import unittest
from ipaddress import ip_address, ip_network
from string import Template

from jinja2 import DictLoader, Environment, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = "roles/web-app-erpnext"
ENV_TEMPLATE = f"{ROLE}/templates/env.j2"
FRONTEND_TEMPLATE = f"{ROLE}/templates/env/frontend.j2"
UPSTREAM_REAL_IP_LINE = Template("set_real_ip_from ${UPSTREAM_REAL_IP_ADDRESS};")
SET_REAL_IP_FROM = re.compile(r"\s*set_real_ip_from ([^;\s]+);")
CLIENT = "203.0.113.9"
FORGED = "198.51.100.66"
COMPOSE_HOPS = ["192.168.41.1", "192.168.201.1"]
MODES = {
    "compose": (COMPOSE_HOPS, COMPOSE_HOPS),
    "swarm": (["192.168.107.0/24"], ["192.168.107.23"]),
}


def _trusted_proxies(hops: list[str]) -> list[str]:
    variables = load_yaml_any(str(PROJECT_ROOT / ROLE / ROLE_FILE_VARS_MAIN))

    def lookup(name: str, *args: str) -> list[str] | str:
        if (name, args) == ("proxy_hops", (variables["application_id"],)):
            return hops
        return f"<lookup {name}>"

    return (
        NativeEnvironment()
        .from_string(variables["ERPNEXT_TRUSTED_PROXIES"])
        .render(lookup=lookup, application_id=variables["application_id"])
    )


def _frontend_env(hops: list[str]) -> dict[str, str]:
    environment = Environment(
        loader=DictLoader(
            {
                ENV_TEMPLATE: "",
                FRONTEND_TEMPLATE: read_text(str(PROJECT_ROOT / FRONTEND_TEMPLATE)),
            }
        ),
        autoescape=select_autoescape(default_for_string=False),
    )
    rendered = environment.get_template(FRONTEND_TEMPLATE).render(
        ERPNEXT_TRUSTED_PROXIES=_trusted_proxies(hops)
    )
    return dict(line.split("=", 1) for line in rendered.splitlines() if "=" in line)


def _set_real_ip_from(env: dict[str, str]) -> list[str]:
    rendered = UPSTREAM_REAL_IP_LINE.substitute(env)
    if not re.fullmatch(f"(?:{SET_REAL_IP_FROM.pattern})+", rendered):
        raise AssertionError(f"not a set_real_ip_from sequence: {rendered!r}")
    return SET_REAL_IP_FROM.findall(rendered)


def _real_ip(peer: str, forwarded_for: str, trusted: list[str], recursive: bool) -> str:
    """Args:
        peer: address of the connection's other end.
        forwarded_for: value of the ``X-Forwarded-For`` request header.
        trusted: the ``set_real_ip_from`` addresses and networks.
        recursive: ``real_ip_recursive``.

    Returns:
        The client address the frontend forwards to the backend.
    """
    networks = [ip_network(entry, strict=False) for entry in trusted]
    address = peer
    for entry in reversed([part.strip() for part in forwarded_for.split(",")]):
        if not any(ip_address(address) in network for network in networks):
            return address
        address = entry
        if not recursive:
            return address
    return address


class TestFrontendRealIp(unittest.TestCase):
    def test_the_frontend_trusts_exactly_the_proxy_hops(self):
        for mode, (hops, _peers) in MODES.items():
            with self.subTest(mode=mode):
                self.assertEqual(_set_real_ip_from(_frontend_env(hops)), hops)

    def test_a_request_through_the_proxy_reaches_the_backend_as_the_client(self):
        for mode, (hops, peers) in MODES.items():
            env = _frontend_env(hops)
            self.assertEqual(env["UPSTREAM_REAL_IP_HEADER"], "X-Forwarded-For")
            for peer in peers:
                with self.subTest(mode=mode, peer=peer):
                    self.assertEqual(
                        _real_ip(
                            peer,
                            f"{FORGED}, {CLIENT}",
                            _set_real_ip_from(env),
                            env["UPSTREAM_REAL_IP_RECURSIVE"] == "on",
                        ),
                        CLIENT,
                    )


if __name__ == "__main__":
    unittest.main()
