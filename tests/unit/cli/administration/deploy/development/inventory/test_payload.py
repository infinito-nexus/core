"""Unit tests for `cli.administration.deploy.development.inventory.payload`."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from cli.administration.deploy.development.inventory import (
    _bake_overrides,
    _resolve_variant_payloads,
)


class TestResolveVariantPayloads(unittest.TestCase):
    @patch(
        "cli.administration.deploy.development.inventory.payload.get_variant_overrides_only",
        autospec=True,
    )
    def test_app_without_meta_collapses_to_variant_zero_payload(
        self, get_overrides_mock: MagicMock
    ) -> None:
        # No `meta/variants.yml` -> loader exposes a single empty variant,
        # i.e. `[{}]`. The 1st entry MUST be picked even though no variant
        # was authored, so the per-app bake stays uniform.
        get_overrides_mock.return_value = {"web-app-foo": [{}]}

        resolved = _resolve_variant_payloads(
            roles_dir="/roles",
            include=["web-app-foo"],
            active_variants={},
        )
        self.assertEqual(resolved, {"web-app-foo": {}})

    @patch(
        "cli.administration.deploy.development.inventory.payload.get_variant_overrides_only",
        autospec=True,
    )
    def test_active_variants_picks_named_variant(
        self, get_overrides_mock: MagicMock
    ) -> None:
        get_overrides_mock.return_value = {
            "web-app-multi": [{"variant": 0}, {"variant": 1}],
        }
        resolved = _resolve_variant_payloads(
            roles_dir="/roles",
            include=["web-app-multi"],
            active_variants={"web-app-multi": 1},
        )
        self.assertEqual(resolved, {"web-app-multi": {"variant": 1}})

    @patch(
        "cli.administration.deploy.development.inventory.payload.get_variant_overrides_only",
        autospec=True,
    )
    def test_out_of_range_index_falls_back_to_variant_zero(
        self, get_overrides_mock: MagicMock
    ) -> None:
        get_overrides_mock.return_value = {
            "web-app-multi": [{"variant": 0}, {"variant": 1}],
        }
        resolved = _resolve_variant_payloads(
            roles_dir="/roles",
            include=["web-app-multi"],
            active_variants={"web-app-multi": 99},
        )
        self.assertEqual(resolved, {"web-app-multi": {"variant": 0}})


class TestBakeOverrides(unittest.TestCase):
    def test_user_supplied_applications_override_wins_over_variant_payload(self):
        baked = _bake_overrides(
            base_overrides={
                "STORAGE_CONSTRAINED": False,
                "RUNTIME": "dev",
                "applications": {
                    "web-app-foo": {"feature_flag": True},
                },
            },
            variant_payloads={
                "web-app-foo": {"feature_flag": False, "image": "v1"},
            },
        )
        # User override wins on conflicting keys; non-conflicting keys
        # from the variant payload remain visible.
        self.assertEqual(
            baked["applications"]["web-app-foo"],
            {"feature_flag": True, "image": "v1"},
        )

    def test_no_variant_payloads_yields_unchanged_base(self):
        base = {"STORAGE_CONSTRAINED": False, "RUNTIME": "dev"}
        baked = _bake_overrides(base_overrides=base, variant_payloads={})
        self.assertEqual(baked, base)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
