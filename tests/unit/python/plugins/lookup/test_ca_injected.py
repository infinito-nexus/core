"""Unit tests for the ca_injected lookup plugin.

Pins the predicate that decides whether the self-signed root CA is bind-mounted
into an application's containers. Anything reading the mounted file must agree
with the handler gate that creates the mount, so all three terms are pinned
here, including their short-circuit order.
"""

from __future__ import annotations

import importlib.util
import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from . import PROJECT_ROOT

MODULE = "lookup_ca_injected"


def _load_lookup():
    spec = importlib.util.spec_from_file_location(
        MODULE, str(PROJECT_ROOT / "plugins/lookup/ca_injected.py")
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _DummyTemplar:
    def template(self, value):
        return value


class _StubLookup:
    def __init__(self, result):
        self._result = result

    def run(self, args, variables=None):
        return [self._result]


class TestCaInjectedLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_lookup()

    def _resolve(self, *, domains, enabled, mode, app="web-app-moodle"):
        calls: list[tuple[str, list]] = []

        def fake_get(name, **_kwargs):
            def run(args, variables=None):
                calls.append((name, list(args)))
                if name == "domains":
                    return [domains]
                return [enabled if args[1] == "enabled" else mode]

            return mock.Mock(run=run)

        plugin = self.mod.LookupModule()
        plugin._loader = None
        plugin._templar = _DummyTemplar()
        with mock.patch.object(self.mod.lookup_loader, "get", side_effect=fake_get):
            result = plugin.run([app], variables={})
        return result[0], calls

    def test_a_self_signed_app_with_a_domain_gets_the_ca(self):
        verdict, _ = self._resolve(
            domains={"web-app-moodle": "moodle.example"},
            enabled=True,
            mode="self_signed",
        )
        self.assertIs(verdict, True)

    def test_letsencrypt_does_not_get_the_ca(self):
        verdict, _ = self._resolve(
            domains={"web-app-moodle": "moodle.example"},
            enabled=True,
            mode="letsencrypt",
        )
        self.assertIs(verdict, False)

    def test_tls_disabled_does_not_get_the_ca(self):
        verdict, _ = self._resolve(
            domains={"web-app-moodle": "moodle.example"},
            enabled=False,
            mode="self_signed",
        )
        self.assertIs(verdict, False)

    def test_an_app_without_a_domain_never_asks_about_tls(self):
        verdict, calls = self._resolve(domains={}, enabled=True, mode="self_signed")
        self.assertIs(verdict, False)
        self.assertEqual([name for name, _ in calls], ["domains"])

    def test_the_term_is_required(self):
        plugin = self.mod.LookupModule()
        plugin._templar = _DummyTemplar()
        with self.assertRaises(AnsibleError):
            plugin.run([], variables={})
        with self.assertRaises(AnsibleError):
            plugin.run(["  "], variables={})


if __name__ == "__main__":
    unittest.main()
