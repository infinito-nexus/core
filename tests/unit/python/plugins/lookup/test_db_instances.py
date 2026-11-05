import unittest
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

from plugins.lookup.db_instances import LookupModule


def _conflicts(applications):
    applications_lookup = MagicMock()
    applications_lookup.run.return_value = [applications]
    with patch(
        "plugins.lookup.db_instances.lookup_loader.get",
        return_value=applications_lookup,
    ):
        lookup = LookupModule()
        lookup._templar = None
        return lookup.run(["svc-db-openldap"], variables={}, exposure_conflicts=True)[0]


class TestExposureConflictsLookup(unittest.TestCase):
    def test_private_engine_is_clear(self):
        self.assertEqual(
            _conflicts({"svc-db-openldap": {"services": {"openldap": {}}}}), []
        )

    def test_public_ldaps_is_reported(self):
        applications = {
            "svc-db-openldap": {"services": {"openldap": {"network": {"public": True}}}}
        }
        conflicts = _conflicts(applications)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("network.public", conflicts[0])


def _run(terms, **variables):
    lookup = LookupModule()
    lookup._templar = None
    return lookup.run(terms, variables=variables)[0]


class TestDbInstancesLookup(unittest.TestCase):
    def test_reads_group_and_mode(self):
        hosts = ["m1", "m2", "m3"]
        result = _run(
            ["svc-db-redis"],
            DEPLOYMENT_MODE="swarm",
            groups={"svc-db-redis": hosts, "svc-swarm-node": hosts},
        )
        self.assertEqual(result["form"], "ha")
        self.assertEqual(result["instances"][2]["service"], "redis-m3")

    def test_defaults_to_application_id(self):
        result = _run([], application_id="svc-db-mariadb", groups={})
        self.assertEqual(result["form"], "standalone")
        self.assertEqual(result["instances"][0]["service"], "mariadb")

    def test_ineligible_host_is_ansible_error(self):
        with self.assertRaises(AnsibleError):
            _run(
                ["svc-db-postgres"],
                DEPLOYMENT_MODE="swarm",
                groups={"svc-db-postgres": ["a", "b", "c"], "svc-swarm-node": ["a"]},
            )

    def test_etcd_defaults_to_managers(self):
        hosts = ["m1", "m2", "m3"]
        result = _run(
            ["svc-dcs-etcd"],
            DEPLOYMENT_MODE="swarm",
            groups={"svc-swarm-manager": hosts, "svc-swarm-node": hosts},
        )
        self.assertEqual(result["form"], "ha")
        self.assertEqual(result["instances"][0]["service"], "etcd-m1")

    def test_coordination_store_needed(self):
        hosts = ["m1", "m2", "m3"]
        lookup = LookupModule()
        lookup._templar = None
        needed = lookup.run(
            [],
            variables={
                "DEPLOYMENT_MODE": "swarm",
                "groups": {"svc-db-postgres": hosts, "svc-swarm-node": hosts},
            },
            coordination_store_needed=True,
        )
        self.assertEqual(needed, [True])

    def test_too_many_terms(self):
        with self.assertRaises(AnsibleError):
            _run(["svc-db-postgres", "x"])


if __name__ == "__main__":
    unittest.main()
