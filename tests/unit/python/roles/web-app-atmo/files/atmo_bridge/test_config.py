import unittest

from ._fixtures import ENV, load

config = load("config")


class TestConfig(unittest.TestCase):
    def test_complete_environment_loads(self):
        loaded = config.load_config(ENV)
        self.assertEqual(loaded.pds_url, "https://pds.example.org")
        self.assertEqual(loaded.appview_url, "https://rsvp.example.org")
        self.assertEqual(loaded.interval_seconds, 60)

    def test_missing_or_invalid_environment_refuses_to_start(self):
        for key in ENV:
            with self.subTest(missing=key), self.assertRaises(SystemExit):
                config.load_config({k: v for k, v in ENV.items() if k != key})
        for value in ("0", "soon"):
            with self.subTest(interval=value), self.assertRaises(SystemExit):
                config.load_config({**ENV, "BRIDGE_INTERVAL_SECONDS": value})
        for key in ("BRIDGE_PDS_URL", "BRIDGE_APPVIEW_URL", "BRIDGE_MOBILIZON_URL"):
            with self.subTest(scheme=key), self.assertRaises(SystemExit):
                config.load_config({**ENV, key: "file:///etc/passwd"})


if __name__ == "__main__":
    unittest.main()
