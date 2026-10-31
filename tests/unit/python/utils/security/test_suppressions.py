from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path
from unittest import TestCase, main

from utils.security.suppressions import (
    Suppression,
    SuppressionError,
    parse_entries,
    role_suppressions,
    service_suppressions,
)


class TestParseEntries(TestCase):
    def test_a_date_until_is_kept(self):
        parsed = parse_entries(
            [{"id": "CVE-2026-1234", "until": dt.date(2026, 12, 31)}], "r:s"
        )
        self.assertEqual(parsed, [Suppression("CVE-2026-1234", dt.date(2026, 12, 31))])

    def test_a_quoted_until_is_parsed(self):
        parsed = parse_entries([{"id": "CVE-2026-1234", "until": "2026-12-31"}], "r:s")
        self.assertEqual(parsed[0].until, dt.date(2026, 12, 31))

    def test_a_ghsa_id_is_rejected(self):
        with self.assertRaisesRegex(SuppressionError, "no CVE-YYYY-NNNN id"):
            parse_entries([{"id": "GHSA-aaaa-bbbb-cccc", "until": "2026-12-31"}], "r:s")

    def test_a_missing_until_is_rejected(self):
        with self.assertRaisesRegex(SuppressionError, "until is required"):
            parse_entries([{"id": "CVE-2026-1234"}], "r:s")

    def test_a_timestamp_until_is_rejected(self):
        with self.assertRaisesRegex(SuppressionError, "not a timestamp"):
            parse_entries(
                [
                    {
                        "id": "CVE-2026-1234",
                        "until": dt.datetime(2026, 12, 31, tzinfo=dt.UTC),
                    }
                ],
                "r:s",
            )

    def test_an_unknown_key_is_rejected(self):
        with self.assertRaisesRegex(SuppressionError, "unknown key"):
            parse_entries(
                [{"id": "CVE-2026-1234", "until": "2026-12-31", "reason": "x"}], "r:s"
            )

    def test_a_mapping_instead_of_a_list_is_rejected(self):
        with self.assertRaisesRegex(SuppressionError, "must be a list"):
            parse_entries({"id": "CVE-2026-1234"}, "r:s")


class TestServiceSuppressions(TestCase):
    def test_services_without_security_are_left_out(self):
        services = {
            "app": {
                "image": "app",
                "security": {
                    "suppressions": [{"id": "CVE-2026-1001", "until": "2026-12-31"}]
                },
            },
            "db": {"image": "postgres"},
        }
        self.assertEqual(list(service_suppressions(services, "role")), ["app"])

    def test_security_without_suppressions_is_rejected(self):
        with self.assertRaisesRegex(
            SuppressionError, "security must hold suppressions"
        ):
            service_suppressions({"app": {"security": {}}}, "role")

    def test_a_role_without_services_file_has_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(role_suppressions(Path(tmp), "web-app-none"), {})


if __name__ == "__main__":
    main()
