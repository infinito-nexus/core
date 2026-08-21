from __future__ import annotations

import unittest
from unittest import mock

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader

from plugins.lookup.tor_socks_proxy import LookupModule, resolve_proxy_url

APPS = {"svc-net-tor": {"services": {"tor": {"ports": {"local": {"socks": 9050}}}}}}


class TestResolveProxyUrl(unittest.TestCase):
    def test_swarm_uses_the_shared_overlay_alias(self):
        self.assertEqual(resolve_proxy_url(APPS, "swarm"), "socks5h://tor:9050")

    def test_compose_uses_the_host_gateway(self):
        self.assertEqual(
            resolve_proxy_url(APPS, "compose"),
            "socks5h://host.docker.internal:9050",
        )

    def test_unknown_mode_falls_back_to_the_compose_form(self):
        for mode in ("", "  ", "kubernetes", None):
            with self.subTest(mode=mode):
                self.assertEqual(
                    resolve_proxy_url(APPS, mode),
                    "socks5h://host.docker.internal:9050",
                )

    def test_port_comes_from_the_single_source_of_truth(self):
        apps = {
            "svc-net-tor": {"services": {"tor": {"ports": {"local": {"socks": 9150}}}}}
        }
        self.assertEqual(resolve_proxy_url(apps, "swarm"), "socks5h://tor:9150")

    def test_missing_port_raises(self):
        with self.assertRaises(AnsibleError):
            resolve_proxy_url({"svc-net-tor": {"services": {"tor": {}}}}, "swarm")


DEPLOYMENT_MODE_EXPR = (
    "{{ 'swarm' if (groups['svc-swarm-node'] | default([]) | length) > 1"
    " else 'compose' }}"
)


class _StubTemplar:
    """Templar stub resolving the DEPLOYMENT_MODE expression to a fixed mode.

    Args:
        resolved: the mode string the expression evaluates to.
    """

    def __init__(self, resolved: str) -> None:
        self.resolved = resolved
        self.available_variables: dict[str, object] = {}

    def template(self, value):
        return self.resolved if value == DEPLOYMENT_MODE_EXPR else value


class TestTorSocksProxyLookup(unittest.TestCase):
    def test_terms_raise(self):
        lookup = LookupModule()
        lookup._templar = None
        with self.assertRaises(AnsibleError):
            lookup.run(["x"], variables={})

    def _run(self, resolved: str) -> str:
        lookup = LookupModule()
        lookup._templar = _StubTemplar(resolved)
        lookup._loader = None
        variables = {
            "DEPLOYMENT_MODE": DEPLOYMENT_MODE_EXPR,
            "applications": APPS,
        }
        with mock.patch.object(lookup_loader, "get", return_value=_StubApplications()):
            return lookup.run([], variables=variables)[0]

    def test_a_swarm_deployment_reaches_tor_over_the_overlay(self):
        self.assertEqual(self._run("swarm"), "socks5h://tor:9050")

    def test_a_compose_deployment_reaches_tor_over_the_host_gateway(self):
        self.assertEqual(self._run("compose"), "socks5h://host.docker.internal:9050")


class _StubApplications:
    def run(self, terms, variables=None, roles_dir=None):
        return [APPS]


if __name__ == "__main__":
    unittest.main()
