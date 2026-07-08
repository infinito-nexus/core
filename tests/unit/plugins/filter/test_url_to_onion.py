import unittest

from plugins.filter.url_to_onion import to_onion_url

NODE = "abc123def456ghij789klmno000pqrstuvwx111yz222abc333def444gh.onion"
PRIMARY = "infinito.example"


class TestToOnionUrl(unittest.TestCase):
    def test_subdomain_swapped_and_forced_http(self):
        self.assertEqual(
            to_onion_url("https://auth.infinito.example/realms/x", NODE, PRIMARY),
            f"http://auth.{NODE}/realms/x",
        )

    def test_bare_primary_becomes_node(self):
        self.assertEqual(
            to_onion_url("https://infinito.example/", NODE, PRIMARY),
            f"http://{NODE}/",
        )

    def test_path_and_query_preserved(self):
        self.assertEqual(
            to_onion_url("https://cdn.infinito.example/a/b.js?v=3", NODE, PRIMARY),
            f"http://cdn.{NODE}/a/b.js?v=3",
        )

    def test_host_not_under_primary_unchanged(self):
        url = "https://example.org/foo"
        self.assertEqual(to_onion_url(url, NODE, PRIMARY), url)

    def test_noop_without_tor_node(self):
        url = "https://auth.infinito.example/"
        self.assertEqual(to_onion_url(url, "", PRIMARY), url)

    def test_noop_on_empty_url(self):
        self.assertEqual(to_onion_url("", NODE, PRIMARY), "")

    def test_already_onion_host_unchanged(self):
        url = f"http://auth.{NODE}/"
        self.assertEqual(to_onion_url(url, NODE, PRIMARY), url)


if __name__ == "__main__":
    unittest.main()
