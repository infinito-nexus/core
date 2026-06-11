"""Unit tests for ``plugins/lookup/objstore.py``.

The lookup branches on which object-store engine (seaweedfs|minio) the
consumer has enabled and yields a uniform S3 connection payload.
``get_merged_applications`` is mocked so the tests stay hermetic.
"""

import importlib.util
import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _DummyTemplar:
    def __init__(self, available_variables):
        self.available_variables = available_variables


class ObjstoreLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module("plugins/lookup/objstore.py", "lookup_objstore")

    def _make_lookup(self, available_vars: dict):
        lm = self.mod.LookupModule()
        lm._templar = _DummyTemplar(available_vars)
        return lm

    @staticmethod
    def _fake_get_entity_name(role_name: str) -> str:
        """
        Make entity resolution deterministic for unit tests (no filesystem access).
        Mirrors the typical behavior for your role naming.
        """
        role_name = role_name.strip()
        for prefix in ("web-app-", "web-svc-", "svc-db-", "svc-", "persona-"):
            if role_name.startswith(prefix):
                return role_name[len(prefix) :]
        return role_name

    def _run(self, terms, applications, vars_=None):
        if vars_ is None:
            vars_ = {"DIR_COMPOSITIONS": "/opt/compose/"}
        lookup = self._make_lookup(vars_)
        with (
            patch.object(
                self.mod, "get_merged_applications", return_value=applications
            ),
            patch.object(
                self.mod, "get_entity_name", side_effect=self._fake_get_entity_name
            ),
        ):
            return lookup.run(terms, variables=vars_)

    def test_invalid_terms_raises(self):
        with self.assertRaises(AnsibleError):
            self._run([], {})

        with self.assertRaises(AnsibleError):
            self._run(["a", "b", "c"], {})

    def test_empty_consumer_id_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(["   "], {})

    def test_missing_dir_compositions_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(["web-app-foo"], {"web-app-foo": {"services": {}}}, vars_={})

    def test_no_engine_enabled_returns_disabled_payload(self):
        applications = {"web-app-foo": {"services": {}}}

        out = self._run(["web-app-foo"], applications)[0]

        self.assertEqual(out["id"], "")
        self.assertEqual(out["engine"], "")
        self.assertFalse(out["enabled"])
        self.assertFalse(out["shared"])
        self.assertFalse(out["local"])
        self.assertEqual(out["host"], "")
        self.assertEqual(out["port"], "")
        self.assertEqual(out["network"], "")
        self.assertEqual(out["container"], "")
        self.assertEqual(out["bucket"], "foo")
        self.assertEqual(out["access_key"], "foo")
        self.assertEqual(out["secret_key"], "")
        self.assertEqual(out["region"], "us-east-1")
        self.assertEqual(out["env"], "")
        self.assertEqual(out["volume"], "")
        self.assertEqual(out["endpoint"], "")
        self.assertEqual(out["url"], "")
        self.assertEqual(out["public_domain"], "")
        self.assertEqual(out["public_bucket"], "")
        self.assertEqual(out["public_url"], "")
        self.assertEqual(out["reach_host"], "127.0.0.1")

        self.assertEqual(self._run(["web-app-foo", "url"], applications)[0], "")

    def test_seaweedfs_shared_uses_central_provider_values(self):
        applications = {
            "web-app-foo": {
                "services": {"seaweedfs": {"enabled": True, "shared": True}},
                "credentials": {"objstore_secret_key": "sk"},
            },
            "web-app-seaweedfs": {
                "services": {
                    "seaweedfs": {"name": "seaweedfs-central", "api_port": 8334}
                },
                "server": {
                    "domains": {"canonical": {"api": "api.seaweedfs.s3.example.com"}}
                },
            },
        }

        out = self._run(["web-app-foo"], applications)[0]

        self.assertEqual(out["id"], "web-app-seaweedfs")
        self.assertEqual(out["engine"], "seaweedfs")
        self.assertTrue(out["enabled"])
        self.assertTrue(out["shared"])
        self.assertFalse(out["local"])
        self.assertEqual(out["host"], "seaweedfs-central")
        self.assertEqual(out["port"], 8334)
        self.assertEqual(out["network"], "seaweedfs")
        self.assertEqual(out["container"], "seaweedfs-central")
        self.assertEqual(out["volume"], "")
        self.assertEqual(out["endpoint"], "seaweedfs-central:8334")
        self.assertEqual(out["url"], "http://seaweedfs-central:8334")
        self.assertEqual(out["public_domain"], "api.seaweedfs.s3.example.com")
        self.assertEqual(out["public_bucket"], "api.seaweedfs.s3.example.com/foo")
        self.assertEqual(out["public_url"], "https://api.seaweedfs.s3.example.com/foo")

        self.assertEqual(
            self._run(["web-app-foo", "url"], applications)[0],
            "http://seaweedfs-central:8334",
        )

    def test_public_url_scheme_follows_provider_tls(self):
        applications = {
            "web-app-foo": {
                "services": {"minio": {"enabled": True, "shared": True}},
                "credentials": {"objstore_secret_key": "sk"},
            },
            "web-app-minio": {
                "services": {"minio": {"name": "minio-central"}},
                "server": {
                    "tls": {"enabled": False},
                    "domains": {"canonical": {"api": "api.minio.s3.example.com"}},
                },
            },
        }

        out = self._run(["web-app-foo"], applications)[0]

        self.assertEqual(out["public_domain"], "api.minio.s3.example.com")
        self.assertEqual(out["public_url"], "http://api.minio.s3.example.com/foo")

    def test_seaweedfs_dedicated_matches_embedded_instance(self):
        applications = {
            "web-app-foo": {
                "services": {"seaweedfs": {"enabled": True, "shared": False}},
                "credentials": {"objstore_secret_key": "sk"},
            }
        }

        out = self._run(["web-app-foo"], applications)[0]

        self.assertEqual(out["id"], "web-app-seaweedfs")
        self.assertEqual(out["engine"], "seaweedfs")
        self.assertTrue(out["enabled"])
        self.assertFalse(out["shared"])
        self.assertTrue(out["local"])
        self.assertEqual(out["host"], "seaweedfs")
        self.assertEqual(out["port"], 8333)
        self.assertEqual(out["network"], "foo")
        self.assertEqual(out["container"], "foo-seaweedfs")
        self.assertEqual(out["volume"], "foo_seaweedfs")
        self.assertEqual(out["url"], "http://seaweedfs:8333")
        self.assertEqual(out["env"], "/opt/compose/foo/.env/objstore.env")
        self.assertEqual(out["image"], "chrislusf/seaweedfs")
        self.assertEqual(out["version"], "latest")

    def test_minio_shared_defaults_port_9000(self):
        applications = {
            "web-app-foo": {
                "services": {"minio": {"enabled": True, "shared": True}},
                "credentials": {"objstore_secret_key": "sk"},
            },
            "web-app-minio": {"services": {"minio": {"name": "minio-central"}}},
        }

        out = self._run(["web-app-foo"], applications)[0]

        self.assertEqual(out["id"], "web-app-minio")
        self.assertEqual(out["engine"], "minio")
        self.assertTrue(out["enabled"])
        self.assertTrue(out["shared"])
        self.assertFalse(out["local"])
        self.assertEqual(out["host"], "minio-central")
        self.assertEqual(out["port"], 9000)
        self.assertEqual(out["network"], "minio")
        self.assertEqual(out["url"], "http://minio-central:9000")

    def test_multiple_engines_enabled_raises(self):
        applications = {
            "web-app-foo": {
                "services": {
                    "seaweedfs": {"enabled": True, "shared": False},
                    "minio": {"enabled": True, "shared": False},
                }
            }
        }

        with self.assertRaises(AnsibleError):
            self._run(["web-app-foo"], applications)

    def test_secret_key_and_public_passthrough(self):
        applications = {
            "web-app-foo": {
                "services": {
                    "seaweedfs": {"enabled": True, "shared": False, "public": True}
                },
                "credentials": {"objstore_secret_key": "s3cr3t"},
            }
        }

        out = self._run(["web-app-foo"], applications)[0]

        self.assertEqual(out["secret_key"], "s3cr3t")
        self.assertTrue(out["public"])
        self.assertEqual(out["access_key"], "foo")
        self.assertEqual(out["bucket"], "foo")

        self.assertEqual(
            self._run(["web-app-foo", "secret_key"], applications)[0], "s3cr3t"
        )


if __name__ == "__main__":
    unittest.main()
