# nocheck: comments-valid  explanatory WHY-comments predate the stricter lint
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.applications import LookupModule as ApplicationsLookup
from plugins.lookup.email import RESOLUTION_ORDER, LookupModule, provider_view_carrier
from utils.cache import _reset_cache_for_tests
from utils.cache import applications as cache_applications
from utils.cache import base as cache_base
from utils.cache import users as cache_users
from utils.cache.carrier import APPLICATIONS_RENDERED_FACT, PROVIDER_VIEW_RENDERED_FACT
from utils.cache.yaml import dump_yaml_str
from utils.roles.mapping import ROLE_FILE_META_DOMAINS, ROLE_FILE_META_SERVICES


def _write_role_config(base_dir: Path, role_name: str, payload: dict) -> None:
    config_path = base_dir / "roles" / role_name / ROLE_FILE_META_SERVICES
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(dump_yaml_str(payload), encoding="utf-8")


class TestEmailLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _reset_cache_for_tests()
        cls.addClassCleanup(_reset_cache_for_tests)

    def setUp(self) -> None:
        cache_base._reset()
        self.lookup = LookupModule()
        self.lookup._templar = None
        self._cwd = str(Path.cwd())
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmpdir.name)
        (self._tmp / "roles").mkdir(parents=True, exist_ok=True)
        os.chdir(self._tmp)
        self._tokens_store_patcher = patch.object(
            cache_users, "_load_store_users", return_value={}
        )
        self._tokens_store_patcher.start()

    def tearDown(self) -> None:
        self._tokens_store_patcher.stop()
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_returns_plugin_defaults_when_no_vars(self) -> None:
        result = self.lookup.run([], variables={"inventory_hostname": "host1"})[0]
        self.assertTrue(result["enabled"])
        self.assertEqual(result["host"], "localhost")
        self.assertEqual(result["port"], 25)
        self.assertEqual(result["from"], "root@host1.localdomain")
        self.assertEqual(result["username"], "root@host1.localdomain")
        self.assertEqual(result["password"], "")
        self.assertFalse(result["tls"])
        self.assertFalse(result["auth"])
        self.assertTrue(result["smtp"])

    def test_host_is_localhost_when_not_external_under_tls(self) -> None:
        result = self.lookup.run(
            [],
            variables={"inventory_hostname": "host1", "TLS_ENABLED": True},
        )[0]
        self.assertEqual(result["host"], "localhost")
        self.assertFalse(result["auth"])
        self.assertFalse(result["tls"])

    def test_keys_are_lowercased_without_prefix(self) -> None:
        result = self.lookup.run([], variables={})[0]
        for key in result:
            self.assertFalse(key.startswith("SYSTEM_EMAIL_"))
            self.assertEqual(key, key.lower())

    def test_group_var_overrides_plugin_default(self) -> None:
        variables = {
            "SYSTEM_EMAIL_HOST": "smtp.example.org",
            "SYSTEM_EMAIL_PORT": 465,
            "SYSTEM_EMAIL_TLS": True,
            "inventory_hostname": "host1",
        }
        result = self.lookup.run([], variables=variables)[0]
        self.assertEqual(result["host"], "smtp.example.org")
        self.assertEqual(result["port"], 465)
        self.assertTrue(result["tls"])
        self.assertEqual(result["from"], "root@host1.localdomain")

    def test_onion_domain_disables_tls_but_keeps_auth(self) -> None:
        """An onion mail host has no TLS certificate, so the relay speaks
        plaintext — Tor already encrypts the transport. AUTH must survive that:
        without credentials the message reaches Mailu unauthenticated with a
        local envelope sender, and rspamd's antispoof rule rejects it with
        554 5.7.1. Plaintext submission is port 587; 25 is the inbound MX and
        offers no AUTH at all."""
        variables = {
            "MAIL_PROVIDER": "web-app-mailu",
            "groups": {"web-app-mailu": ["host1"]},
            "SYSTEM_EMAIL_HOST": "mail.abc123.onion",
            "TLS_ENABLED": True,
            "DOMAIN_PRIMARY": "abc123.onion",
            "inventory_hostname": "host1",
        }
        result = self.lookup.run([], variables=variables)[0]
        self.assertFalse(result["tls"])
        self.assertTrue(result["auth"])
        self.assertEqual(result["port"], 587)

    def test_clearnet_external_keeps_tls(self) -> None:
        variables = {
            "MAIL_PROVIDER": "web-app-mailu",
            "groups": {"web-app-mailu": ["host1"]},
            "SYSTEM_EMAIL_HOST": "mail.example.org",
            "TLS_ENABLED": True,
            "DOMAIN_PRIMARY": "example.org",
            "inventory_hostname": "host1",
        }
        result = self.lookup.run([], variables=variables)[0]
        self.assertTrue(result["tls"])
        self.assertEqual(result["port"], 465)

    def test_the_axis_matrix_stays_where_it_was_measured(self) -> None:
        """Decoupling auth from tls may only move the two cases it was meant to.

        The clearnet default and the local relay must render byte-identically,
        or a change aimed at the onion has silently reached every deploy."""
        cases = [
            ("mail.example.org", True, True, {"tls": True, "auth": True, "port": 465}),
            (
                "mail.example.org",
                False,
                True,
                {"tls": False, "auth": True, "port": 587},
            ),
            ("mail.x.onion", True, True, {"tls": False, "auth": True, "port": 587}),
            (
                "mail.example.org",
                True,
                False,
                {"tls": False, "auth": False, "port": 25},
            ),
        ]
        for host, tls_enabled, external, expected in cases:
            with self.subTest(host=host, tls=tls_enabled, external=external):
                variables = {
                    "MAIL_PROVIDER": "web-app-mailu",
                    "groups": {"web-app-mailu": ["host1"]} if external else {},
                    "SYSTEM_EMAIL_HOST": host,
                    "TLS_ENABLED": tls_enabled,
                    "DOMAIN_PRIMARY": host.split(".", 1)[1],
                    "inventory_hostname": "host1",
                }
                result = self.lookup.run([], variables=variables)[0]
                for key, value in expected.items():
                    self.assertEqual(
                        bool(result[key]) if key != "port" else result[key], value
                    )

    def test_auth_mechanism_is_named_only_where_msmtp_would_refuse(self) -> None:
        """msmtp aborts with EX_UNAVAILABLE when it has to pick a mechanism
        itself on a cleartext link, so the onion relay needs PLAIN spelled out.
        The TLS and the no-relay cases must keep rendering on and off, or the
        change reaches deploys it was never meant to touch."""
        cases = [
            ("mail.example.org", True, True, "on"),
            ("mail.x.onion", True, True, "plain"),
            ("mail.example.org", True, False, "off"),
        ]
        for host, tls_enabled, external, expected in cases:
            with self.subTest(host=host, external=external):
                variables = {
                    "MAIL_PROVIDER": "web-app-mailu",
                    "groups": {"web-app-mailu": ["host1"]} if external else {},
                    "SYSTEM_EMAIL_HOST": host,
                    "TLS_ENABLED": tls_enabled,
                    "DOMAIN_PRIMARY": host.split(".", 1)[1],
                    "inventory_hostname": "host1",
                }
                result = self.lookup.run([], variables=variables)[0]
                self.assertEqual(result["auth_mechanism"], expected)

    def test_empty_string_falls_back_to_plugin_default(self) -> None:
        variables = {
            "SYSTEM_EMAIL_HOST": "",
            "inventory_hostname": "host1",
        }
        result = self.lookup.run([], variables=variables)[0]
        self.assertEqual(result["host"], "localhost")

    def test_application_override_wins_over_defaults(self) -> None:
        # Per the file root of meta/services.yml IS the services map
        # (no `compose.services` envelope).
        _write_role_config(
            self._tmp,
            "web-app-x",
            {"email": {"host": "smtp.app.org", "port": 587}},
        )
        variables = {
            "SYSTEM_EMAIL_HOST": "smtp.global.org",
            "SYSTEM_EMAIL_PORT": 25,
            "inventory_hostname": "host1",
        }
        result = self.lookup.run(
            ["web-app-x"],
            variables=variables,
            roles_dir=str(self._tmp / "roles"),
        )[0]
        self.assertEqual(result["host"], "smtp.app.org")
        self.assertEqual(result["port"], 587)
        self.assertEqual(result["from"], "root@host1.localdomain")

    def test_missing_application_returns_defaults(self) -> None:
        variables = {
            "SYSTEM_EMAIL_HOST": "smtp.global.org",
            "inventory_hostname": "host1",
        }
        result = self.lookup.run(
            ["web-app-unknown"],
            variables=variables,
            roles_dir=str(self._tmp / "roles"),
        )[0]
        self.assertEqual(result["host"], "smtp.global.org")

    def test_application_without_email_service_returns_defaults(self) -> None:
        _write_role_config(
            self._tmp,
            "web-app-nomail",
            {"logout": {"enabled": True}},
        )
        variables = {
            "SYSTEM_EMAIL_HOST": "smtp.global.org",
            "inventory_hostname": "host1",
        }
        result = self.lookup.run(
            ["web-app-nomail"],
            variables=variables,
            roles_dir=str(self._tmp / "roles"),
        )[0]
        self.assertEqual(result["host"], "smtp.global.org")

    def test_too_many_terms_raises(self) -> None:
        with self.assertRaises(AnsibleError):
            self.lookup.run(["a", "b"], variables={})

    def test_an_onion_relay_never_announces_starttls(self) -> None:
        # No CA issues a certificate for a .onion name, so a client that
        # verifies the peer can never complete the handshake -- Ruby's
        # Net::SMTP drops the mail after three silent retries. Tor already
        # carries the confidentiality, which is why `tls` is False here too.
        _write_role_config(
            self._tmp,
            "web-app-mailprov",
            {"sso": {"enabled": True}},
        )
        variables = {
            "MAIL_PROVIDER": "web-app-mailprov",
            "group_names": ["web-app-mailprov", "web-app-keycloak"],
            "groups": {"web-app-mailprov": ["host1"], "web-app-keycloak": ["host1"]},
            "TLS_ENABLED": True,
            "SYSTEM_EMAIL_HOST": "mail." + "a" * 56 + ".onion",
            "inventory_hostname": "host1",
        }
        result = self.lookup.run(
            [], variables=variables, roles_dir=str(self._tmp / "roles")
        )[0]
        self.assertFalse(result["start_tls"])
        self.assertFalse(result["tls"])

    def test_a_provider_behind_sso_keeps_authenticated_submission(self) -> None:
        _write_role_config(
            self._tmp,
            "web-app-mailprov",
            {"sso": {"enabled": True}},
        )
        variables = {
            "MAIL_PROVIDER": "web-app-mailprov",
            "group_names": ["web-app-mailprov", "web-app-keycloak"],
            "groups": {"web-app-mailprov": ["host1"], "web-app-keycloak": ["host1"]},
            "TLS_ENABLED": True,
            "inventory_hostname": "host1",
        }
        result = self.lookup.run(
            [], variables=variables, roles_dir=str(self._tmp / "roles")
        )[0]
        self.assertEqual(result["port"], 465)
        self.assertTrue(result["auth"])
        self.assertEqual(result["auth_mechanism"], "on")
        self.assertFalse(result["start_tls"])

    def test_a_provider_without_plaintext_submission_falls_back_to_its_mx(
        self,
    ) -> None:
        """Stalwart's default config binds the implicit-TLS client ports and the
        MX, never 587, so the onion path (which drops TLS) has no submission
        listener to reach. The port follows what the provider declares, and AUTH
        drops with it: an MX offers none, and announcing it aborts msmtp with
        EX_UNAVAILABLE before a message is ever sent."""
        _write_role_config(
            self._tmp,
            "web-app-mailprov",
            {"mailprov": {"ports": {"public": {"smtp": 25, "smtps": 465}}}},
        )
        variables = {
            "MAIL_PROVIDER": "web-app-mailprov",
            "group_names": ["web-app-mailprov"],
            "groups": {"web-app-mailprov": ["host1"]},
            "SYSTEM_EMAIL_HOST": "mail.x.onion",
            "TLS_ENABLED": True,
            "DOMAIN_PRIMARY": "x.onion",
            "inventory_hostname": "host1",
        }
        result = self.lookup.run(
            [], variables=variables, roles_dir=str(self._tmp / "roles")
        )[0]
        self.assertFalse(result["tls"])
        self.assertEqual(result["port"], 25)
        self.assertFalse(result["auth"])
        self.assertEqual(result["auth_mechanism"], "off")

    def test_a_provider_declaring_submission_keeps_the_authenticated_path(
        self,
    ) -> None:
        """Mailu binds 587, so the same onion target stays on plaintext
        submission with AUTH PLAIN. The MX fallback above must not reach a
        provider that declares a submission listener."""
        _write_role_config(
            self._tmp,
            "web-app-mailprov",
            {
                "mailprov": {
                    "ports": {"public": {"smtp": 25, "smtps": 465, "submission": 587}}
                }
            },
        )
        variables = {
            "MAIL_PROVIDER": "web-app-mailprov",
            "group_names": ["web-app-mailprov"],
            "groups": {"web-app-mailprov": ["host1"]},
            "SYSTEM_EMAIL_HOST": "mail.x.onion",
            "TLS_ENABLED": True,
            "DOMAIN_PRIMARY": "x.onion",
            "inventory_hostname": "host1",
        }
        result = self.lookup.run(
            [], variables=variables, roles_dir=str(self._tmp / "roles")
        )[0]
        self.assertFalse(result["tls"])
        self.assertEqual(result["port"], 587)
        self.assertTrue(result["auth"])
        self.assertEqual(result["auth_mechanism"], "plain")

    def test_computed_defaults_are_templated(self) -> None:
        self.lookup._templar = _DummyTemplar(
            {"DOMAIN_PRIMARY_RESOLVED": "mail.example.org"}
        )
        variables = {
            "DOMAIN_PRIMARY": "{{ DOMAIN_PRIMARY_RESOLVED }}",
            "inventory_hostname": "host1",
        }
        result = self.lookup.run([], variables=variables)[0]
        self.assertEqual(result["domain"], "mail.example.org")

    def test_key_returns_the_value_the_full_mapping_carries(self) -> None:
        _write_role_config(
            self._tmp,
            "web-app-mailprov",
            {
                "mailprov": {
                    "ports": {"public": {"smtp": 25, "smtps": 465, "submission": 587}}
                }
            },
        )
        cases = (
            {"inventory_hostname": "host1"},
            {"inventory_hostname": "host1", "TLS_ENABLED": True},
            {
                "SYSTEM_EMAIL_HOST": "smtp.example.org",
                "SYSTEM_EMAIL_PORT": 465,
                "SYSTEM_EMAIL_TLS": True,
                "SYSTEM_EMAIL_TIMEOUT": "45",
                "inventory_hostname": "host1",
            },
            {
                "MAIL_PROVIDER": "web-app-mailprov",
                "group_names": ["web-app-mailprov"],
                "groups": {"web-app-mailprov": ["host1"]},
                "SYSTEM_EMAIL_HOST": "mail.x.onion",
                "TLS_ENABLED": True,
                "DOMAIN_PRIMARY": "x.onion",
                "inventory_hostname": "host1",
            },
        )
        roles_dir = str(self._tmp / "roles")
        for variables in cases:
            full = self.lookup.run([], variables=variables, roles_dir=roles_dir)[0]
            for short_key in RESOLUTION_ORDER:
                with self.subTest(variables=variables, key=short_key):
                    value = self.lookup.run(
                        [], variables=variables, roles_dir=roles_dir, key=short_key
                    )[0]
                    self.assertEqual(value, full[short_key])

    def test_key_applies_the_application_override(self) -> None:
        _write_role_config(
            self._tmp,
            "web-app-x",
            {"email": {"HOST": "smtp.app.org", "port": 587}},
        )
        variables = {
            "SYSTEM_EMAIL_HOST": "smtp.global.org",
            "SYSTEM_EMAIL_PORT": 25,
            "inventory_hostname": "host1",
        }
        roles_dir = str(self._tmp / "roles")
        full = self.lookup.run(["web-app-x"], variables=variables, roles_dir=roles_dir)[
            0
        ]
        for short_key in ("host", "port", "external", "from"):
            with self.subTest(key=short_key):
                value = self.lookup.run(
                    ["web-app-x"],
                    variables=variables,
                    roles_dir=roles_dir,
                    key=short_key,
                )[0]
                self.assertEqual(value, full[short_key])
        self.assertEqual(full["host"], "smtp.app.org")
        self.assertEqual(full["port"], 587)

    def test_unknown_key_raises(self) -> None:
        with self.assertRaises(AnsibleError):
            self.lookup.run([], variables={}, key="externl")


