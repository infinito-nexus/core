import tempfile
import unittest
from pathlib import Path

from plugins.lookup.cdn import _cdn_paths, _to_url_tree


class TestCdnPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.app = "web-app-dashboard"
        self.ver = "latest"
        self.tree = _cdn_paths(self.root, self.app, self.ver)

    def tearDown(self):
        self.tmp.cleanup()

    def test_root_is_absolute(self):
        self.assertTrue(Path(self.tree["root"]).is_absolute())

    def test_shared_paths_under_root(self):
        shared = self.tree["shared"]
        self.assertTrue(shared["css"].startswith(self.tree["root"]))
        self.assertTrue(shared["js"].startswith(self.tree["root"]))
        self.assertTrue(shared["img"].startswith(self.tree["root"]))
        self.assertTrue(shared["fonts"].startswith(self.tree["root"]))

    def test_vendor_under_root(self):
        self.assertTrue(self.tree["vendor"].startswith(self.tree["root"]))

    def test_role_id_and_version(self):
        self.assertEqual(self.tree["role"]["id"], self.app)
        self.assertEqual(self.tree["role"]["version"], self.ver)

    def test_role_release_paths(self):
        release = self.tree["role"]["release"]
        self.assertTrue(release["css"].endswith(str(Path(self.app) / self.ver / "css")))
        self.assertTrue(release["js"].endswith(str(Path(self.app) / self.ver / "js")))

    def test_different_app_ids_produce_different_role_paths(self):
        other = _cdn_paths(self.root, "web-app-nextcloud", self.ver)
        self.assertNotEqual(
            self.tree["role"]["release"]["css"],
            other["role"]["release"]["css"],
        )


class TestCdnToUrlTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.base_url = "https://cdn.example.com"
        self.app = "web-app-matomo"
        self.tree = _cdn_paths(self.root, self.app, "latest")

    def tearDown(self):
        self.tmp.cleanup()

    def test_paths_become_urls(self):
        urls = _to_url_tree(self.tree, self.root, self.base_url)
        self.assertTrue(urls["shared"]["css"].startswith(self.base_url))
        self.assertTrue(urls["shared"]["js"].startswith(self.base_url))
        self.assertTrue(urls["vendor"].startswith(self.base_url))
        self.assertTrue(urls["role"]["release"]["css"].startswith(self.base_url))

    def test_root_ends_with_slash(self):
        urls = _to_url_tree(self.tree, self.root, self.base_url)
        self.assertTrue(urls["root"].endswith("/"))

    def test_non_cdn_strings_unchanged(self):
        urls = _to_url_tree(self.tree, self.root, self.base_url)
        self.assertEqual(urls["role"]["id"], self.app)
        self.assertEqual(urls["role"]["version"], "latest")

    def test_base_url_trailing_slash_normalized(self):
        urls_with = _to_url_tree(self.tree, self.root, self.base_url + "/")
        urls_without = _to_url_tree(self.tree, self.root, self.base_url)
        self.assertEqual(urls_with["shared"]["css"], urls_without["shared"]["css"])

    def test_different_apps_produce_different_role_urls(self):
        tree_other = _cdn_paths(self.root, "web-app-nextcloud", "latest")
        urls_a = _to_url_tree(self.tree, self.root, self.base_url)
        urls_b = _to_url_tree(tree_other, self.root, self.base_url)
        self.assertNotEqual(
            urls_a["role"]["release"]["css"],
            urls_b["role"]["release"]["css"],
        )


if __name__ == "__main__":
    unittest.main()
