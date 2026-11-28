import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(
        (
            Path(__file__).parent
            / "../../../../../../roles/web-svc-loki/filter_plugins"
        ).resolve()
    ),
)

from ansible.errors import AnsibleFilterError
from loki_retention import FilterModule, loki_retention

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES


class TestLokiRetention(unittest.TestCase):
    def test_the_shipped_default_keeps_every_class_for_seven_days(self) -> None:
        services = load_yaml_any(
            str(PROJECT_ROOT / "roles" / "web-svc-loki" / ROLE_FILE_META_SERVICES)
        )
        result = loki_retention(services["loki"]["retention"], "log_class")
        self.assertEqual("168h", result["period"])
        self.assertEqual({"168h"}, {stream["period"] for stream in result["streams"]})

    def test_each_class_becomes_one_selector(self) -> None:
        result = loki_retention({"system": "7d", "application": "14d"}, "log_class")
        self.assertEqual(
            [
                {
                    "selector": '{log_class="application"}',
                    "priority": 1,
                    "period": "336h",
                },
                {"selector": '{log_class="system"}', "priority": 1, "period": "168h"},
            ],
            result["streams"],
        )

    def test_the_global_period_is_the_longest_class(self) -> None:
        result = loki_retention(
            {"system": "2d", "security": "4w", "application": "36h"}, "log_class"
        )
        self.assertEqual("672h", result["period"])

    def test_hours_days_and_weeks_are_accepted(self) -> None:
        result = loki_retention({"a": "48h", "b": "3d", "c": "1w"}, "log_class")
        self.assertEqual(
            ["48h", "72h", "168h"], [stream["period"] for stream in result["streams"]]
        )

    def test_an_empty_map_fails(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            loki_retention({}, "log_class")

    def test_a_malformed_duration_fails(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            loki_retention({"system": "seven days"}, "log_class")

    def test_a_zero_duration_fails(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            loki_retention({"system": "0d"}, "log_class")

    def test_a_retention_below_one_index_period_fails(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            loki_retention({"system": "12h"}, "log_class")

    def test_a_class_name_loki_cannot_select_fails(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            loki_retention({'sys"tem': "7d"}, "log_class")

    def test_an_invalid_stream_label_fails(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            loki_retention({"system": "7d"}, "log-class")

    def test_the_filter_is_registered(self) -> None:
        self.assertIs(loki_retention, FilterModule().filters()["loki_retention"])


if __name__ == "__main__":
    unittest.main()
