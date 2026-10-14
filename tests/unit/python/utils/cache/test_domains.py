"""Focused unit tests for ``utils.cache.domains``.

`get_merged_domains` is a thin derivation on top of
`get_merged_applications` plus the
`plugins.filter.canonical_domains_map` filter. We pin: cache-keying
behaviour, the missing-DOMAIN_PRIMARY validation, and the dispatch to
the upstream applications view.
"""

from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache import _reset_cache_for_tests
from utils.cache import domains as cache_domains
from utils.cache.base import _RENDER_GUARD
from utils.domains.default_primary import default_domain_primary
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_USERS

from . import PROJECT_ROOT

DOMAIN = default_domain_primary()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _seed_minimal_role(tmp: Path) -> Path:
    role = tmp / "roles" / "web-app-foo"
    _write(
        role / ROLE_FILE_META_SERVICES,
        """
        server:
          domains:
            canonical:
              - foo.{{ DOMAIN_PRIMARY }}
            aliases: []
        """,
    )
    _write(role / ROLE_FILE_META_USERS, "users: {}\n")
    return tmp / "roles"


class TestMissingPrimaryDomain(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_raises_when_domain_primary_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_role(Path(tmp))
            with self.assertRaisesRegex(ValueError, "DOMAIN_PRIMARY"):
                cache_domains.get_merged_domains(
                    variables={}, roles_dir=roles, templar=None
                )

    def test_falls_back_to_system_email_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_role(Path(tmp))
            with patch(
                "utils.cache.applications.get_merged_applications",
                return_value={},
            ):
                result = cache_domains.get_merged_domains(
                    variables={"SYSTEM_EMAIL_DOMAIN": DOMAIN},
                    roles_dir=roles,
                    templar=None,
                )
            self.assertIsInstance(result, dict)


class TestCachingPerVariablesSignature(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_caches_result_for_identical_variables(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_role(Path(tmp))
            with patch(
                "utils.cache.applications.get_merged_applications",
                return_value={},
            ) as mocked:
                first = cache_domains.get_merged_domains(
                    variables={"DOMAIN_PRIMARY": DOMAIN},
                    roles_dir=roles,
                    templar=None,
                )
                second = cache_domains.get_merged_domains(
                    variables={"DOMAIN_PRIMARY": DOMAIN},
                    roles_dir=roles,
                    templar=None,
                )
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(first, second)

    def test_different_domain_primary_misses_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_role(Path(tmp))
            with patch(
                "utils.cache.applications.get_merged_applications",
                return_value={},
            ) as mocked:
                cache_domains.get_merged_domains(
                    variables={"DOMAIN_PRIMARY": "a.example"},
                    roles_dir=roles,
                    templar=None,
                )
                cache_domains.get_merged_domains(
                    variables={"DOMAIN_PRIMARY": "b.example"},
                    roles_dir=roles,
                    templar=None,
                )
            self.assertEqual(mocked.call_count, 2)

    def test_a_map_built_during_the_render_never_becomes_the_finished_one(self):
        """Under the guard the applications view is still unrendered, so its
        map must not answer a later read; it may still serve the render."""
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_role(Path(tmp))
            variables = {"DOMAIN_PRIMARY": DOMAIN}
            with patch(
                "utils.cache.applications.get_merged_applications",
                return_value={},
            ) as mocked:
                _RENDER_GUARD.applications = True
                try:
                    cache_domains.get_merged_domains(
                        variables=variables, roles_dir=roles, templar=None
                    )
                    cache_domains.get_merged_domains(
                        variables=variables, roles_dir=roles, templar=None
                    )
                    self.assertEqual(mocked.call_count, 1)
                finally:
                    _RENDER_GUARD.applications = False
                cache_domains.get_merged_domains(
                    variables=variables, roles_dir=roles, templar=None
                )
                self.assertEqual(mocked.call_count, 2)
            self.assertEqual(len(cache_domains._MERGED_DOMAINS_CACHE), 2)
            self.assertEqual(
                sorted(key[-1] for key in cache_domains._MERGED_DOMAINS_CACHE),
                [False, True],
            )


class TestResetClearsDomainsCache(unittest.TestCase):
    def test_reset_evicts_cached_entry(self):
        _reset_cache_for_tests()
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_role(Path(tmp))
            with patch(
                "utils.cache.applications.get_merged_applications",
                return_value={},
            ):
                cache_domains.get_merged_domains(
                    variables={"DOMAIN_PRIMARY": DOMAIN},
                    roles_dir=roles,
                    templar=None,
                )
                self.assertEqual(len(cache_domains._MERGED_DOMAINS_CACHE), 1)
                _reset_cache_for_tests()
                self.assertEqual(len(cache_domains._MERGED_DOMAINS_CACHE), 0)


class TestImportableWithoutAnsible(unittest.TestCase):
    """`utils.cache.domains` MUST stay ansible-free at import time so
    callers in CLI/runner-host paths can pull the module without
    needing ansible. Calling `get_merged_domains` requires ansible
    transitively (via `canonical_domains_map`) and is NOT pinned here
    — the import-only invariant is what matters for the
    ansible-less host. Subprocess isolation avoids the in-process
    sys.modules / namespace-package hazards that bit earlier shims.
    """

    def test_module_imports_without_ansible(self):
        import subprocess

        repo_root = PROJECT_ROOT
        snippet = (
            "import sys\n"
            f"sys.path.insert(0, {str(repo_root)!r})\n"
            "class _Block:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name == 'ansible' or name.startswith('ansible.'):\n"
            "            raise ImportError(f'blocked: {name}')\n"
            "        return None\n"
            "sys.meta_path.insert(0, _Block())\n"
            "from utils.cache.domains import get_merged_domains\n"
            "assert callable(get_merged_domains)\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=60,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stderr=\n{result.stderr}\nstdout=\n{result.stdout}",
        )
        self.assertIn("OK", result.stdout)


class TestNetworkSiblingInjection(unittest.TestCase):
    ONION = "abc123def456ghij789klmno000pqrstuvwx111yz222abc333def444gh.onion"

    def _apps(self, enabled=True, **reachability):
        config = {"services": {"tor": {"enabled": enabled}}}
        if reachability:
            config["networks"] = {"reachability": reachability}
        return {"web-app-x": config}

    def _inject(self, apps, node_mode, *, domains=None, deployed=("web-app-x",)):
        return cache_domains._inject_network_siblings(
            {"web-app-x": domains if domains is not None else [f"x.{DOMAIN}"]},
            apps,
            DOMAIN,
            self.ONION,
            node_mode,
            deployed=list(deployed),
        )["web-app-x"]

    def test_multi_appends_onion_after_clearnet(self):
        self.assertEqual(
            self._inject(self._apps(), "multi"),
            [f"x.{DOMAIN}", f"x.{self.ONION}"],
        )

    def test_tor_mode_replaces_clearnet(self):
        self.assertEqual(self._inject(self._apps(), "tor"), [f"x.{self.ONION}"])

    def test_clearnet_mode_is_untouched(self):
        self.assertEqual(
            self._inject(self._apps(enabled=False), "clearnet"), [f"x.{DOMAIN}"]
        )

    def test_clearnet_mode_never_renders_the_tor_flag(self):
        apps = self._apps(enabled="{{ 'svc-net-tor' in group_names }}")
        self.assertEqual(self._inject(apps, "clearnet"), [f"x.{DOMAIN}"])

    def test_tor_only_role_on_clearnet_node_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, "web-app-x"):
            self._inject(self._apps(modes=["tor"]), "clearnet")

    def test_single_mode_on_multi_serves_tor(self):
        self.assertEqual(
            self._inject(self._apps(single_mode=True), "multi"), [f"x.{self.ONION}"]
        )

    def test_clearnet_only_role_on_multi_stays_clearnet(self):
        self.assertEqual(
            self._inject(self._apps(modes=["clearnet"]), "multi"), [f"x.{DOMAIN}"]
        )

    def test_disabled_tor_bond_on_multi_stays_clearnet(self):
        self.assertEqual(
            self._inject(self._apps(enabled=False), "multi"), [f"x.{DOMAIN}"]
        )

    def test_role_without_tor_bond_is_exempt_on_tor_node(self):
        apps = {"web-app-x": {"services": {}}}
        self.assertEqual(self._inject(apps, "tor"), [f"x.{DOMAIN}"])

    def test_deployed_mismatch_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, "web-app-x"):
            self._inject(self._apps(modes=["clearnet"]), "tor")

    def test_undeployed_mismatch_keeps_domains(self):
        self.assertEqual(
            self._inject(self._apps(modes=["clearnet"]), "tor", deployed=()),
            [f"x.{DOMAIN}"],
        )

    def test_bare_primary_domain_maps_to_node_onion(self):
        self.assertEqual(
            self._inject(self._apps(), "multi", domains=[DOMAIN]),
            [DOMAIN, self.ONION],
        )

    def test_named_canonicals_gain_onion_keys_after_clearnet(self):
        self.assertEqual(
            self._inject(self._apps(), "multi", domains={"api": f"api.{DOMAIN}"}),
            {"api": f"api.{DOMAIN}", "api_onion": f"api.{self.ONION}"},
        )

    def test_named_canonicals_in_tor_mode_swap_values(self):
        self.assertEqual(
            self._inject(self._apps(), "tor", domains={"api": f"api.{DOMAIN}"}),
            {"api": f"api.{self.ONION}"},
        )


class TestNodeNetworkMode(unittest.TestCase):
    def test_node_onion_requires_the_provider_on_the_host(self):
        apps = {"svc-net-tor": {"services": {"tor": {"node": "n.onion"}}}}
        self.assertEqual(cache_domains.node_onion_of(apps, {"group_names": []}), "")
        self.assertEqual(
            cache_domains.node_onion_of(apps, {"group_names": ["svc-net-tor"]}),
            "n.onion",
        )

    def test_empty_mode_derives_from_the_node_onion(self):
        self.assertEqual(cache_domains.node_network_mode({}, "n.onion"), "multi")
        self.assertEqual(cache_domains.node_network_mode({}, ""), "clearnet")

    def test_declared_tor_mode_without_provider_fails(self):
        with self.assertRaises(ValueError):
            cache_domains.node_network_mode({"NETWORK_MODE": "tor"}, "")


class TestTorFlagsAreRendered(unittest.TestCase):
    """`services.tor.enabled` reaches this map as Jinja in almost every role
    that declares it, and as its own source text whenever the applications
    render is still in flight. Reading that text as a boolean answers False and
    drops the onion domains for every app.
    """

    ONION = TestNetworkSiblingInjection.ONION
    JINJA_ON = "{{ 'svc-net-tor' in group_names }}"

    def _templar(self, **variables):
        from ansible.parsing.dataloader import DataLoader
        from ansible.template import Templar

        templar = Templar(loader=DataLoader(), variables=dict(variables))
        templar.available_variables = dict(variables)
        return templar

    def _inject(self, templar, **variables):
        return cache_domains._inject_network_siblings(
            {"web-app-x": [f"x.{DOMAIN}"]},
            {"web-app-x": {"services": {"tor": {"enabled": self.JINJA_ON}}}},
            DOMAIN,
            self.ONION,
            "multi",
            templar=templar,
            variables=dict(variables),
        )["web-app-x"]

    def test_a_templated_enabled_flag_still_injects_the_onion(self):
        variables = {"group_names": ["svc-net-tor", "web-app-x"]}
        self.assertEqual(
            self._inject(self._templar(**variables), **variables),
            [f"x.{DOMAIN}", f"x.{self.ONION}"],
        )

    def test_a_templated_flag_resolving_false_leaves_the_clearnet_domain(self):
        variables = {"group_names": ["web-app-x"]}
        self.assertEqual(
            self._inject(self._templar(**variables), **variables),
            [f"x.{DOMAIN}"],
        )

    def test_a_flag_that_cannot_be_rendered_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "services.tor.enabled"):
            self._inject(None, group_names=["svc-net-tor"])


if __name__ == "__main__":
    unittest.main()
