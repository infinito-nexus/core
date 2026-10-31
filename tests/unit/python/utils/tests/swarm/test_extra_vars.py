from __future__ import annotations

import json
import unittest
from unittest import mock

from utils.tests.swarm import extra_vars

ROUND_OVERRIDES = {
    "applications": {
        "web-app-erpnext": {"services": {"backup": {"remote": ["10.0.0.2"]}}}
    },
    "users": {"administrator": {"authorized_keys": ["ssh-ed25519 AAAA"]}},
    "STORAGE_CONSTRAINED": False,
}


class TestInventoryExtraVars(unittest.TestCase):
    def test_unset_or_empty_variable_keeps_the_round_overrides(self):
        for env in ({}, {"INFINITO_INVENTORY_EXTRA_VARS": ""}):
            with mock.patch.dict(extra_vars.os.environ, env, clear=True):
                self.assertEqual(
                    extra_vars.with_extra_vars(ROUND_OVERRIDES), ROUND_OVERRIDES
                )

    def test_nested_app_switch_merges_beside_the_round_overrides(self):
        extra = {
            "applications": {
                "web-app-erpnext": {"services": {"erpnext": {"server_scripts": True}}}
            },
            "STORAGE_CONSTRAINED": True,
        }
        with mock.patch.dict(
            extra_vars.os.environ,
            {"INFINITO_INVENTORY_EXTRA_VARS": json.dumps(extra)},
            clear=True,
        ):
            merged = extra_vars.with_extra_vars(ROUND_OVERRIDES)
        self.assertEqual(
            merged["applications"]["web-app-erpnext"]["services"],
            {"backup": {"remote": ["10.0.0.2"]}, "erpnext": {"server_scripts": True}},
        )
        self.assertEqual(merged["users"], ROUND_OVERRIDES["users"])
        self.assertTrue(merged["STORAGE_CONSTRAINED"])

    def test_a_non_object_variable_fails_loud(self):
        with (
            mock.patch.dict(
                extra_vars.os.environ,
                {"INFINITO_INVENTORY_EXTRA_VARS": "[]"},
                clear=True,
            ),
            self.assertRaises(SystemExit),
        ):
            extra_vars.with_extra_vars(ROUND_OVERRIDES)


if __name__ == "__main__":
    unittest.main()
