import unittest

from plugins.filter.csp_filters import FilterModule


def _connect_src(header: str) -> list[str]:
    for raw in header.split(";"):
        part = raw.strip()
        if part.startswith("connect-src "):
            return part.split()[1:]
    return []


class TestCspToggleApi(unittest.TestCase):
    def _header(self, api_enabled: bool) -> str:
        apps = {
            "app1": {
                "services": {"api": {"enabled": api_enabled}},
                "server": {"csp": {"whitelist": {}, "flags": {}, "hashes": {}}},
            }
        }
        domains = {
            "web-svc-api": ["api.example.org"],
            "web-svc-cdn": ["cdn.example.org"],
        }
        return FilterModule().build_csp_header(apps, "app1", domains, "https")

    def test_enabled_api_service_admits_the_api_origin(self):
        self.assertIn("https://api.example.org", _connect_src(self._header(True)))

    def test_disabled_api_service_keeps_the_api_origin_out(self):
        self.assertNotIn("https://api.example.org", _connect_src(self._header(False)))


if __name__ == "__main__":
    unittest.main()
