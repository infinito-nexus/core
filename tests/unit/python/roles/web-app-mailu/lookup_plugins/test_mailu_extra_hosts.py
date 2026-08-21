from __future__ import annotations

import importlib.util
import sys
import unittest
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MODULE = _load_module(
    "roles/web-app-mailu/lookup_plugins/mailu_extra_hosts.py", "mailu_extra_hosts"
)


class TestMailuExtraHosts(unittest.TestCase):
    def setUp(self):
        self.lookup = MODULE.LookupModule()

        def _get(name, *args, **kwargs):
            plugin = MagicMock()

            def _run(terms, variables=None, **_kwargs):
                return [(variables or {}).get("_redis_local", False)]

            plugin.run.side_effect = _run
            return plugin

        patcher = patch.object(MODULE.lookup_loader, "get", side_effect=_get)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, **overrides):
        variables = {
            "application_id": "web-app-mailu",
            "DEPLOYMENT_MODE": "compose",
            "DOCKER_IN_CONTAINER": False,
            "MAILU_OIDC_ENABLED": False,
            "MAILU_OIDC_HOST": "auth.example.org",
            "MAILU_SWARM_DB_HOST": "db.example.org",
            "MAILU_SWARM_DB_ADDR": "10.0.0.2",
            "MAILU_SWARM_REDIS_HOST": "redis.example.org",
            "MAILU_SWARM_REDIS_ADDR": "10.0.0.3",
            "_redis_local": False,
        }
        variables.update(overrides)
        return self.lookup.run(None, variables=variables)

    def test_nothing_applies_in_plain_compose(self):
        self.assertEqual(self._run(), [])

    def test_oidc_pin_needs_both_the_rig_and_oidc(self):
        self.assertEqual(self._run(DOCKER_IN_CONTAINER=True), [])
        self.assertEqual(self._run(MAILU_OIDC_ENABLED=True), [])
        self.assertEqual(
            self._run(DOCKER_IN_CONTAINER=True, MAILU_OIDC_ENABLED=True),
            ["auth.example.org:host-gateway"],
        )

    def test_string_flags_are_coerced_like_jinja_bool(self):
        self.assertEqual(
            self._run(DOCKER_IN_CONTAINER="True", MAILU_OIDC_ENABLED="true"),
            ["auth.example.org:host-gateway"],
        )
        self.assertEqual(
            self._run(DOCKER_IN_CONTAINER="False", MAILU_OIDC_ENABLED="true"), []
        )

    def test_an_onion_provider_is_left_to_the_container_extra_hosts_spot(self):
        self.assertEqual(
            self._run(
                DOCKER_IN_CONTAINER=True,
                MAILU_OIDC_ENABLED=True,
                MAILU_OIDC_HOST="auth." + "b" * 56 + ".onion",
            ),
            [],
        )

    def test_swarm_pins_the_database_vip(self):
        self.assertEqual(
            self._run(DEPLOYMENT_MODE="swarm"),
            ["db.example.org:10.0.0.2", "redis.example.org:10.0.0.3"],
        )

    def test_a_local_redis_is_not_pinned(self):
        self.assertEqual(
            self._run(DEPLOYMENT_MODE="swarm", _redis_local=True),
            ["db.example.org:10.0.0.2"],
        )

    def test_swarm_and_oidc_pins_combine_in_order(self):
        self.assertEqual(
            self._run(
                DEPLOYMENT_MODE="swarm",
                DOCKER_IN_CONTAINER=True,
                MAILU_OIDC_ENABLED=True,
                _redis_local=True,
            ),
            ["auth.example.org:host-gateway", "db.example.org:10.0.0.2"],
        )

    def test_positional_terms_raise(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["nope"], variables={})


if __name__ == "__main__":
    unittest.main()
