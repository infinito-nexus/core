import unittest
from typing import ClassVar

from utils.roles.db.instances import (
    DbInstancesError,
    build_instances,
    coordination_store_needed,
    departed_instance_services,
    engine_hosts,
    engine_word,
    ha_exposure_conflicts,
    instance_service,
    instance_volume_name,
    sanitize_host_id,
)

NODES = ["mgr-01", "mgr-02", "mgr-03", "wrk-01"]


class TestHaExposureConflicts(unittest.TestCase):
    def test_private_engine_has_no_conflict(self):
        config = {"services": {"openldap": {"network": {"public": False}}}}
        self.assertEqual(
            ha_exposure_conflicts("svc-db-openldap", config, tor_reachable=False), []
        )

    def test_engine_without_network_block_has_no_conflict(self):
        config = {"services": {"postgres": {"ports": {"local": {"postgres": 5432}}}}}
        self.assertEqual(
            ha_exposure_conflicts("svc-db-postgres", config, tor_reachable=False), []
        )

    def test_public_service_conflicts(self):
        config = {"services": {"openldap": {"network": {"public": True}}}}
        conflicts = ha_exposure_conflicts(
            "svc-db-openldap", config, tor_reachable=False
        )
        self.assertEqual(len(conflicts), 1)
        self.assertIn("services.openldap.network.public", conflicts[0])

    def test_tor_reachability_conflicts(self):
        config = {"services": {"mariadb": {}}}
        conflicts = ha_exposure_conflicts("svc-db-mariadb", config, tor_reachable=True)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("Tor", conflicts[0])

    def test_both_conflicts_are_reported(self):
        config = {"services": {"openldap": {"network": {"public": "true"}}}}
        self.assertEqual(
            len(ha_exposure_conflicts("svc-db-openldap", config, tor_reachable=True)),
            2,
        )


class TestHelpers(unittest.TestCase):
    def test_engine_word(self):
        self.assertEqual(engine_word("svc-db-postgres"), "postgres")
        self.assertEqual(engine_word("svc-dcs-etcd"), "etcd")

    def test_engine_word_rejects_other_roles(self):
        with self.assertRaises(DbInstancesError):
            engine_word("web-app-gitea")

    def test_sanitize_host_id(self):
        self.assertEqual(sanitize_host_id("Node_01.example.org"), "node-01-example-org")
        self.assertEqual(sanitize_host_id("--a--"), "a")

    def test_instance_service_names_the_instance_and_its_sidecar(self):
        model = build_instances(
            "svc-db-redis",
            NODES[:3],
            deployment_mode="swarm",
            swarm_nodes=NODES,
        )
        instance = model["instances"][1]
        self.assertEqual(instance_service("svc-db-redis", instance), "redis-mgr-02")
        self.assertEqual(
            instance_service("svc-db-redis", instance, "redis"), "redis-mgr-02"
        )
        self.assertEqual(
            instance_service("svc-db-redis", instance, "sentinel"),
            "redis-sentinel-mgr-02",
        )

    def test_sidecar_of_a_standalone_instance_raises(self):
        model = build_instances("svc-db-redis", [], deployment_mode="swarm")
        with self.assertRaises(DbInstancesError):
            instance_service("svc-db-redis", model["instances"][0], "sentinel")


