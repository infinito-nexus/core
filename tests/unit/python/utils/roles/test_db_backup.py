import unittest

from utils.roles.db.backup import ha_instance_hosts, local_backup_instances

NODES = ["mgr-01", "mgr-02", "mgr-03"]


def _groups(**engines):
    groups = {"svc-swarm-node": NODES}
    groups.update({k.replace("_", "-"): v for k, v in engines.items()})
    return groups


class TestHaInstanceHosts(unittest.TestCase):
    def test_standalone_engines_have_no_ha_hosts(self):
        groups = _groups(svc_db_postgres=["mgr-01"])
        self.assertEqual(ha_instance_hosts(groups, "swarm"), [])

    def test_compose_never_renders_ha(self):
        groups = _groups(svc_db_postgres=NODES)
        self.assertEqual(ha_instance_hosts(groups, "compose"), [])

    def test_union_of_dumped_engines(self):
        groups = _groups(svc_db_postgres=NODES[:2], svc_db_mariadb=NODES[1:])
        self.assertEqual(ha_instance_hosts(groups, "swarm"), NODES)

    def test_redis_is_not_backed_up(self):
        groups = _groups(svc_db_redis=NODES)
        self.assertEqual(ha_instance_hosts(groups, "swarm"), [])


class TestLocalBackupInstances(unittest.TestCase):
    def test_local_instances_keep_engine_word_and_volume(self):
        groups = _groups(svc_db_postgres=NODES, svc_db_openldap=NODES)
        local = local_backup_instances(groups, "swarm", "mgr-02", "/usr/bin")
        self.assertEqual(
            local,
            [
                {
                    "engine": "openldap",
                    "service": "openldap_openldap-mgr-02",
                    "volume": "openldap_data_mgr-02",
                    "probe": [
                        "/usr/bin/primary-probe-openldap",
                        "openldap",
                        "openldap-mgr-02",
                    ],
                    "sql": False,
                },
                {
                    "engine": "postgres",
                    "service": "postgres_postgres-mgr-02",
                    "volume": "postgres_data_mgr-02",
                    "probe": [
                        "/usr/bin/primary-probe-postgres",
                        "postgres",
                        "postgres-mgr-02",
                    ],
                    "sql": True,
                },
            ],
        )

    def test_first_host_keeps_legacy_volume(self):
        groups = _groups(svc_db_mariadb=NODES)
        local = local_backup_instances(groups, "swarm", "mgr-01", "/usr/bin")
        self.assertEqual(local[0]["volume"], "mariadb_data")

    def test_host_without_instance(self):
        groups = _groups(svc_db_postgres=NODES[:2])
        self.assertEqual(
            local_backup_instances(groups, "swarm", "mgr-03", "/usr/bin"), []
        )


if __name__ == "__main__":
    unittest.main()
