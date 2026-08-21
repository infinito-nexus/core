from __future__ import annotations

import unittest

from ansible.errors import AnsibleError

from plugins.lookup.tor_socks import resolve_socks_endpoint

_APPS = {"svc-net-tor": {"services": {"tor": {"ports": {"local": {"socks": 9050}}}}}}


class TestTorSocks(unittest.TestCase):
    def test_default_loopback_host(self) -> None:
        self.assertEqual(resolve_socks_endpoint(_APPS, "127.0.0.1"), "127.0.0.1:9050")

    def test_custom_host(self) -> None:
        self.assertEqual(
            resolve_socks_endpoint(_APPS, "host.docker.internal"),
            "host.docker.internal:9050",
        )
        self.assertEqual(
            resolve_socks_endpoint(_APPS, "0.0.0.0"),  # noqa: S104  test string, not a bind
            "0.0.0.0:9050",
        )

    def test_missing_spot_raises(self) -> None:
        with self.assertRaises(AnsibleError):
            resolve_socks_endpoint({}, "127.0.0.1")
        with self.assertRaises(AnsibleError):
            resolve_socks_endpoint(
                {"svc-net-tor": {"services": {"tor": {"ports": {}}}}}, "127.0.0.1"
            )


if __name__ == "__main__":
    unittest.main()