class TestBuildInstances(unittest.TestCase):
    def build(self, hosts, mode="swarm", nodes=NODES, legacy_host=None):
        return build_instances(
            "svc-db-postgres",
            hosts,
            deployment_mode=mode,
            swarm_nodes=nodes,
            legacy_volume_host=legacy_host,
        )

    def test_no_hosts_is_standalone_with_todays_names(self):
        result = self.build([])
        self.assertEqual(result["form"], "standalone")
        self.assertEqual(
            result["instances"],
            [
                {
                    "host": None,
                    "host_id": None,
                    "service": "postgres",
                    "volume": "postgres_data",
                    "legacy": True,
                }
            ],
        )

    def test_one_host_is_standalone(self):
        result = self.build(["mgr-01"])
        self.assertEqual(result["form"], "standalone")
        self.assertEqual(result["instances"][0]["service"], "postgres")
        self.assertEqual(result["instances"][0]["host"], "mgr-01")
        self.assertEqual(result["warnings"], [])

    def test_compose_mode_is_always_standalone(self):
        result = self.build(["mgr-01", "mgr-02", "mgr-03"], mode="compose")
        self.assertEqual(result["form"], "standalone")
        self.assertEqual(len(result["instances"]), 1)

    def test_three_hosts_render_ha_instances(self):
        result = self.build(["mgr-01", "mgr-02", "mgr-03"])
        self.assertEqual(result["form"], "ha")
        self.assertEqual(
            [i["service"] for i in result["instances"]],
            ["postgres-mgr-01", "postgres-mgr-02", "postgres-mgr-03"],
        )
        self.assertEqual(
            [i["volume"] for i in result["instances"]],
            ["postgres_data", "postgres_data_mgr-02", "postgres_data_mgr-03"],
        )
        self.assertEqual(result["warnings"], [])

    def test_names_keep_engine_word(self):
        for inst in self.build(["mgr-01", "mgr-02", "mgr-03"])["instances"]:
            self.assertIn("postgres", inst["service"])
            self.assertIn("postgres", inst["volume"])

    def test_two_hosts_render_ha_with_warning(self):
        result = self.build(["mgr-01", "mgr-02"])
        self.assertEqual(result["form"], "ha")
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("drain", result["warnings"][0])

    def test_legacy_volume_host_adopts_legacy_volume(self):
        result = self.build(["mgr-01", "mgr-02", "mgr-03"], legacy_host="mgr-01")
        self.assertEqual(result["instances"][0]["volume"], "postgres_data")
        self.assertEqual(result["instances"][1]["volume"], "postgres_data_mgr-02")

    def test_order_independent_identity(self):
        a = self.build(["mgr-01", "mgr-02", "mgr-03"])["instances"]
        b = self.build(["mgr-03", "mgr-01", "mgr-02"])["instances"]
        self.assertEqual(
            {i["host"]: i["service"] for i in a},
            {i["host"]: i["service"] for i in b},
        )

    def test_host_outside_swarm_nodes_raises(self):
        with self.assertRaisesRegex(DbInstancesError, "outsider"):
            self.build(["mgr-01", "mgr-02", "outsider"])

    def test_explicit_legacy_host_overrides_first_host(self):
        result = self.build(["mgr-01", "mgr-02", "mgr-03"], legacy_host="mgr-02")
        self.assertEqual(result["instances"][0]["volume"], "postgres_data_mgr-01")
        self.assertEqual(result["instances"][1]["volume"], "postgres_data")

    def test_instance_volume_name(self):
        result = self.build(["mgr-01", "mgr-02", "mgr-03"], legacy_host="mgr-01")
        legacy, fresh = result["instances"][0], result["instances"][1]
        self.assertEqual(
            instance_volume_name("openldap_config", legacy), "openldap_config"
        )
        self.assertEqual(
            instance_volume_name("openldap_config", fresh), "openldap_config_mgr-02"
        )
        self.assertEqual(instance_volume_name("x", None), "x")

    def test_engine_without_v1_ha_stays_standalone(self):
        result = build_instances(
            "svc-db-qdrant",
            ["mgr-01", "mgr-02", "mgr-03"],
            deployment_mode="swarm",
            swarm_nodes=NODES,
        )
        self.assertEqual(result["form"], "standalone")

    def test_etcd_three_members_render_ha(self):
        result = build_instances(
            "svc-dcs-etcd",
            ["mgr-01", "mgr-02", "mgr-03"],
            deployment_mode="swarm",
            swarm_nodes=NODES,
        )
        self.assertEqual(result["form"], "ha")
        self.assertEqual(
            [i["service"] for i in result["instances"]],
            ["etcd-mgr-01", "etcd-mgr-02", "etcd-mgr-03"],
        )

    def test_host_id_collision_raises(self):
        with self.assertRaisesRegex(DbInstancesError, "collide"):
            self.build(
                ["node.a", "node_a", "mgr-01"], nodes=["node.a", "node_a", "mgr-01"]
            )


