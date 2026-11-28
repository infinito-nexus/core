from __future__ import annotations

import re
import unittest
import unittest.mock as mock

from plugins.lookup.tls import LookupModule
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

PROVIDER_VARS = PROJECT_ROOT / "roles/sys-front-tls-letsencrypt" / ROLE_FILE_VARS_MAIN
DISPATCHER_VARS = PROJECT_ROOT / "roles/sys-front-tls" / ROLE_FILE_VARS_MAIN
TLS_TERM = re.compile(r"\{\{ lookup\('tls', (\w+), '([\w.]+)'\) \}\}")

SERVED_NAME = "*.user.blog.example.org"
TOR_NODE_VARIABLES = {
    "domains": {"web-app-wordpress": ["blog.abc.onion", "biber.blog.abc.onion"]},
    "applications": {"web-app-wordpress": {}},
    "TLS_ENABLED": True,
    "TLS_MODE": "letsencrypt",
    "CURRENT_PLAY_SERVED_DOMAINS": [
        {"name": SERVED_NAME, "application_id": "web-app-wordpress"}
    ],
    "application_id": "web-app-wordpress",
    "domain": SERVED_NAME,
}


def _tls_term(path, fact: str) -> tuple[str, str]:
    """Args:
        path: the vars file.
        fact: the variable whose ``lookup('tls', <term>, '<want>')`` is read.

    Returns:
        ``(term, want)`` of that lookup.
    """
    match = TLS_TERM.fullmatch(load_yaml_any(path)[fact])
    if match is None:
        raise AssertionError(f"{path}: {fact} is no lookup('tls', <term>, <want>)")
    return match.group(1), match.group(2)


class TestLetsEncryptProviderResolvesTheDispatchedVhost(unittest.TestCase):
    def setUp(self):
        self.lookup = LookupModule()
        self.lookup._loader = mock.MagicMock()

        def _get(name, *_a, **_k):
            def _run(_terms, variables=None, **__):
                return [(variables or {}).get(name, {})]

            return mock.MagicMock(run=_run)

        patcher = mock.patch("plugins.lookup.tls.lookup_loader")
        patcher.start().get.side_effect = _get
        self.addCleanup(patcher.stop)

    def _resolve(self, term: str, want: str):
        return self.lookup.run(
            [TOR_NODE_VARIABLES[term], want], variables=TOR_NODE_VARIABLES
        )[0]

    def test_the_mode_assert_resolves_by_the_term_the_dispatcher_chose_by(self):
        dispatcher, _ = _tls_term(DISPATCHER_VARS, "tls_mode_effective")
        for fact in ("_tls_enabled", "_tls_mode", "_tls_domain"):
            with self.subTest(fact=fact):
                self.assertEqual(_tls_term(PROVIDER_VARS, fact)[0], dispatcher)

    def test_a_clearnet_served_name_on_a_tor_node_passes_the_mode_assert(self):
        dispatched = self._resolve(*_tls_term(DISPATCHER_VARS, "tls_mode_effective"))
        self.assertEqual(dispatched, "letsencrypt")
        self.assertTrue(self._resolve(*_tls_term(PROVIDER_VARS, "_tls_enabled")))
        self.assertEqual(
            self._resolve(*_tls_term(PROVIDER_VARS, "_tls_mode")), dispatched
        )

    def test_negative_control_resolving_by_the_application_reads_tls_off(self):
        self.assertFalse(self._resolve("application_id", "enabled"))
        self.assertEqual(self._resolve("application_id", "mode"), "off")


if __name__ == "__main__":
    unittest.main()
