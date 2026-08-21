"""Unit tests for `cli.administration.deploy.development.inventory.spec`."""

from __future__ import annotations

import unittest

from cli.administration.deploy.development.inventory import DevInventorySpec

from ._fixtures import make_spec


class TestDevInventorySpec(unittest.TestCase):
    def test_empty_include_rejected(self):
        with self.assertRaises(ValueError):
            DevInventorySpec(
                inventory_dir="/tmp/inv",
                include=(),
                storage_constrained=False,
                runtime="dev",
            )

    def test_list_include_normalised_to_tuple(self):
        spec = DevInventorySpec(
            inventory_dir="/tmp/inv",
            include=["web-app-keycloak"],
            storage_constrained=True,
            runtime="dev",
        )
        self.assertIsInstance(spec.include, tuple)
        self.assertEqual(spec.include, ("web-app-keycloak",))

    def test_overrides_default(self):
        spec = make_spec(storage_constrained=True, runtime="prod")
        self.assertEqual(
            spec.overrides(),
            {"STORAGE_CONSTRAINED": True, "RUNTIME": "prod"},
        )

    def test_extra_vars_win_over_implicit_overrides(self):
        spec = make_spec(
            storage_constrained=False,
            runtime="dev",
            extra_vars={"STORAGE_CONSTRAINED": True, "FOO": "bar"},
        )
        self.assertEqual(
            spec.overrides(),
            {"STORAGE_CONSTRAINED": True, "RUNTIME": "dev", "FOO": "bar"},
        )

    def test_inventory_root_strips_trailing_slash(self):
        spec = make_spec(inventory_dir="/tmp/inv///")
        self.assertEqual(spec.inventory_root(), "/tmp/inv")

    def test_variant_selectors_default_to_empty_dict(self):
        self.assertEqual(make_spec().variant_selectors(), {})

    def test_variant_selectors_returned_as_plain_dict(self):
        spec = make_spec(active_variants={"web-app-keycloak": 2})
        self.assertEqual(spec.variant_selectors(), {"web-app-keycloak": 2})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
