"""Unit tests for :mod:`utils.roles.applications.services.variant_status`."""

from __future__ import annotations

import unittest

from utils.roles.applications.services.variant_status import (
    variant_disables_all_services,
)


class TestVariantDisablesAllServices(unittest.TestCase):
    def test_all_literal_false_is_disabled(self) -> None:
        self.assertTrue(
            variant_disables_all_services(
                {"services": {"a": {"enabled": False}, "b": {"enabled": False}}}
            )
        )

    def test_string_false_is_disabled(self) -> None:
        self.assertTrue(
            variant_disables_all_services({"services": {"a": {"enabled": "false"}}})
        )

    def test_any_enabled_true_keeps_variant(self) -> None:
        self.assertFalse(
            variant_disables_all_services(
                {"services": {"a": {"enabled": False}, "b": {"enabled": True}}}
            )
        )

    def test_jinja_conditional_keeps_variant(self) -> None:
        self.assertFalse(
            variant_disables_all_services(
                {"services": {"a": {"enabled": "{{ 'web-app-x' in group_names }}"}}}
            )
        )

    def test_absent_enabled_keeps_variant(self) -> None:
        self.assertFalse(
            variant_disables_all_services({"services": {"a": {"shared": False}}})
        )

    def test_empty_or_absent_services_keeps_variant(self) -> None:
        self.assertFalse(variant_disables_all_services({"services": {}}))
        self.assertFalse(variant_disables_all_services({}))
        self.assertFalse(variant_disables_all_services({"image": "x"}))


if __name__ == "__main__":
    unittest.main()
