import importlib.util
import unittest

from . import PROJECT_ROOT


def _load_module():
    path = PROJECT_ROOT / "roles/svc-stack/filter_plugins/front_proxy_batch.py"
    spec = importlib.util.spec_from_file_location("front_proxy_batch", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


PROBE = {"url": "https://x.example/", "status_codes": [200]}
VHOSTS = {
    "x.example": {"consumer": "web-app-x", "changed": True, "probe": PROBE},
    "www.x.example": {"consumer": "web-app-www", "changed": False, "probe": PROBE},
    "y.example": {"consumer": "web-app-x", "changed": False, "probe": PROBE},
}


class TestFrontProxyBatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_the_cited_config_file_names_its_consumer_only(self):
        error = (
            'unknown directive "bogus" in /etc/nginx/servers/https/www.x.example.conf:3'
        )
        self.assertEqual(
            self.module.front_proxy_batch_culprits(VHOSTS, error), ["web-app-www"]
        )

    def test_a_consumer_cited_twice_is_named_once(self):
        error = "/srv/http/x.example.conf:1 and /srv/https/y.example.conf:9"
        self.assertEqual(
            self.module.front_proxy_batch_culprits(VHOSTS, error), ["web-app-x"]
        )

    def test_an_error_citing_no_vhost_names_nobody(self):
        self.assertEqual(
            self.module.front_proxy_batch_culprits(VHOSTS, "container is restarting"),
            [],
        )

    def test_only_changed_vhosts_are_rechecked(self):
        self.assertEqual(
            self.module.front_proxy_batch_rechecks(VHOSTS), {"x.example": PROBE}
        )


if __name__ == "__main__":
    unittest.main()
