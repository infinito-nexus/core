import unittest
from unittest import mock
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
        if len(terms) != 2 or terms[1] != "protocols.web":
            raise AssertionError(f"Unexpected terms passed to tls: {terms}")

        # Legacy kwarg want must be ignored; if it appears, fail (we don't expect it anymore)
        if kwargs.get("want"):
            raise AssertionError(f"Unexpected want kwarg passed to tls: {kwargs}")

        return [self._protocol]


class TestNginxPathsLookup(unittest.TestCase):
    def setUp(self):
        self.plugin = LookupModule()
        self.plugin._loader = mock.MagicMock()
        self.applications = {"svc-prx-openresty": {"docker": {"volumes": {}}}}
        self.variables = {
            "applications": self.applications,
        }

    def _fake_get(self, applications, app_id, key, strict=True):
        if key == "volumes.www.path":
            return "/opt/mock/www"
        if key == "volumes.nginx.path":
            return "/opt/mock/nginx"
        raise KeyError(key)

    def _loader_get(self, tls=None):
        def _get(name, *a, **k):
            if name == "applications":
                return mock.MagicMock(run=lambda *_a, **_k: [self.applications])
            if name == "tls":
                if tls is None:
                    raise AssertionError(
                        "tls must not be called when protocol override is set"
                    )
                return tls
            raise AssertionError(f"Unexpected lookup requested: {name}")

        return _get

    def _run(self, terms, **kwargs):
        with (
            patch(
                "plugins.lookup.nginx.get",
                side_effect=self._fake_get,
            ),
            patch(
                "plugins.lookup.nginx.get_canonical_volumes",
                return_value={},
            ),
            patch("plugins.lookup.nginx.lookup_loader") as loader_mock,
        ):
            loader_mock.get.side_effect = self._loader_get()
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

    def test_canonical_dict_supplies_volume_paths(self):
        canonical = {
            "www": {"type": "volume", "path": "/opt/canonical/www"},
            "nginx": {"type": "volume", "path": "/opt/canonical/nginx"},
        }
        with (
            patch(
                "plugins.lookup.nginx.get",
                side_effect=AssertionError(
                    "get() must not be called when canonical paths are present"
                ),
            ),
            patch(
                "plugins.lookup.nginx.get_canonical_volumes",
                return_value=canonical,
            ),
            patch("plugins.lookup.nginx.lookup_loader") as loader_mock,
        ):
            loader_mock.get.side_effect = self._loader_get()
            out = self.plugin.run(["files.configuration"], variables=self.variables)[0]
        self.assertEqual(out, "/opt/canonical/nginx/nginx.conf")

    def test_domain_uses_tls_when_no_override(self):
        fake_tls = _FakeTlsResolveLookup("https")

        with (
            patch(
                "plugins.lookup.nginx.get",
                side_effect=self._fake_get,
            ),
            patch(
                "plugins.lookup.nginx.get_canonical_volumes",
                return_value={},
            ),
            patch("plugins.lookup.nginx.lookup_loader") as loader_mock,
        ):
            loader_mock.get.side_effect = self._loader_get(tls=fake_tls)
            out = self.plugin.run(
                ["files.domain", "example.com"], variables=self.variables
            )[0]

        self.assertEqual(
            out,
            "/opt/mock/nginx/conf.d/servers/https/example.com.conf",
        )

    def test_domain_protocol_override_http(self):
        with (
            patch(
                "plugins.lookup.nginx.get",
                side_effect=self._fake_get,
            ),
            patch(
                "plugins.lookup.nginx.get_canonical_volumes",
                return_value={},
            ),
            patch("plugins.lookup.nginx.lookup_loader") as loader_mock,
        ):
            loader_mock.get.side_effect = self._loader_get()
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
        with (
            patch(
                "plugins.lookup.nginx.get",
                side_effect=self._fake_get,
            ),
            patch(
                "plugins.lookup.nginx.get_canonical_volumes",
                return_value={},
            ),
            patch("plugins.lookup.nginx.lookup_loader") as loader_mock,
            self.assertRaises(AnsibleError),
        ):
            loader_mock.get.side_effect = self._loader_get()
            self.plugin.run(
                ["files.domain", "example.com"],
                variables=self.variables,
                protocol="ftp",
            )

    def test_invalid_usage_raises(self):
        with (
            patch(
                "plugins.lookup.nginx.get",
                side_effect=self._fake_get,
            ),
            patch(
                "plugins.lookup.nginx.get_canonical_volumes",
                return_value={},
            ),
            patch("plugins.lookup.nginx.lookup_loader") as loader_mock,
        ):
            loader_mock.get.side_effect = self._loader_get()

            with self.assertRaises(AnsibleError):
                self.plugin.run([], variables=self.variables)

            with self.assertRaises(AnsibleError):
                self.plugin.run(
                    ["files.domain", "example.com", "extra"], variables=self.variables
                )


if __name__ == "__main__":
    unittest.main()
