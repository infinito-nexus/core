# tests/unit/plugins/lookup/test_nginx.py
import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.nginx import LookupModule


class _FakeTlsResolveLookup:
    """
    Minimal fake lookup plugin compatible with the NEW call style:
      - run([domain, "protocols.web"], variables=...)
    """

    def __init__(self, protocol: str):
        self._protocol = protocol

    def run(self, terms, variables=None, **kwargs):
        # New API: second positional term is want-path
        if len(terms) != 2 or terms[1] != "protocols.web":
            raise AssertionError(f"Unexpected terms passed to tls: {terms}")

        # Legacy kwarg want must be ignored; if it appears, fail (we don't expect it anymore)
        if "want" in kwargs and kwargs["want"]:
            raise AssertionError(f"Unexpected want kwarg passed to tls: {kwargs}")

        return [self._protocol]


class TestNginxPathsLookup(unittest.TestCase):
    def setUp(self):
        self.plugin = LookupModule()
        self.variables = {
            "applications": {"svc-prx-openresty": {"docker": {"volumes": {}}}},
        }

    def _fake_get(self, applications, app_id, key, strict=True):
        if key == "volumes.www":
            return "/opt/mock/www"
        if key == "volumes.nginx":
            return "/opt/mock/nginx"
        raise KeyError(key)

    def _run(self, terms, **kwargs):
        with patch(
            "plugins.lookup.nginx.get",
            side_effect=self._fake_get,
        ):
            return self.plugin.run(terms, variables=self.variables, **kwargs)[0]

    def test_files_configuration_projection(self):
        out = self._run(["files.configuration"])
        self.assertEqual(out, "/opt/mock/nginx/nginx.conf")

    def test_directories_configuration_projection(self):
        out = self._run(["directories.configuration.base"])
        self.assertEqual(out, "/opt/mock/nginx/conf.d/")

    def test_directories_configuration_http_includes(self):
        out = self._run(["directories.configuration.http_includes"])
        self.assertEqual(
            out,
            [
                "/opt/mock/nginx/conf.d/global/",
                "/opt/mock/nginx/conf.d/maps/",
                "/opt/mock/nginx/conf.d/servers/http/",
                "/opt/mock/nginx/conf.d/servers/https/",
            ],
        )

    def test_directories_data_projection(self):
        out = self._run(["directories.data"])
        self.assertEqual(out["www"], "/opt/mock/www/")
        self.assertEqual(out["html"], "/opt/mock/www/public_html/")
        self.assertEqual(out["files"], "/opt/mock/www/public_files/")
        self.assertEqual(out["cdn"], "/opt/mock/www/public_cdn/")
        self.assertEqual(out["global"], "/opt/mock/www/global/")
        self.assertEqual(out["well_known"], "/usr/share/nginx/well-known/")

    def test_directories_cache_projection(self):
        out = self._run(["directories.cache"])
        self.assertEqual(out["general"], "/tmp/cache_nginx_general/")
        self.assertEqual(out["image"], "/tmp/cache_nginx_image/")

    def test_directories_ensure_projection(self):
        ensure = self._run(["directories.ensure"])
        self.assertIsInstance(ensure, list)

        self.assertIn({"path": "/tmp/cache_nginx_general/", "mode": "0700"}, ensure)
        self.assertIn({"path": "/tmp/cache_nginx_image/", "mode": "0700"}, ensure)

        ensure_paths = self._run(["directories.ensure_paths"])
        self.assertIsInstance(ensure_paths, list)
        self.assertEqual(ensure_paths, [d["path"] for d in ensure])

        # well_known is container path → must NOT be part of host dir creation
        self.assertNotIn("/usr/share/nginx/well-known/", ensure_paths)

    def test_domain_uses_tls_when_no_override(self):
        fake_tls = _FakeTlsResolveLookup("https")

        with (
            patch(
                "plugins.lookup.nginx.get",
                side_effect=self._fake_get,
            ),
            patch(
                "plugins.lookup.nginx.lookup_loader.get",
                return_value=fake_tls,
            ),
        ):
            out = self.plugin.run(
                ["files.domain", "example.com"], variables=self.variables
            )[0]

        self.assertEqual(
            out,
            "/opt/mock/nginx/conf.d/servers/https/example.com.conf",
        )

    def test_domain_protocol_override_http(self):
        # tls should NOT be consulted when override is present
        with (
            patch(
                "plugins.lookup.nginx.get",
                side_effect=self._fake_get,
            ),
            patch(
                "plugins.lookup.nginx.lookup_loader.get",
                side_effect=AssertionError(
                    "tls must not be called when protocol override is set"
                ),
            ),
        ):
            out = self.plugin.run(
                ["files.domain", "example.com"],
                variables=self.variables,
                protocol="http",
            )[0]

        self.assertEqual(
            out,
            "/opt/mock/nginx/conf.d/servers/http/example.com.conf",
        )

    def test_invalid_protocol_override_raises(self):
        with patch(
            "plugins.lookup.nginx.get",
            side_effect=self._fake_get,
        ):
            with self.assertRaises(AnsibleError):
                self.plugin.run(
                    ["files.domain", "example.com"],
                    variables=self.variables,
                    protocol="ftp",
                )

    def test_invalid_usage_raises(self):
        with patch(
            "plugins.lookup.nginx.get",
            side_effect=self._fake_get,
        ):
            # want-path missing
            with self.assertRaises(AnsibleError):
                self.plugin.run([], variables=self.variables)

            # too many terms
            with self.assertRaises(AnsibleError):
                self.plugin.run(
                    ["files.domain", "example.com", "extra"], variables=self.variables
                )


if __name__ == "__main__":
    unittest.main()
