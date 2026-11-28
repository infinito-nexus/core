from __future__ import annotations

import unittest
from urllib.parse import urlsplit

from utils.cache.hosts import declarations, hosts_serving, repo_named

OWNER = "svc-cache-package"
UNHIJACKED = {"raw-nixos-cache": "cache.nixos.org"}


class TestUnhijackedRepos(unittest.TestCase):
    def test_each_is_a_raw_proxy_of_its_origin_no_host_routes_to(self) -> None:
        hijacked = {entry.host for entry in declarations().hosts}
        for name, origin in UNHIJACKED.items():
            with self.subTest(repo=name):
                repo = repo_named(name)
                self.assertIsNotNone(repo, f"{name} is declared by no role")
                parts = urlsplit(repo.upstream)
                self.assertEqual(
                    (repo.role, repo.flavor, parts.scheme, parts.hostname, parts.path),
                    (OWNER, "raw", "https", origin, "/"),
                )
                self.assertEqual(hosts_serving(name), [])
                self.assertNotIn(origin, hijacked)


if __name__ == "__main__":
    unittest.main()
