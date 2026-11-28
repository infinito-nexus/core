import unittest

from ansible._internal._datatag._tags import TrustedAsTemplate
from ansible.errors import AnsibleError

from plugins.lookup.patroni_config import LookupModule
from utils.cache.yaml import load_yaml_str

SUBNET = "192.168.200.0/24"


def _file_kwargs():
    return {
        "scope": "postgres",
        "namespace": "/service/",
        "etcd_hosts": ["etcd-a:2379"],
        "etcd_cacert": "/ca",
        "etcd_username": "patroni",
        "etcd_password": "e",
        "restapi_port": 8008,
        "restapi_username": "patroni",
        "restapi_password": "r",
        "superuser": "postgres",
        "superuser_password": "s",
        "replication_user": "replicator",
        "replication_password": "p",
        "rewind_user": "rewinder",
        "rewind_password": "w",
        "data_dir": "/d",
        "bin_dir": "/b",
        "postgres_port": 5432,
        "parameters": {},
        "replication_subnet": SUBNET,
    }


class TestPatroniConfigLookup(unittest.TestCase):
    def test_dynamic(self):
        dcs = LookupModule().run(
            ["dynamic"],
            parameters={"max_connections": 10},
            replication_subnet=SUBNET,
            replication_user="replicator",
            rewind_user="rewinder",
        )[0]
        self.assertEqual(dcs["postgresql"]["parameters"]["max_connections"], 10)

    def test_file(self):
        text = LookupModule().run(["file"], **_file_kwargs())[0]
        self.assertEqual(load_yaml_str(text)["scope"], "postgres")

    def test_file_accepts_ansible_tagged_values(self):
        kwargs = _file_kwargs()
        kwargs["scope"] = TrustedAsTemplate().tag("postgres")
        kwargs["etcd_hosts"] = [TrustedAsTemplate().tag("etcd-a:2379")]
        text = LookupModule().run(["file"], **kwargs)[0]
        self.assertEqual(load_yaml_str(text)["scope"], "postgres")

    def test_bad_term(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run(["other"])

    def test_missing_argument(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run(["dynamic"], parameters={})


if __name__ == "__main__":
    unittest.main()
