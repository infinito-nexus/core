import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(
            str(
                Path(str(Path(__file__).parent))
                / "../../../../roles/web-app-matrix/filter_plugins"
            )
        ).resolve()
    ),
)

from bridge_filters import filter_enabled_bridges


class TestBridgeFilters(unittest.TestCase):
    def test_no_bridges_returns_empty_list(self):
        # When there are no bridges defined, result should be an empty list
        self.assertEqual(filter_enabled_bridges([], {}), [])

    def test_all_bridges_disabled(self):
        # Define two bridges, but plugins dict has them disabled or missing
        bridges = [
            {"bridge_name": "whatsapp", "config": {}},
            {"bridge_name": "telegram", "config": {}},
        ]
        plugins = {
            "whatsapp": False,
            "telegram": False,
        }
        result = filter_enabled_bridges(bridges, plugins)
        self.assertEqual(result, [])

    def test_some_bridges_enabled(self):
        # Only bridges with True in plugins should be returned
        bridges = [
            {"bridge_name": "whatsapp", "version": "1.0"},
            {"bridge_name": "telegram", "version": "1.0"},
            {"bridge_name": "signal", "version": "1.0"},
        ]
        plugins = {
            "whatsapp": True,
            "telegram": False,
            "signal": True,
        }
        result = filter_enabled_bridges(bridges, plugins)
        expected = [
            {"bridge_name": "whatsapp", "version": "1.0"},
            {"bridge_name": "signal", "version": "1.0"},
        ]
        self.assertEqual(result, expected)

    def test_bridge_without_plugin_entry_defaults_to_disabled(self):
        # If a bridge_name is not present in plugins, it should be treated as disabled
        bridges = [
            {"bridge_name": "facebook", "enabled": True},
        ]
        plugins = {}  # no entries
        result = filter_enabled_bridges(bridges, plugins)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