class TestCoordinationStore(unittest.TestCase):
    def test_etcd_hosts_default_to_managers(self):
        groups = {"svc-swarm-manager": ["m1", "m2", "m3"]}
        self.assertEqual(engine_hosts("svc-dcs-etcd", groups), ["m1", "m2", "m3"])

    def test_explicit_etcd_group_wins(self):
        groups = {"svc-swarm-manager": ["m1", "m2", "m3"], "svc-dcs-etcd": ["m1"]}
        self.assertEqual(engine_hosts("svc-dcs-etcd", groups), ["m1"])

    def test_engine_hosts_have_no_default(self):
        groups = {"svc-swarm-manager": ["m1", "m2", "m3"]}
        self.assertEqual(engine_hosts("svc-db-postgres", groups), [])

    def test_not_needed_when_all_engines_standalone(self):
        groups = {"svc-swarm-node": NODES, "svc-db-postgres": ["mgr-01"]}
        self.assertFalse(coordination_store_needed(groups, "swarm"))

    def test_needed_when_one_engine_is_ha(self):
        groups = {
            "svc-swarm-node": NODES,
            "svc-db-mariadb": ["mgr-01", "mgr-02", "mgr-03"],
        }
        self.assertTrue(coordination_store_needed(groups, "swarm"))

    def test_etcd_group_alone_does_not_trigger(self):
        groups = {
            "svc-swarm-node": NODES,
            "svc-dcs-etcd": ["mgr-01", "mgr-02", "mgr-03"],
        }
        self.assertFalse(coordination_store_needed(groups, "swarm"))

    def test_redis_alone_does_not_need_the_store(self):
        groups = {
            "svc-swarm-node": NODES,
            "svc-db-redis": ["mgr-01", "mgr-02", "mgr-03"],
        }
        self.assertFalse(coordination_store_needed(groups, "swarm"))

    def test_never_needed_outside_swarm(self):
        groups = {"svc-db-postgres": ["mgr-01", "mgr-02", "mgr-03"]}
        self.assertFalse(coordination_store_needed(groups, "compose"))


class TestDepartedInstanceServices(unittest.TestCase):
    LIVE: ClassVar[list[str]] = [
        "redis_redis-mgr-01",
        "redis_redis-mgr-02",
        "redis_redis-mgr-03",
        "redis_redis-sentinel-mgr-01",
        "redis_redis-sentinel-mgr-02",
        "redis_redis-sentinel-mgr-03",
        "redis_redis",
    ]

    def test_removes_instance_and_sidecar_of_departed_host(self):
        declared = [
            "redis",
            "redis-mgr-01",
            "redis-mgr-02",
            "redis-wrk-01",
            "redis-sentinel-mgr-01",
            "redis-sentinel-mgr-02",
            "redis-sentinel-wrk-01",
        ]
        self.assertEqual(
            departed_instance_services("svc-db-redis", "redis", self.LIVE, declared),
            ["redis_redis-mgr-03", "redis_redis-sentinel-mgr-03"],
        )

    def test_nothing_departed(self):
        declared = [name.split("_", 1)[1] for name in self.LIVE]
        self.assertEqual(
            departed_instance_services("svc-db-redis", "redis", self.LIVE, declared),
            [],
        )

    def test_a_role_without_an_ha_form_has_nothing_to_depart(self):
        self.assertEqual(
            departed_instance_services(
                "svc-db-memcached",
                "memcached",
                ["memcached_memcached", "memcached_memcached-mgr-02"],
                ["memcached"],
            ),
            [],
        )

    def test_never_touches_the_engine_service_or_foreign_names(self):
        live = ["redis_redis", "redis_other-mgr-03", "postgres_redis-mgr-03"]
        self.assertEqual(
            departed_instance_services("svc-db-redis", "redis", live, ["redis-mgr-01"]),
            [],
        )

    def test_refuses_empty_declaration(self):
        with self.assertRaises(DbInstancesError):
            departed_instance_services("svc-db-redis", "redis", self.LIVE, [])

    def test_etcd_members(self):
        live = ["etcd_etcd-mgr-01", "etcd_etcd-mgr-02", "etcd_etcd-mgr-03"]
        declared = ["etcd-mgr-01", "etcd-mgr-02", "etcd-mgr-04"]
        self.assertEqual(
            departed_instance_services("svc-dcs-etcd", "etcd", live, declared),
            ["etcd_etcd-mgr-03"],
        )


if __name__ == "__main__":
    unittest.main()