class TestProviderOnionIsClusterWide(unittest.TestCase):
    """In swarm only the manager is in svc-net-tor, so a worker renders the
    provider's clearnet name while the provider (onion-primary on the
    manager) never deployed a certificate for it. TLS must follow the
    provider host's view, not the worker's."""

    ONION = "a" * 56 + ".onion"
    TOR_ON = "{{ 'svc-net-tor' in group_names }}"
    STALWART_PORTS: ClassVar[dict[str, int]] = {"smtp": 25, "smtps": 465}
    MAILU_PORTS: ClassVar[dict[str, int]] = {
        "smtp": 25,
        "smtps": 465,
        "submission": 587,
    }

    @classmethod
    def setUpClass(cls) -> None:
        _reset_cache_for_tests()
        cls.addClassCleanup(_reset_cache_for_tests)

    def setUp(self) -> None:
        from ansible.parsing.dataloader import DataLoader
        from ansible.template import Templar

        cache_base._reset()
        _reset_cache_for_tests()
        self.lookup = LookupModule()
        self.lookup._templar = Templar(loader=DataLoader(), variables={})
        self._cwd = str(Path.cwd())
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmpdir.name)
        (self._tmp / "roles").mkdir(parents=True, exist_ok=True)
        os.chdir(self._tmp)
        self._tokens_store_patcher = patch.object(
            cache_users, "_load_store_users", return_value={}
        )
        self._tokens_store_patcher.start()

    def tearDown(self) -> None:
        self._tokens_store_patcher.stop()
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def _seed(self, *, ports, node=None, provider_tor=None) -> None:
        """Write the tor provider and the mail provider roles.

        Args:
            ports: the mail provider's published SMTP ports.
            node: svc-net-tor's node onion; defaults to ``ONION``.
            provider_tor: the mail provider's ``tor`` block; defaults to
                enabled on svc-net-tor hosts.
        """
        _write_role_config(
            self._tmp,
            "svc-net-tor",
            {
                "tor": {
                    "enabled": True,
                    "shared": True,
                    "node": self.ONION if node is None else node,
                }
            },
        )
        _write_role_config(
            self._tmp,
            "web-app-mailprov",
            {
                "mailprov": {"ports": {"public": ports}},
                "tor": provider_tor or {"enabled": self.TOR_ON},
            },
        )
        domains = self._tmp / "roles" / "web-app-mailprov" / ROLE_FILE_META_DOMAINS
        domains.write_text(
            dump_yaml_str({"canonical": {"mail": "mail.x.test"}, "aliases": []}),
            encoding="utf-8",
        )

    def _worker(self, *, tor_hosts=("mgr",), network_mode="") -> dict:
        manager = {"group_names": ["web-app-mailprov", "svc-net-tor"]}
        if network_mode:
            manager["NETWORK_MODE"] = network_mode
        return {
            "MAIL_PROVIDER": "web-app-mailprov",
            "group_names": ["svc-swarm-node"],
            "groups": {
                "web-app-mailprov": ["mgr"],
                "svc-net-tor": list(tor_hosts),
            },
            "hostvars": {
                "mgr": manager,
                "other": {"group_names": ["svc-net-tor"]},
            },
            "SYSTEM_EMAIL_HOST": "mail.x.test",
            "TLS_ENABLED": True,
            "DOMAIN_PRIMARY": "x.test",
            "inventory_hostname": "wrk",
        }

    def _run(self, variables: dict) -> dict:
        return self.lookup.run(
            [], variables=variables, roles_dir=str(self._tmp / "roles")
        )[0]

    def test_worker_of_an_onion_stalwart_drops_tls_and_auth(self) -> None:
        self._seed(ports=self.STALWART_PORTS)

        result = self._run(self._worker(network_mode="tor"))

        self.assertFalse(result["tls"])
        self.assertFalse(result["start_tls"])
        self.assertFalse(result["auth"])
        self.assertEqual(result["port"], 25)

    def test_worker_of_an_onion_mailu_keeps_plain_submission(self) -> None:
        self._seed(ports=self.MAILU_PORTS)

        result = self._run(self._worker(network_mode="tor"))

        self.assertFalse(result["tls"])
        self.assertEqual(result["port"], 587)
        self.assertTrue(result["auth"])
        self.assertEqual(result["auth_mechanism"], "plain")

    def test_worker_key_lookup_skips_the_provider_onion_probe(self) -> None:
        self._seed(ports=self.STALWART_PORTS)
        variables = self._worker(network_mode="tor")
        roles_dir = str(self._tmp / "roles")

        with patch.object(
            LookupModule, "_provider_onion_primary", return_value=True
        ) as probe:
            external = self.lookup.run(
                [], variables=variables, roles_dir=roles_dir, key="external"
            )[0]
            timeout = self.lookup.run(
                [], variables=variables, roles_dir=roles_dir, key="timeout"
            )[0]
            probe.assert_not_called()
            full = self._run(variables)
            probe.assert_called()

        self.assertIs(external, True)
        self.assertEqual(external, full["external"])
        self.assertEqual(timeout, full["timeout"])

    def test_tor_on_another_host_keeps_tls(self) -> None:
        self._seed(ports=self.STALWART_PORTS)

        result = self._run(self._worker(tor_hosts=("other",)))

        self.assertTrue(result["tls"])
        self.assertEqual(result["port"], 465)

    def test_dual_stack_provider_keeps_tls(self) -> None:
        self._seed(ports=self.STALWART_PORTS)

        result = self._run(self._worker())

        self.assertTrue(result["tls"])

    def test_empty_tor_node_keeps_tls(self) -> None:
        self._seed(ports=self.STALWART_PORTS, node="")

        result = self._run(self._worker())

        self.assertTrue(result["tls"])

    def _park(self, variables: dict) -> dict:
        lookup = ApplicationsLookup()
        lookup._templar = self.lookup._templar
        return lookup.run(
            [], variables=variables, roles_dir=str(self._tmp / "roles"), carrier=True
        )[0]

    def _provider_view(self, worker: dict, **overrides) -> dict:
        manager = worker["hostvars"]["mgr"]
        view = dict(worker, inventory_hostname="mgr")
        view["group_names"] = manager["group_names"]
        if manager.get("NETWORK_MODE"):
            view["NETWORK_MODE"] = manager["NETWORK_MODE"]
        view.update(overrides)
        return view

    def _worker_with_carrier(self) -> dict:
        worker = self._worker(network_mode="tor")
        worker[APPLICATIONS_RENDERED_FACT] = self._park(worker)
        return worker

    def _run_counting_renders(self, worker: dict) -> tuple[dict, int]:
        _reset_cache_for_tests()
        with patch.object(
            cache_applications,
            "_render_with_templar",
            wraps=cache_applications._render_with_templar,
        ) as render:
            result = self._run(worker)
        return result, render.call_count

    def test_worker_reads_the_provider_view_from_the_provider_carrier(self) -> None:
        self._seed(ports=self.STALWART_PORTS)
        worker = self._worker_with_carrier()
        expected, baseline_renders = self._run_counting_renders(worker)
        worker["hostvars"]["mgr"][APPLICATIONS_RENDERED_FACT] = self._park(
            self._provider_view(worker)
        )

        result, renders = self._run_counting_renders(worker)

        self.assertEqual(baseline_renders, 1)
        self.assertEqual(renders, 0)
        self.assertEqual(result, expected)

    def test_worker_renders_when_the_provider_carrier_key_differs(self) -> None:
        self._seed(ports=self.STALWART_PORTS)
        worker = self._worker_with_carrier()
        expected, _ = self._run_counting_renders(worker)
        worker["hostvars"]["mgr"][APPLICATIONS_RENDERED_FACT] = self._park(
            self._provider_view(worker, group_names=["web-app-mailprov"])
        )

        result, renders = self._run_counting_renders(worker)

        self.assertGreater(renders, 0)
        self.assertEqual(result, expected)
        self.assertFalse(result["tls"])

    def test_worker_reads_the_provider_carrier_untemplated(self) -> None:
        self._seed(ports=self.STALWART_PORTS)
        worker = self._worker_with_carrier()
        expected, _ = self._run_counting_renders(worker)
        raw = {
            "mgr": dict(
                worker["hostvars"]["mgr"],
                **{APPLICATIONS_RENDERED_FACT: self._park(self._provider_view(worker))},
            )
        }
        worker["hostvars"] = _RawGetHostvars(worker["hostvars"], raw)

        result, renders = self._run_counting_renders(worker)

        self.assertEqual(renders, 0)
        self.assertEqual(result, expected)

    MESH: ClassVar[dict[str, str]] = {
        "mgr": "10.13.0.1",
        "wrk": "10.13.0.2",
        "wrk2": "10.13.0.3",
    }

    def _mesh_apps(self, host: str) -> dict:
        return {
            "svc-net-wireguard": {
                "networks": {"interfaces": [{"host": host, "address": self.MESH[host]}]}
            }
        }

    def _mesh_worker(self, *, host: str = "wrk", network_mode: str = "tor") -> dict:
        """A worker with its own mesh interface in ``applications``.

        Args:
            host: the worker's inventory hostname.
            network_mode: the manager's ``NETWORK_MODE``.
        """
        _write_role_config(
            self._tmp, "svc-net-wireguard", {"wireguard": {"enabled": True}}
        )
        worker = self._worker(network_mode=network_mode)
        worker["inventory_hostname"] = host
        worker["applications"] = self._mesh_apps(host)
        worker["hostvars"]["mgr"]["applications"] = self._mesh_apps("mgr")
        return worker

    def _park_manager_carrier(self, worker: dict) -> None:
        worker["hostvars"]["mgr"][APPLICATIONS_RENDERED_FACT] = self._park(
            self._provider_view(worker, applications=self._mesh_apps("mgr"))
        )

    def _park_provider_view(self, worker: dict) -> dict | None:
        return provider_view_carrier(
            worker,
            templar=self.lookup._templar,
            roles_dir=str(self._tmp / "roles"),
        )

    def test_a_mesh_worker_renders_the_provider_view_the_manager_carrier_misses(
        self,
    ) -> None:
        self._seed(ports=self.STALWART_PORTS)
        worker = self._mesh_worker()
        expected, _ = self._run_counting_renders(worker)
        worker[APPLICATIONS_RENDERED_FACT] = self._park(worker)
        self._park_manager_carrier(worker)

        result, renders = self._run_counting_renders(worker)

        self.assertEqual(renders, 1)
        self.assertEqual(result, expected)

    def test_a_mesh_worker_reads_the_provider_view_parked_for_it(self) -> None:
        self._seed(ports=self.STALWART_PORTS)
        worker = self._mesh_worker()
        expected, fresh_renders = self._run_counting_renders(worker)
        worker[APPLICATIONS_RENDERED_FACT] = self._park(worker)
        self._park_manager_carrier(worker)
        _reset_cache_for_tests()
        worker[PROVIDER_VIEW_RENDERED_FACT] = self._park_provider_view(worker)

        result, renders = self._run_counting_renders(worker)

        self.assertGreater(fresh_renders, 0)
        self.assertIsNotNone(worker[PROVIDER_VIEW_RENDERED_FACT])
        self.assertEqual(renders, 0)
        for key in RESOLUTION_ORDER:
            self.assertEqual(result[key], expected[key], key)
        self.assertEqual(result, expected)
        self.assertFalse(result["tls"])
        self.assertIsNone(self._park_provider_view(worker))

    def test_a_provider_view_parked_for_another_view_is_never_served(self) -> None:
        self._seed(ports=self.STALWART_PORTS)
        worker = self._mesh_worker()
        worker[APPLICATIONS_RENDERED_FACT] = self._park(worker)
        worker[PROVIDER_VIEW_RENDERED_FACT] = self._park_provider_view(worker)
        onion, onion_renders = self._run_counting_renders(worker)
        dual_stack = self._mesh_worker(network_mode="")
        other_worker = self._mesh_worker(host="wrk2")
        expected = {
            "dual_stack": self._run_counting_renders(dual_stack)[0],
            "other_worker": self._run_counting_renders(other_worker)[0],
        }
        stale = {"dual_stack": dual_stack, "other_worker": other_worker}
        for variables in stale.values():
            variables[APPLICATIONS_RENDERED_FACT] = self._park(variables)
            variables[PROVIDER_VIEW_RENDERED_FACT] = worker[PROVIDER_VIEW_RENDERED_FACT]

        results = {name: self._run_counting_renders(v) for name, v in stale.items()}

        self.assertEqual(onion_renders, 0)
        self.assertFalse(onion["tls"])
        for name, (result, renders) in results.items():
            self.assertEqual(renders, 1, name)
            for key in RESOLUTION_ORDER:
                self.assertEqual(result[key], expected[name][key], (name, key))
        self.assertTrue(results["dual_stack"][0]["tls"])

    def test_the_provider_host_and_a_clearnet_provider_park_no_view(self) -> None:
        self._seed(ports=self.STALWART_PORTS)
        provider_host = self._provider_view(
            self._mesh_worker(), applications=self._mesh_apps("mgr")
        )
        clearnet = self._mesh_worker()
        clearnet["groups"] = dict(clearnet["groups"], **{"svc-net-tor": ["other"]})

        with patch.object(
            cache_applications,
            "_render_with_templar",
            wraps=cache_applications._render_with_templar,
        ) as render:
            parked = [self._park_provider_view(v) for v in (provider_host, clearnet)]

        self.assertEqual(parked, [None, None])
        self.assertEqual(render.call_count, 0)


class _RawGetHostvars(dict):
    def __init__(self, templated: dict, raw: dict) -> None:
        super().__init__(templated)
        self._raw = raw

    def raw_get(self, host: str) -> dict:
        return self._raw[host]


class _DummyTemplar:
    def __init__(self, available_variables: dict[str, str]) -> None:
        self.available_variables = available_variables

    def template(self, value, fail_on_undefined=False):
        if isinstance(value, str):
            rendered = value
            for key, replacement in self.available_variables.items():
                rendered = rendered.replace(f"{{{{ {key} }}}}", str(replacement))
            return rendered
        return value


if __name__ == "__main__":
    unittest.main()
