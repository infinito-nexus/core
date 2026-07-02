"""Unit tests for :mod:`utils.github.variant_bundles`."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from humanfriendly import parse_size

from utils.github import variant_bundles as vb


class TestChunkIndices(unittest.TestCase):
    def test_splits_into_consecutive_bundles(self) -> None:
        self.assertEqual(vb.chunk_indices(5, 3), [[0, 1, 2], [3, 4]])
        self.assertEqual(vb.chunk_indices(6, 3), [[0, 1, 2], [3, 4, 5]])
        self.assertEqual(vb.chunk_indices(3, 3), [[0, 1, 2]])
        self.assertEqual(vb.chunk_indices(1, 3), [[0]])


class TestResolveBundleSize(unittest.TestCase):
    def test_default_when_unset(self) -> None:
        self.assertEqual(vb.resolve_bundle_size(""), vb.DEFAULT_BUNDLE_SIZE)

    def test_explicit_value(self) -> None:
        self.assertEqual(vb.resolve_bundle_size("2"), 2)

    def test_zero_or_negative_rejected(self) -> None:
        with self.assertRaises(ValueError):
            vb.resolve_bundle_size("0")

    def test_non_numeric_rejected_cleanly(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            vb.resolve_bundle_size("three")


class TestExpandApps(unittest.TestCase):
    VARIANTS = {  # noqa: RUF012
        "web-app-single": [{}],
        "web-app-three": [{}, {}, {}],
        "web-app-five": [{}, {}, {}, {}, {}],
    }

    def test_role_within_bundle_size_shows_all_variants(self) -> None:
        self.assertEqual(
            vb.expand_apps(["web-app-three"], self.VARIANTS, 3),
            [{"apps": "web-app-three", "variant": "0,1,2", "variant_slug": "0-1-2"}],
        )

    def test_missing_variants_treated_as_single(self) -> None:
        self.assertEqual(
            vb.expand_apps(["web-app-unknown"], self.VARIANTS, 3),
            [{"apps": "web-app-unknown", "variant": "", "variant_slug": ""}],
        )

    def test_role_over_bundle_size_is_split(self) -> None:
        self.assertEqual(
            vb.expand_apps(["web-app-five"], self.VARIANTS, 3),
            [
                {"apps": "web-app-five", "variant": "0,1,2", "variant_slug": "0-1-2"},
                {"apps": "web-app-five", "variant": "3,4", "variant_slug": "3-4"},
            ],
        )

    def test_mixed_list_preserves_app_order(self) -> None:
        out = vb.expand_apps(["web-app-single", "web-app-five"], self.VARIANTS, 3)
        self.assertEqual(
            out,
            [
                {"apps": "web-app-single", "variant": "0", "variant_slug": "0"},
                {"apps": "web-app-five", "variant": "0,1,2", "variant_slug": "0-1-2"},
                {"apps": "web-app-five", "variant": "3,4", "variant_slug": "3-4"},
            ],
        )

    def test_storage_cap_splits_within_bundle_size(self) -> None:
        gb = 1_000_000_000
        out = vb.expand_apps(
            ["web-app-three"],
            self.VARIANTS,
            3,
            storages_per_app={"web-app-three": [300 * gb, 300 * gb, 300 * gb]},
            max_storage_bytes=400 * gb,
        )
        self.assertEqual(
            out,
            [
                {"apps": "web-app-three", "variant": "0", "variant_slug": "0"},
                {"apps": "web-app-three", "variant": "1", "variant_slug": "1"},
                {"apps": "web-app-three", "variant": "2", "variant_slug": "2"},
            ],
        )


class TestBundleIndices(unittest.TestCase):
    def test_count_only_matches_chunk_indices(self) -> None:
        self.assertEqual(vb.bundle_indices(6, 3), [[0, 1, 2], [3, 4, 5]])
        self.assertEqual(vb.bundle_indices(5, 3), [[0, 1, 2], [3, 4]])
        self.assertEqual(vb.bundle_indices(3, 3), [[0, 1, 2]])

    def test_storage_cap_opens_new_bundle_early(self) -> None:
        gb = 1_000_000_000
        storages = [206 * gb, 150 * gb, 159 * gb, 148 * gb, 164 * gb, 143 * gb]
        self.assertEqual(
            vb.bundle_indices(6, 3, storages, 400 * gb),
            [[0, 1], [2, 3], [4, 5]],
        )

    def test_single_variant_over_cap_stands_alone(self) -> None:
        gb = 1_000_000_000
        self.assertEqual(
            vb.bundle_indices(2, 3, [500 * gb, 100 * gb], 400 * gb),
            [[0], [1]],
        )

    def test_none_storage_falls_back_to_count(self) -> None:
        self.assertEqual(
            vb.bundle_indices(4, 3, [None, None, None, None], 400_000_000_000),
            [[0, 1, 2], [3]],
        )


class TestResolveMaxStorage(unittest.TestCase):
    def test_default_when_unset(self) -> None:
        self.assertEqual(vb.resolve_max_storage(""), int(parse_size("350GB")))

    def test_explicit_value(self) -> None:
        self.assertEqual(vb.resolve_max_storage("200GB"), int(parse_size("200GB")))

    def test_zero_disables_cap(self) -> None:
        self.assertIsNone(vb.resolve_max_storage("0"))

    def test_invalid_rejected(self) -> None:
        with self.assertRaises(ValueError):
            vb.resolve_max_storage("huge")


class TestMain(unittest.TestCase):
    def test_reads_argv_and_prints_json(self) -> None:
        with (
            patch.object(vb, "get_variants", return_value={"web-app-five": [{}] * 5}),
            patch.object(vb, "app_variant_storages", return_value={}),
            patch.dict(
                "os.environ",
                {"INFINITO_VARIANT_BUNDLE_SIZE": "3", "INFINITO_DEPLOY_MODE": ""},
            ),
            patch("builtins.print") as mock_print,
        ):
            rc = vb.main(['["web-app-five"]'])
        self.assertEqual(rc, 0)
        printed = json.loads(mock_print.call_args.args[0])
        self.assertEqual(
            printed,
            [
                {"apps": "web-app-five", "variant": "0,1,2", "variant_slug": "0-1-2"},
                {"apps": "web-app-five", "variant": "3,4", "variant_slug": "3-4"},
            ],
        )

    def test_empty_input_yields_empty_list(self) -> None:
        with (
            patch.object(vb, "get_variants", return_value={}),
            patch.object(vb, "app_variant_storages", return_value={}),
            patch("builtins.print") as mock_print,
        ):
            rc = vb.main([""])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(mock_print.call_args.args[0]), [])

    def test_non_list_json_rejected(self) -> None:
        with (
            patch.object(vb, "get_variants", return_value={}),
            patch.object(vb, "app_variant_storages", return_value={}),
            self.assertRaises(SystemExit),
        ):
            vb.main(['"web-app-five"'])


class TestSwarmMode(unittest.TestCase):
    ENABLED = {"services": {"a": {"enabled": True}}}  # noqa: RUF012
    DISABLED = {"services": {"a": {"enabled": False}}}  # noqa: RUF012

    def _run_swarm(self, apps_json, variants, overrides):
        with (
            patch.object(vb, "get_variants", return_value=variants),
            patch.object(vb, "get_variant_overrides_only", return_value=overrides),
            patch.dict("os.environ", {"INFINITO_DEPLOY_MODE": "swarm"}),
            patch("builtins.print") as mock_print,
        ):
            rc = vb.main([apps_json])
        self.assertEqual(rc, 0)
        return json.loads(mock_print.call_args.args[0])

    def test_one_variant_per_runner(self) -> None:
        printed = self._run_swarm(
            '["web-app-five"]',
            {"web-app-five": [{}] * 5},
            {"web-app-five": [{}] * 5},
        )
        self.assertEqual(
            printed,
            [
                {"apps": "web-app-five", "variant": str(i), "variant_slug": str(i)}
                for i in range(5)
            ],
        )

    def test_skips_all_disabled_variant_keeping_absolute_index(self) -> None:
        printed = self._run_swarm(
            '["web-app-bbb"]',
            {"web-app-bbb": [{}, {}]},
            {"web-app-bbb": [self.ENABLED, self.DISABLED]},
        )
        self.assertEqual(
            printed,
            [{"apps": "web-app-bbb", "variant": "0", "variant_slug": "0"}],
        )

    def test_non_consecutive_survivors_keep_absolute_indices(self) -> None:
        printed = self._run_swarm(
            '["web-app-x"]',
            {"web-app-x": [{}, {}, {}]},
            {"web-app-x": [self.ENABLED, self.DISABLED, self.ENABLED]},
        )
        self.assertEqual(
            printed,
            [
                {"apps": "web-app-x", "variant": "0", "variant_slug": "0"},
                {"apps": "web-app-x", "variant": "2", "variant_slug": "2"},
            ],
        )

    def test_app_with_only_disabled_variants_is_dropped(self) -> None:
        printed = self._run_swarm(
            '["web-app-off"]',
            {"web-app-off": [{}]},
            {"web-app-off": [self.DISABLED]},
        )
        self.assertEqual(printed, [])

    def test_compose_mode_keeps_bundling_and_all_variants(self) -> None:
        with (
            patch.object(vb, "get_variants", return_value={"web-app-bbb": [{}, {}]}),
            patch.object(vb, "app_variant_storages", return_value={}),
            patch.dict("os.environ", {"INFINITO_DEPLOY_MODE": "compose"}, clear=False),
            patch("builtins.print") as mock_print,
        ):
            rc = vb.main(['["web-app-bbb"]'])
        self.assertEqual(rc, 0)
        self.assertEqual(
            json.loads(mock_print.call_args.args[0]),
            [{"apps": "web-app-bbb", "variant": "0,1", "variant_slug": "0-1"}],
        )


if __name__ == "__main__":
    unittest.main()
