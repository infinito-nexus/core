from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path
from unittest import TestCase, main

from utils.cache.yaml import load_yaml_str
from utils.security.suppressions import (
    Suppression,
    SuppressionError,
    drop_image_tag_entries,
    parse_entries,
    role_suppressions,
    service_suppressions,
)


class TestParseEntries(TestCase):
    def test_a_date_until_is_kept(self):
        parsed = parse_entries(
            [{"id": "CVE-2026-1234", "until": dt.date(2026, 12, 31)}], "r:s"
        )
        self.assertEqual(
            parsed, [Suppression("CVE-2026-1234", None, dt.date(2026, 12, 31))]
        )

    def test_an_image_tag_entry_is_kept(self):
        parsed = parse_entries([{"image_tag": "2.18.5", "until": "2026-12-31"}], "r:s")
        self.assertEqual(parsed, [Suppression(None, "2.18.5", dt.date(2026, 12, 31))])

    def test_an_entry_with_id_and_image_tag_is_rejected(self):
        with self.assertRaisesRegex(
            SuppressionError, "exactly one of id and image_tag"
        ):
            parse_entries(
                [
                    {
                        "id": "CVE-2026-1234",
                        "image_tag": "2.18.5",
                        "until": "2026-12-31",
                    }
                ],
                "r:s",
            )

    def test_an_entry_without_id_or_image_tag_is_rejected(self):
        with self.assertRaisesRegex(
            SuppressionError, "exactly one of id and image_tag"
        ):
            parse_entries([{"until": "2026-12-31"}], "r:s")

    def test_an_unquoted_numeric_image_tag_is_rejected(self):
        with self.assertRaisesRegex(SuppressionError, "non-empty quoted string"):
            parse_entries([{"image_tag": 1.1, "until": "2026-12-31"}], "r:s")

    def test_an_empty_image_tag_is_rejected(self):
        with self.assertRaisesRegex(SuppressionError, "non-empty quoted string"):
            parse_entries([{"image_tag": "", "until": "2026-12-31"}], "r:s")

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


MIXED = """\
app:
  image: app
  version: "1.2"
  security:
    suppressions:
      # nocheck: cve the module is not built into the image
      - id: CVE-2026-1234
        until: 2026-12-31

      # nocheck: cve upstream ships no rebuild yet
      - until: 2026-12-31
        image_tag: "1.2"
  mem_limit: 1g
db:
  image: postgres
  version: "17"
  security:
    suppressions:
      # nocheck: cve upstream ships no rebuild yet
      - image_tag: "17"
        until: 2026-12-31
"""


def _drop(text, service):
    return "".join(drop_image_tag_entries(text.splitlines(keepends=True), service))


class TestDropImageTagEntries(TestCase):
    def test_only_the_tag_entry_and_its_marker_leave(self):
        self.assertEqual(
            _drop(MIXED, "app"),
            MIXED.replace(
                "\n      # nocheck: cve upstream ships no rebuild yet\n"
                "      - until: 2026-12-31\n"
                '        image_tag: "1.2"\n',
                "\n",
            ),
        )

    def test_an_emptied_list_takes_suppressions_and_security_along(self):
        self.assertEqual(
            _drop(MIXED, "db"),
            MIXED.replace(
                '  version: "17"\n'
                "  security:\n"
                "    suppressions:\n"
                "      # nocheck: cve upstream ships no rebuild yet\n"
                '      - image_tag: "17"\n'
                "        until: 2026-12-31\n",
                '  version: "17"\n',
            ),
        )

    def test_the_result_still_parses(self):
        for service in ("app", "db"):
            with self.subTest(service=service):
                parsed = load_yaml_str(_drop(MIXED, service))
                self.assertEqual(
                    [
                        entry.image_tag
                        for entries in service_suppressions(parsed, "r").values()
                        for entry in entries
                    ],
                    [None, "17"] if service == "app" else [None, "1.2"],
                )

    def test_a_sequence_at_the_key_indent_is_handled(self):
        text = (
            "app:\n"
            "  security:\n"
            "    suppressions:\n"
            "    # nocheck: cve upstream ships no rebuild yet\n"
            '    - image_tag: "1"\n'
            "      until: 2026-12-31\n"
            "  mem_limit: 1g\n"
        )
        self.assertEqual(_drop(text, "app"), "app:\n  mem_limit: 1g\n")

    def test_a_service_without_tag_entries_is_unchanged(self):
        text = "app:\n  image: app\n"
        self.assertEqual(_drop(text, "app"), text)
        self.assertEqual(_drop(text, "other"), text)


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
