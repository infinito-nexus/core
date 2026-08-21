import unittest
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

from plugins.lookup.container_extra_hosts import LookupModule

ONION = "auth." + "b" * 56 + ".onion"


class TestContainerExtraHostsLookup(unittest.TestCase):
    def setUp(self):
        self.lookup = LookupModule()

        def _get(name, *args, **kwargs):
            plugin = MagicMock()

            def _run(terms, variables=None, **_kwargs):
                vars_ = variables or {}
                if name == "config":
                    return [vars_.get("_sso_enabled", False)]
                if name == "tls":
                    return [vars_.get("_provider_domain", "")]
                raise AssertionError(f"unexpected lookup '{name}'")

            plugin.run.side_effect = _run
            return plugin

        patcher = patch(
            "plugins.lookup.container_extra_hosts.lookup_loader.get", side_effect=_get
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, extra_hosts=None, **overrides):
        variables = {
            "application_id": "web-app-espocrm",
            "_sso_enabled": True,
            "_provider_domain": ONION,
            "DEPLOYMENT_MODE": "compose",
        }
        variables.update(overrides)
        kwargs = {} if extra_hosts is None else {"extra_hosts": extra_hosts}
        return self.lookup.run(None, variables=variables, **kwargs)[0]

    def test_compose_pins_the_provider_to_the_host_gateway(self):
        self.assertEqual(
            self._run(),
            'extra_hosts:\n  - "host.docker.internal:host-gateway"\n'
            f'  - "{ONION}:host-gateway"',
        )

    def test_swarm_pins_the_provider_to_the_node_address(self):
        block = self._run(
            DEPLOYMENT_MODE="swarm",
            ansible_facts={"default_ipv4": {"address": "10.0.0.7"}},
        )
        self.assertIn(f'  - "{ONION}:10.0.0.7"', block)
        self.assertNotIn(f"{ONION}:host-gateway", block)

    def test_docker_internal_alias_is_always_present(self):
        self.assertIn('  - "host.docker.internal:host-gateway"', self._run())

    def test_sso_disabled_emits_nothing(self):
        self.assertEqual(self._run(_sso_enabled=False), "")

    def test_clearnet_provider_emits_nothing(self):
        self.assertEqual(self._run(_provider_domain="auth.example.org"), "")

    def test_onion_substring_that_is_not_the_suffix_emits_nothing(self):
        self.assertEqual(self._run(_provider_domain="auth.onion.example.org"), "")

    def test_empty_provider_domain_emits_nothing(self):
        self.assertEqual(self._run(_provider_domain=""), "")

    def test_compose_mode_force_overrides_the_cluster_mode(self):
        block = self._run(compose_mode_force="compose", DEPLOYMENT_MODE="swarm")
        self.assertIn(f'  - "{ONION}:host-gateway"', block)

    def test_deployment_mode_is_used_without_an_override(self):
        block = self._run(
            compose_mode_force="",
            DEPLOYMENT_MODE="swarm",
            ansible_facts={"default_ipv4": {"address": "10.0.0.8"}},
        )
        self.assertIn(f'  - "{ONION}:10.0.0.8"', block)

    def test_absent_deployment_mode_defaults_to_compose(self):
        variables = {
            "application_id": "web-app-espocrm",
            "_sso_enabled": True,
            "_provider_domain": ONION,
        }
        block = self.lookup.run(None, variables=variables)[0]
        self.assertIn(f'  - "{ONION}:host-gateway"', block)

    def test_swarm_without_facts_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(DEPLOYMENT_MODE="swarm")

    def test_positional_terms_raise(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-espocrm"], variables={})

    def test_missing_application_id_raises(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(None, variables={})

    def test_application_id_kwarg_overrides_the_play_var(self):
        seen = []

        def _get(name, *args, **kwargs):
            plugin = MagicMock()

            def _run(terms, variables=None, **_kwargs):
                if name == "config":
                    seen.append(terms[0])
                    return [False]
                return [""]

            plugin.run.side_effect = _run
            return plugin

        with patch(
            "plugins.lookup.container_extra_hosts.lookup_loader.get", side_effect=_get
        ):
            self.lookup.run(
                None,
                variables={"application_id": "web-app-joomla"},
                application_id="web-app-penpot",
            )
        self.assertEqual(seen, ["web-app-penpot"])

    def test_caller_entries_alone_emit_a_block_without_sso(self):
        self.assertEqual(
            self._run(_sso_enabled=False, extra_hosts=["seaweedfs.example:1.2.3.4"]),
            'extra_hosts:\n  - "seaweedfs.example:1.2.3.4"',
        )

    def test_caller_entries_are_appended_after_the_sso_pins(self):
        block = self._run(extra_hosts=["db.example:10.0.0.9"])
        self.assertEqual(
            block.splitlines(),
            [
                "extra_hosts:",
                '  - "host.docker.internal:host-gateway"',
                f'  - "{ONION}:host-gateway"',
                '  - "db.example:10.0.0.9"',
            ],
        )

    def test_a_bare_string_is_accepted(self):
        self.assertIn(
            '  - "one.example:192.0.2.1"',
            self._run(_sso_enabled=False, extra_hosts="one.example:192.0.2.1"),
        )

    def test_duplicates_collapse_in_first_seen_order(self):
        block = self._run(
            extra_hosts=["host.docker.internal:host-gateway", "db.example:10.0.0.9"]
        )
        self.assertEqual(block.count("host.docker.internal"), 1)
        self.assertEqual(
            block.splitlines()[1], '  - "host.docker.internal:host-gateway"'
        )

    def test_empty_entries_are_dropped(self):
        self.assertEqual(
            self._run(_sso_enabled=False, extra_hosts=["", None, "  "]), ""
        )

    def test_entry_without_a_separator_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(_sso_enabled=False, extra_hosts=["no-address-here"])

    def test_no_sources_at_all_emit_nothing(self):
        self.assertEqual(self._run(_sso_enabled=False, extra_hosts=[]), "")


if __name__ == "__main__":
    unittest.main()
