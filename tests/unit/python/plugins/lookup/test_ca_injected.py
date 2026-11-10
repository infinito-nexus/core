"""Unit tests for the ca_injected lookup plugin.

Pins the predicate that decides whether the self-signed root CA is bind-mounted
into an application's containers. Anything reading the mounted file must agree
with the handler gate that creates the mount, so every term is pinned here,
including their short-circuit order.
"""

from __future__ import annotations

import importlib.util
import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from . import PROJECT_ROOT

MODULE = "lookup_ca_injected"
ISSUER = "web-app-keycloak"


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


class TestCaInjectedLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_lookup()

    def _resolve(
        self,
        *,
        domains,
        enabled,
        mode,
        app="web-app-moodle",
        services=None,
        tls_mode="self_signed",
        peer_enabled=True,
        peer_mode="self_signed",
        issuers=(ISSUER,),
    ):
        calls: list[tuple[str, list]] = []
        own_domain = domains.get(app)

        def fake_get(name, **_kwargs):
            def run(args, variables=None):
                calls.append((name, list(args)))
                if name == "config":
                    return [services or {}]
                if name == "domains":
                    return [domains]
                if args[0] == own_domain:
                    return [enabled if args[1] == "enabled" else mode]
                if args[0] == app:
                    return [False if args[1] == "enabled" else "off"]
                if isinstance(peer_mode, Exception) and args[1] == "mode":
                    raise peer_mode
                return [peer_enabled if args[1] == "enabled" else peer_mode]

            return mock.Mock(run=run)

        plugin = self.mod.LookupModule()
        plugin._loader = None
        plugin._templar = _DummyTemplar()
        with (
            mock.patch.object(self.mod.lookup_loader, "get", side_effect=fake_get),
            mock.patch.object(self.mod, "issuer_applications", return_value=issuers),
        ):
            variables = {} if tls_mode is None else {"TLS_MODE": tls_mode}
            result = plugin.run([app], variables=variables)
        return result[0], calls

    def test_a_self_signed_app_with_a_domain_gets_the_ca(self):
        verdict, _ = self._resolve(
            domains={"web-app-moodle": "moodle.example"},
            enabled=True,
            mode="self_signed",
        )
        self.assertIs(verdict, True)

    def test_own_tls_is_read_on_the_canonical_domain_not_the_vhost_sibling(self):
        verdict, calls = self._resolve(
            domains={"web-app-moodle": "moodle.example"},
            enabled=True,
            mode="self_signed",
        )
        self.assertIs(
            verdict,
            True,
            "asked by application id, tls aligns to the vhost in `domain`; a "
            "handler flushed after the onion sibling's vhost then reads TLS off "
            "and the next stack deploy drops the CA mount",
        )
        self.assertEqual(calls[1], ("tls", ["moodle.example", "enabled"]))

    def test_letsencrypt_does_not_get_the_ca(self):
        verdict, _ = self._resolve(
            domains={"web-app-moodle": "moodle.example"},
            enabled=True,
            mode="letsencrypt",
        )
        self.assertIs(verdict, False)

    def test_tls_disabled_does_not_get_the_ca(self):
        verdict, calls = self._resolve(
            domains={"web-app-moodle": "moodle.example"},
            enabled=False,
            mode="self_signed",
        )
        self.assertIs(verdict, False)
        self.assertEqual([name for name, _ in calls], ["domains", "tls", "config"])

    def test_an_app_without_a_domain_never_asks_about_tls(self):
        verdict, calls = self._resolve(domains={}, enabled=True, mode="self_signed")
        self.assertIs(verdict, False)
        self.assertEqual([name for name, _ in calls], ["domains", "config"])

    def test_a_domainless_ca_client_gets_the_ca_from_a_self_signed_issuer(self):
        verdict, calls = self._resolve(
            domains={},
            enabled=True,
            mode="self_signed",
            services={"agent-broker": {"ca_client": True}, "socket-proxy": {}},
        )
        self.assertIs(
            verdict,
            True,
            "a container that only calls the self-signed endpoint has no domain "
            "of its own, and without the CA every outbound call fails the "
            "handshake",
        )
        self.assertEqual(
            calls,
            [
                ("domains", []),
                ("config", ["web-app-moodle", "services", {}]),
                ("tls", [ISSUER, "enabled"]),
                ("tls", [ISSUER, "mode"]),
            ],
        )

    def test_a_domainless_ca_client_gets_the_ca_on_the_deployment_mode(self):
        verdict, calls = self._resolve(
            domains={},
            enabled=True,
            mode="self_signed",
            services={"agent-broker": {"ca_client": True}, "socket-proxy": {}},
            issuers=(),
        )
        self.assertIs(
            verdict,
            True,
            "with no issuer to answer for it, a domainless ca_client still needs "
            "the CA whenever the deployment itself is self-signed",
        )
        self.assertEqual([name for name, _ in calls], ["domains", "config"])

    def test_a_ca_client_with_a_domain_never_answers_on_the_deployment_mode(self):
        verdict, calls = self._resolve(
            domains={"web-app-moodle": "moodle.example"},
            enabled=True,
            mode="letsencrypt",
            services={"agent-broker": {"ca_client": True}},
            tls_mode="self_signed",
            peer_mode="letsencrypt",
        )
        self.assertIs(
            verdict,
            False,
            "an app that has a domain is served over its own resolved mode, which "
            "may override the deployment default; the ca_client answer comes from "
            "the issuer's resolved mode, never from the global TLS_MODE",
        )
        self.assertEqual(
            [name for name, _ in calls],
            ["domains", "tls", "tls", "config", "tls", "tls"],
        )

    def test_an_onion_served_ca_client_gets_the_ca_on_the_deployment_mode(self):
        verdict, _ = self._resolve(
            domains={"web-app-moodle": "abc.onion"},
            enabled=False,
            mode="self_signed",
            services={"api": {"ca_client": True}},
            tls_mode="self_signed",
            issuers=(),
        )
        self.assertIs(
            verdict,
            True,
            "resolve_enabled returns False for a .onion primary, so an onion app "
            "has a domain and no TLS of its own; without the CA its outbound call "
            "to a self-signed endpoint dies at the handshake",
        )

    def test_an_onion_served_app_without_the_declaration_still_gets_nothing(self):
        verdict, _ = self._resolve(
            domains={"web-app-moodle": "abc.onion"},
            enabled=False,
            mode="self_signed",
            services={"api": {}},
            tls_mode="self_signed",
        )
        self.assertIs(verdict, False)

    def test_a_ca_client_gets_nothing_when_the_ca_is_not_self_signed(self):
        verdict, _ = self._resolve(
            domains={},
            enabled=True,
            mode="self_signed",
            services={"agent-broker": {"ca_client": True}},
            tls_mode="letsencrypt",
            issuers=(),
        )
        self.assertIs(verdict, False)

    def test_a_ca_client_with_its_own_letsencrypt_still_trusts_a_self_signed_issuer(
        self,
    ):
        verdict, _ = self._resolve(
            domains={"web-app-matrix": "matrix.example"},
            enabled=True,
            mode="letsencrypt",
            app="web-app-matrix",
            services={"matrix": {"ca_client": True}},
        )
        self.assertIs(
            verdict,
            True,
            "a client served over its own letsencrypt certificate still calls the "
            "issuer, whose per-app override may be self-signed",
        )

    def test_an_onion_only_ca_client_gets_the_ca_from_a_self_signed_issuer(self):
        verdict, _ = self._resolve(
            domains={"web-app-matrix": "matrix.example.onion"},
            enabled=False,
            mode="off",
            app="web-app-matrix",
            services={"matrix": {"ca_client": True}},
        )
        self.assertIs(
            verdict,
            True,
            "an onion-only role has no TLS of its own but still calls the "
            "self-signed clearnet issuer",
        )

    def test_a_ca_client_gets_nothing_when_the_issuer_serves_no_tls(self):
        verdict, _ = self._resolve(
            domains={"web-app-matrix": "matrix.example.onion"},
            enabled=False,
            mode="off",
            app="web-app-matrix",
            services={"matrix": {"ca_client": True}},
            peer_enabled=False,
            peer_mode="off",
            tls_mode="letsencrypt",
        )
        self.assertIs(
            verdict,
            False,
            "on a tor-only node the issuer is served over plain http, so there is "
            "no self-signed endpoint to trust",
        )

    def test_a_ca_client_gets_nothing_when_the_issuer_is_not_self_signed(self):
        verdict, _ = self._resolve(
            domains={},
            enabled=True,
            mode="self_signed",
            services={"agent-broker": {"ca_client": True}},
            peer_mode="letsencrypt",
            tls_mode="letsencrypt",
        )
        self.assertIs(verdict, False)

    def test_a_ca_client_without_an_issuer_gets_nothing(self):
        verdict, _ = self._resolve(
            domains={},
            enabled=True,
            mode="self_signed",
            services={"agent-broker": {"ca_client": True}},
            issuers=(),
            tls_mode="letsencrypt",
        )
        self.assertIs(verdict, False)

    def test_a_ca_client_keeps_the_refusal_of_an_unresolvable_issuer_mode(self):
        with self.assertRaises(
            AnsibleError,
            msg="a missing mode read as 'not self signed' withholds the CA in "
            "silence, and every handshake then fails far from here",
        ):
            self._resolve(
                domains={},
                enabled=True,
                mode="self_signed",
                services={"agent-broker": {"ca_client": True}},
                peer_mode=AnsibleError("tls: required variable 'TLS_MODE' is missing"),
            )

    def test_a_ca_client_refuses_an_absent_tls_mode(self):
        with self.assertRaises(
            AnsibleError,
            msg="a missing mode read as 'not self signed' withholds the CA in "
            "silence, and every handshake then fails far from here",
        ):
            self._resolve(
                domains={},
                enabled=True,
                mode="self_signed",
                services={"agent-broker": {"ca_client": True}},
                issuers=(),
                tls_mode=None,
            )

    def test_the_term_is_required(self):
        plugin = self.mod.LookupModule()
        plugin._templar = _DummyTemplar()
        with self.assertRaises(AnsibleError):
            plugin.run([], variables={})
        with self.assertRaises(AnsibleError):
            plugin.run(["  "], variables={})


if __name__ == "__main__":
    unittest.main()
