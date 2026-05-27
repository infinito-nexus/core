from __future__ import annotations

import sys
import unittest

from . import PROJECT_ROOT

# Ensure repo root is importable (so `import cli...` works in all runners)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cli.administration.inventory.devices import command as devices


class TestFullInventoryCommand(unittest.TestCase):
    def test_build_group_inventory(self):
        apps = ["app1", "app2"]
        host = "myhost"

        inventory = devices.build_group_inventory(apps, host)

        self.assertIn("all", inventory)
        self.assertIn("app1", inventory)
        self.assertIn("app2", inventory)
        self.assertEqual(inventory["app1"], {"hosts": [host]})
        self.assertEqual(inventory["all"]["hosts"], [host])
        self.assertIn("app1", inventory["all"]["children"])

    def test_build_hostvar_inventory(self):
        apps = ["foo", "bar"]
        host = "testhost"

        inventory = devices.build_hostvar_inventory(apps, host)

        self.assertIn("all", inventory)
        self.assertIn("_meta", inventory)
        self.assertIn("hostvars", inventory["_meta"])
        self.assertEqual(
            inventory["_meta"]["hostvars"][host]["invokable_applications"], apps
        )
        self.assertEqual(inventory["all"]["hosts"], [host])

    def test_ignore_filtering(self):
        # Simulate argument parsing logic for ignore flattening
        ignore_args = ["foo,bar", "baz"]
        ignore_ids: set[str] = set()
        for entry in ignore_args:
            ignore_ids.update(i.strip() for i in entry.split(",") if i.strip())
        self.assertEqual(ignore_ids, {"foo", "bar", "baz"})

        # Filtering list
        apps = ["foo", "bar", "baz", "other"]
        filtered = [app for app in apps if app not in ignore_ids]
        self.assertEqual(filtered, ["other"])

    def test_ignore_filtering_empty(self):
        ignore_args: list[str] = []
        ignore_ids: set[str] = set()
        for entry in ignore_args:
            ignore_ids.update(i.strip() for i in entry.split(",") if i.strip())

        apps = ["a", "b"]
        filtered = [app for app in apps if app not in ignore_ids]
        self.assertEqual(filtered, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
