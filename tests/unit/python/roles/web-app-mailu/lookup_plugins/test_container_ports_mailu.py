from __future__ import annotations

import importlib.util
import sys
import unittest
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

from . import PROJECT_ROOT

INTERNAL_PORTS = {
    "http": 80,
    "smtp": 25,
    "smtps": 465,
    "submission": 587,
    "pop3": 110,
    "pop3s": 995,
    "imap": 143,
    "imaps": 993,
    "sieve": 4190,
}

BIND = "127.0.0.1"
PUBLIC = "10.0.0.1"


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MODULE = _load_module(
    "roles/web-app-mailu/lookup_plugins/container_ports_mailu.py",
    "container_ports_mailu",
)


class TestContainerPortsMailu(unittest.TestCase):
    def setUp(self):
        self.lookup = MODULE.LookupModule()
        self.email = {"tls": True}
        self.captured: list = []

        def _get(name, *args, **kwargs):
            plugin = MagicMock()
            if name == "email":
                plugin.run.side_effect = lambda terms, **_kw: [self.email]
            else:
                plugin.run.side_effect = lambda terms, **_kw: (
                    self.captured.append(terms) or ["ports:"]
                )
            return plugin

        patcher = patch.object(MODULE.lookup_loader, "get", side_effect=_get)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _protocols(self, **overrides) -> list[str]:
        variables = {
            "application_id": "web-app-mailu",
            "MAILU_PORTS": INTERNAL_PORTS,
            "DOCKER_BIND_HOST": BIND,
            "MAILU_IP4_PUBLIC": PUBLIC,
        }
        variables.update(overrides)
        self.lookup.run([], variables=variables)
        return [term[1] for term in self.captured[0]]

    def test_tls_publishes_every_declared_protocol(self):
        self.assertEqual(self._protocols(), list(INTERNAL_PORTS))

    def test_notls_drops_only_the_implicit_tls_protocols(self):
        self.email = {"tls": False}
        published = self._protocols()
        self.assertNotIn("smtps", published)
        self.assertNotIn("pop3s", published)
        self.assertNotIn("imaps", published)
        self.assertEqual(
            published, ["http", "smtp", "submission", "pop3", "imap", "sieve"]
        )

    def test_http_binds_to_the_docker_host_and_the_rest_to_the_public_address(self):
        self._protocols()
        hosts = {term[1]: term[2] for term in self.captured[0]}
        self.assertEqual(hosts["http"], BIND)
        self.assertEqual(hosts["smtp"], PUBLIC)
        self.assertEqual(hosts["imaps"], PUBLIC)

    def test_an_empty_catalogue_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            self._protocols(MAILU_PORTS={})

    def test_a_missing_tls_flag_fails_loudly(self):
        self.email = {"host": "mail.example.org"}
        with self.assertRaises(AnsibleError):
            self._protocols()

    def test_positional_terms_are_rejected(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["mailu"], variables={})


if __name__ == "__main__":
    unittest.main()
