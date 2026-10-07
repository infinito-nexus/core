from __future__ import annotations

import os
import unittest
from typing import ClassVar
from unittest import mock

from ansible.errors import AnsibleError

from plugins.lookup.sso_whitelist_domains import LookupModule

PRIMARY = "main.infinito.test"
RAW_PRIMARY = "{{ lookup('env', 'INFINITO_WHITELIST_TEST_DOMAIN') }}"


class _Stub:
    def __init__(self, value):
        self._value = value

    def run(self, *_args, **_kwargs):
        return [self._value]


def _loader_for(domains, node_onion=""):
    def get(name, **_kwargs):
        if name == "domains":
            return _Stub(domains)
        if name == "config":
            return _Stub(node_onion)
        raise AssertionError(f"unexpected lookup {name}")

    return get


class TestSsoWhitelistDomains(unittest.TestCase):
    APP: ClassVar[str] = "web-app-pihole"

    def setUp(self) -> None:
        self.module = LookupModule()
        self.module._loader = None
        self.module._templar = None
        os.environ["INFINITO_WHITELIST_TEST_DOMAIN"] = PRIMARY
        self.addCleanup(os.environ.pop, "INFINITO_WHITELIST_TEST_DOMAIN", None)

    def _run(self, variables, domains=None, node_onion=""):
        domains = {self.APP: f"pihole.{PRIMARY}"} if domains is None else domains
        with mock.patch(
            "plugins.lookup.sso_whitelist_domains.lookup_loader.get",
            side_effect=_loader_for(domains, node_onion),
        ):
            return self.module.run([self.APP], variables=variables)[0]

    def test_raw_jinja_primary_domain_is_rendered(self):
        self.assertEqual(
            self._run({"DOMAIN_PRIMARY": RAW_PRIMARY}), [f".{PRIMARY}"]
        )

    def test_plain_primary_domain_passes_through(self):
        self.assertEqual(self._run({"DOMAIN_PRIMARY": PRIMARY}), [f".{PRIMARY}"])

    def test_unresolvable_primary_domain_fails_closed(self):
        with self.assertRaises(AnsibleError):
            self._run({"DOMAIN_PRIMARY": "{{ undefined_primary_domain }}"})

    def test_onion_only_app_gets_no_clearnet_scope(self):
        onion = "h5ixhuz3djk5wx3ecch3wl442z2vw66p55djsjwmdzqyufurcixly6qd.onion"
        self.assertEqual(
            self._run(
                {"DOMAIN_PRIMARY": PRIMARY},
                domains={self.APP: f"pihole.{onion}"},
                node_onion=onion,
            ),
            [f".{onion}"],
        )


if __name__ == "__main__":
    unittest.main()
