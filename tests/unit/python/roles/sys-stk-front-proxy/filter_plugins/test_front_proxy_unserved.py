import importlib.util
import unittest

from . import PROJECT_ROOT


def _load_filter():
    path = (
        PROJECT_ROOT
        / "roles"
        / "sys-stk-front-proxy"
        / "filter_plugins"
        / "front_proxy_unserved.py"
    )
    spec = importlib.util.spec_from_file_location("front_proxy_unserved", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.front_proxy_unserved


STALE = [-1, 404]

PROBES = {
    "cloud.example.org": {
        "url": "https://cloud.example.org/",
        "status_codes": [200, 302, 301],
    },
    "newsletter.example.org": {
        "url": "https://newsletter.example.org/",
        "status_codes": [200, 302, 301, 404],
    },
    "icons.example.org": {
        "url": "https://icons.example.org/",
        "status_codes": [200, 302, 301],
    },
}


class TestFrontProxyUnserved(unittest.TestCase):
    def setUp(self):
        self.unserved = _load_filter()

    def test_vhosts_answering_an_accepted_status_are_served(self):
        status = {"cloud.example.org": 200, "icons.example.org": 302}
        self.assertEqual(self.unserved(status, PROBES, STALE), [])

    def test_a_vhost_without_an_answer_is_unserved(self):
        status = {"cloud.example.org": -1, "icons.example.org": 200}
        self.assertEqual(self.unserved(status, PROBES, STALE), ["cloud.example.org"])

    def test_a_404_the_vhost_does_not_declare_is_unserved(self):
        status = {"cloud.example.org": 404}
        self.assertEqual(self.unserved(status, PROBES, STALE), ["cloud.example.org"])

    def test_a_404_the_vhost_declares_is_served(self):
        status = {"newsletter.example.org": 404}
        self.assertEqual(self.unserved(status, PROBES, STALE), [])

    def test_an_upstream_that_is_down_still_proves_the_vhost_is_served(self):
        status = {"cloud.example.org": 502, "icons.example.org": 504}
        self.assertEqual(self.unserved(status, PROBES, STALE), [])

    def test_an_unexpected_status_that_is_no_stale_answer_is_served(self):
        status = {"cloud.example.org": 500, "icons.example.org": 403}
        self.assertEqual(self.unserved(status, PROBES, STALE), [])

    def test_every_unserved_vhost_is_named_in_sorted_order(self):
        status = {"icons.example.org": -1, "cloud.example.org": 404}
        self.assertEqual(
            self.unserved(status, PROBES, STALE),
            ["cloud.example.org", "icons.example.org"],
        )

    def test_status_codes_given_as_strings_are_compared_as_numbers(self):
        status = {"newsletter.example.org": "404", "cloud.example.org": "-1"}
        self.assertEqual(
            self.unserved(status, PROBES, ["-1", "404"]), ["cloud.example.org"]
        )

    def test_a_status_for_a_vhost_that_was_never_queued_is_an_error(self):
        with self.assertRaises(KeyError):
            self.unserved({"stray.example.org": 200}, PROBES, STALE)


if __name__ == "__main__":
    unittest.main()
