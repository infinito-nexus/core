from __future__ import annotations

import re
import unittest
import unittest.mock as mock

from plugins.lookup.tls import LookupModule
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

PROVIDER_TASKS = PROJECT_ROOT / "roles/sys-front-tls-selfsigned/tasks/00_core.yml"
DISPATCHER_VARS = PROJECT_ROOT / "roles/sys-front-tls/vars/main.yml"

SERVED_NAME = "*.user.blog.example.org"
TOR_NODE_VARIABLES = {
    "domains": {"web-app-wordpress": ["blog.abc.onion", "biber.blog.abc.onion"]},
    "applications": {"web-app-wordpress": {}},
    "TLS_ENABLED": True,
    "TLS_MODE": "self_signed",
    "CURRENT_PLAY_SERVED_DOMAINS": [
        {"name": SERVED_NAME, "application_id": "web-app-wordpress"}
    ],
    "application_id": "web-app-wordpress",
    "domain": SERVED_NAME,
}


def _set_fact_term(fact: str, plugin: str) -> str:
    for task in load_yaml_any(PROVIDER_TASKS):
        expression = (task.get("ansible.builtin.set_fact") or {}).get(fact)
        if expression:
            return re.fullmatch(
                r"\{\{ lookup\('" + plugin + r"', (\w+)\) \}\}", expression
            ).group(1)
    raise AssertionError(f"{PROVIDER_TASKS} sets no {fact}")


def _dispatcher_term() -> str:
    expression = load_yaml_any(DISPATCHER_VARS)["tls_mode_effective"]
    return re.fullmatch(r"\{\{ lookup\('tls', (\w+), 'mode'\) \}\}", expression).group(
        1
    )


class TestSelfSignedProviderResolvesTheDispatchedVhost(unittest.TestCase):
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

    def test_tls_and_cert_resolve_by_the_term_the_dispatcher_chose_the_mode_by(self):
        dispatcher = _dispatcher_term()
        self.assertEqual(_set_fact_term("_tls", "tls"), dispatcher)
        self.assertEqual(_set_fact_term("_cert", "cert"), dispatcher)

    def test_a_clearnet_served_name_on_a_tor_node_passes_the_mode_assert(self):
        dispatched = self.lookup.run(
            [TOR_NODE_VARIABLES[_dispatcher_term()], "mode"],
            variables=TOR_NODE_VARIABLES,
        )[0]
        self.assertEqual(dispatched, "self_signed")

        resolved = self.lookup.run(
            [TOR_NODE_VARIABLES[_set_fact_term("_tls", "tls")]],
            variables=TOR_NODE_VARIABLES,
        )[0]
        self.assertTrue(resolved["enabled"])
        self.assertEqual(resolved["mode"], dispatched)


if __name__ == "__main__":
    unittest.main()
