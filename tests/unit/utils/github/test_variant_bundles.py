"""Unit tests for :mod:`utils.github.variant_bundles`."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

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

    def test_role_within_bundle_size_stays_full_matrix(self) -> None:
        self.assertEqual(
            vb.expand_apps(["web-app-three"], self.VARIANTS, 3),
            [{"apps": "web-app-three", "variant": "", "variant_slug": ""}],
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
        out = vb.expand_apps(
            ["web-app-single", "web-app-five"], self.VARIANTS, 3
        )
        self.assertEqual(
            out,
            [
                {"apps": "web-app-single", "variant": "", "variant_slug": ""},
                {"apps": "web-app-five", "variant": "0,1,2", "variant_slug": "0-1-2"},
                {"apps": "web-app-five", "variant": "3,4", "variant_slug": "3-4"},
            ],
        )


class TestMain(unittest.TestCase):
    def test_reads_argv_and_prints_json(self) -> None:
        with (
            patch.object(vb, "get_variants", return_value={"web-app-five": [{}] * 5}),
            patch.dict("os.environ", {"INFINITO_VARIANT_BUNDLE_SIZE": "3"}),
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
            patch("builtins.print") as mock_print,
        ):
            rc = vb.main([""])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(mock_print.call_args.args[0]), [])

    def test_non_list_json_rejected(self) -> None:
        with (
            patch.object(vb, "get_variants", return_value={}),
            self.assertRaises(SystemExit),
        ):
            vb.main(['"web-app-five"'])


if __name__ == "__main__":
    unittest.main()
