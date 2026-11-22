from __future__ import annotations

import unittest

from . import TARGET_RE


class TestTargetRe(unittest.TestCase):
    def test_rules_are_targets(self) -> None:
        for line in ("all:", "build: deps", "clean::", "run: VAR := 1"):
            with self.subTest(line=line):
                self.assertIsNotNone(TARGET_RE.match(line))

    def test_variable_assignments_are_not_targets(self) -> None:
        for line in (
            "SHELL := /bin/bash",
            "ENV_SH := $(CURDIR)/scripts/meta/env/load.sh",
            "override ENV_SH := $(CURDIR)/scripts/meta/env/load.sh",
            "X ::= y",
            "X :::= y",
            "X ?= y",
            "X = y",
            ".PHONY: all",
        ):
            with self.subTest(line=line):
                self.assertIsNone(TARGET_RE.match(line))
