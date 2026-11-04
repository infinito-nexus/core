import importlib.util
import unittest

from . import PROJECT_ROOT

_PATH = (
    PROJECT_ROOT / "roles" / "web-app-dashboard" / "filter_plugins" / "first_seen.py"
)
_SPEC = importlib.util.spec_from_file_location("first_seen", _PATH)
first_seen = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(first_seen)


def _cards(*ids):
    return [{"id": card_id, "title": card_id} for card_id in ids]


class TestFirstSeenMerge(unittest.TestCase):
    def test_a_host_without_a_registry_records_every_card_as_baseline(self):
        merged = first_seen.first_seen_merge(None, _cards("a", "b"), "2026-11-03")

        self.assertEqual(merged, {"a": "", "b": ""})

    def test_a_card_new_to_the_registry_gets_todays_date(self):
        merged = first_seen.first_seen_merge({"a": ""}, _cards("a", "b"), "2026-11-03")

        self.assertEqual(merged, {"a": "", "b": "2026-11-03"})

    def test_a_known_date_survives_a_redeploy(self):
        merged = first_seen.first_seen_merge(
            {"b": "2026-10-01"}, _cards("b"), "2026-11-03"
        )

        self.assertEqual(merged, {"b": "2026-10-01"})

    def test_a_removed_card_keeps_its_entry(self):
        merged = first_seen.first_seen_merge(
            {"gone": "2026-10-01"}, _cards("a"), "2026-11-03"
        )

        self.assertEqual(merged, {"gone": "2026-10-01", "a": "2026-11-03"})


class TestWithAdded(unittest.TestCase):
    def test_only_cards_with_a_date_carry_added(self):
        cards = first_seen.with_added(_cards("a", "b"), {"a": "", "b": "2026-11-03"})

        self.assertEqual(
            cards,
            [
                {"id": "a", "title": "a"},
                {"id": "b", "title": "b", "added": "2026-11-03"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
