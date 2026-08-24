"""Unit tests for the shared variant-selection helpers."""

from __future__ import annotations

import argparse
import os
import unittest
from typing import ClassVar
from unittest.mock import patch

from cli.administration.deploy.development import variant_select as vs


class TestParseVariantCsv(unittest.TestCase):
    def test_parses_and_drops_blank_tokens(self) -> None:
        self.assertEqual(vs.parse_variant_csv("0,1,2"), [0, 1, 2])
        self.assertEqual(vs.parse_variant_csv(" 3 , 4 "), [3, 4])
        self.assertEqual(vs.parse_variant_csv("2"), [2])
        self.assertEqual(vs.parse_variant_csv(""), [])
        self.assertEqual(vs.parse_variant_csv(","), [])

    def test_non_integer_raises_argument_type_error(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            vs.parse_variant_csv("0,x")


class TestEnvVariant(unittest.TestCase):
    def test_single_and_csv(self) -> None:
        with patch.dict(os.environ, {"variant": "2"}):
            self.assertEqual(vs.env_variant(), [2])
        with patch.dict(os.environ, {"variant": "0,1,2"}):
            self.assertEqual(vs.env_variant(), [0, 1, 2])

    def test_blank_is_none(self) -> None:
        with patch.dict(os.environ, {"variant": ""}):
            self.assertIsNone(vs.env_variant())
        with patch.dict(os.environ, {"variant": "   "}):
            self.assertIsNone(vs.env_variant())

    def test_bad_value_exits(self) -> None:
        with patch.dict(os.environ, {"variant": "0,x"}), self.assertRaises(SystemExit):
            vs.env_variant()


class TestApplyVariantFilter(unittest.TestCase):
    PLAN: ClassVar[list[tuple]] = [(i, f"inv-{i}", {}, (), ()) for i in range(5)]

    def _args(self, *, variant=None) -> argparse.Namespace:
        return argparse.Namespace(variant=variant)

    def test_none_returns_full_plan(self) -> None:
        self.assertEqual(vs.apply_variant_filter(self.PLAN, self._args()), self.PLAN)

    def test_single_index_pins_one_round(self) -> None:
        out = vs.apply_variant_filter(self.PLAN, self._args(variant=[1]))
        self.assertEqual([e[0] for e in out], [1])

    def test_subset_keeps_listed_rounds(self) -> None:
        self.assertEqual(
            vs.apply_variant_filter(self.PLAN, self._args(variant=[3, 4])),
            self.PLAN[3:],
        )

    def test_empty_list_falls_back_to_full_matrix(self) -> None:
        self.assertEqual(
            vs.apply_variant_filter(self.PLAN, self._args(variant=[])), self.PLAN
        )


if __name__ == "__main__":
    unittest.main()
