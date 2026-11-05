from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils.cache.files import read_text
from utils.failover.swarm import SwarmLab, shell
from utils.failover.swarm import commands as swarm
from utils.roles.mapping import ROLE_FILE_META_SERVICES


class TestFaultCommands(unittest.TestCase):
    def test_instance_kill_reaches_the_container_inside_its_node(self):
        self.assertEqual(
            swarm.inject_argv("kill", node="n1", network="lab", container="c1"),
            ["docker", "exec", "n1", "docker", "kill", "c1"],
        )

    def test_node_faults_act_on_the_node_container(self):
        self.assertEqual(
            swarm.inject_argv("node", node="n1", network="lab"),
            ["docker", "kill", "n1"],
        )
        self.assertEqual(
            swarm.inject_argv("hang", node="n1", network="lab"),
            ["docker", "pause", "n1"],
        )
        self.assertEqual(
            swarm.inject_argv("partition", node="n1", network="lab"),
            ["docker", "network", "disconnect", "lab", "n1"],
        )

    def test_heal_reverses_each_node_fault(self):
        self.assertEqual(
            swarm.heal_argv("node", node="n1", network="lab"), ["docker", "start", "n1"]
        )
        self.assertEqual(
            swarm.heal_argv("hang", node="n1", network="lab"),
            ["docker", "unpause", "n1"],
        )
        self.assertEqual(
            swarm.heal_argv("partition", node="n1", network="lab", ip="10.0.0.2"),
            ["docker", "network", "connect", "--ip", "10.0.0.2", "lab", "n1"],
        )
        self.assertIsNone(swarm.heal_argv("kill", node="n1", network="lab"))

    def test_kill_needs_a_container(self):
        with self.assertRaises(ValueError):
            swarm.inject_argv("kill", node="n1", network="lab")


class _FakeCluster:
    """Answers the adapter's docker calls for a 3-instance HA engine.

    Args:
        primary_cid: container id whose primary probe succeeds.
    """

    def __init__(self, primary_cid: str):
        self.primary_cid = primary_cid
        self.ran: list[list[str]] = []
        self.placement = {
            "postgres_postgres-m1": ("m1", "c1"),
            "postgres_postgres-m2": ("m2", "c2"),
            "postgres_postgres-m3": ("m3", "c3"),
        }

    def __call__(self, argv, *, stdin=None, timeout=None):
        self.ran.append(argv)
        out, rc = "", 0
        if argv[-4:] == ["node", "ls", "--format", "{{.Hostname}} {{.ManagerStatus}}"]:
            out = "m1 Leader\nm2 Reachable\nm3 Reachable\nw1\n"
        elif argv[-4:] == ["node", "ls", "--format", "{{.Hostname}} {{.Status}}"]:
            out = "m1 Ready\nm2 Ready\nm3 Ready\nw1 Ready\n"
        elif argv[-4:] == ["service", "ls", "--format", "{{.Name}}"]:
            out = "postgres_postgres\npostgres_haproxy\n" + "\n".join(self.placement)
        elif "ps" in argv and argv[argv.index("ps") - 1] == "service":
            out = self.placement[argv[argv.index("ps") + 1]][0]
        elif argv[3:6] == ["docker", "ps", "-q"]:
            service = argv[-1].split("=", 2)[-1]
            out = self.placement[service][1]
        elif len(argv) == 6 and argv[3].endswith("/primary-probe-postgres"):
            rc = (
                0
                if self.placement[f"{argv[4]}_{argv[5]}"][1] == self.primary_cid
                else 1
            )
        elif argv[3:5] == ["docker", "exec"] and argv[2:3] != ["-i"]:
            rc = 0 if argv[5] == self.primary_cid else 1
        return mock.Mock(returncode=rc, stdout=out, stderr="")


class TestSwarmLabTargetsThePrimary(unittest.TestCase):
    def _lab(self) -> SwarmLab:
        return SwarmLab(
            engine="postgres",
            managers=["m1", "m2", "m3"],
            spare="w1",
            network="lab",
            node_ips={"m2": "10.0.0.3"},
        )

    def test_instance_kill_kills_the_primary_container_not_the_endpoint(self):
        cluster = _FakeCluster(primary_cid="c2")
        with mock.patch.object(shell, "execute", cluster):
            self._lab().inject("kill")
        self.assertEqual(
            cluster.ran[-1], ["docker", "exec", "m2", "docker", "kill", "c2"]
        )

    def test_node_fault_hits_the_primary_node_and_heal_restores_it(self):
        cluster = _FakeCluster(primary_cid="c2")
        lab = self._lab()
        with mock.patch.object(shell, "execute", cluster):
            lab.inject("partition")
            self.assertEqual(
                cluster.ran[-1], ["docker", "network", "disconnect", "lab", "m2"]
            )
            lab.heal("partition")
        self.assertIn(
            ["docker", "network", "connect", "--ip", "10.0.0.3", "lab", "m2"],
            cluster.ran,
        )
        self.assertEqual(cluster.ran[-1][5:7], ["node", "ls"])

    def test_no_primary_is_an_adapter_error(self):
        with (
            mock.patch.object(shell, "execute", _FakeCluster(primary_cid="none")),
            self.assertRaises(RuntimeError),
        ):
            self._lab().inject("node")

    def test_leader_loss_crashes_the_stack_host_and_manages_through_another(self):
        cluster = _FakeCluster(primary_cid="c1")
        lab = self._lab()
        with mock.patch.object(shell, "execute", cluster):
            lab.inject("leader")
            self.assertEqual(cluster.ran[-1], ["docker", "kill", "m1"])
            lab.instances()
            self.assertEqual(cluster.ran[-1][:4], ["docker", "exec", "-i", "m2"])
            lab.heal("leader")
        self.assertIn(["docker", "start", "m1"], cluster.ran)

    def test_writer_round_samples_every_instance(self):
        with mock.patch.object(shell, "execute", _FakeCluster(primary_cid="c3")):
            sample = self._lab().writer_round()
        self.assertEqual(
            sample.writers,
            {
                "postgres_postgres-m1": False,
                "postgres_postgres-m2": False,
                "postgres_postgres-m3": True,
            },
        )
        self.assertEqual(sample.gtids, {})

    def test_primary_instance_names_the_service(self):
        with mock.patch.object(shell, "execute", _FakeCluster(primary_cid="c2")):
            self.assertEqual(self._lab().primary_instance(), "postgres_postgres-m2")

    def test_forgetting_a_manager_promotes_the_spare_in_the_lab_view(self):
        lab = self._lab()
        lab.inventory = mock.Mock(
            dir=Path("/x"),
            devices=Path("/x/devices.yml"),
            password=Path("/x/.password"),
        )
        lab.inventory.load.return_value = {
            "all": {
                "children": {
                    "svc-swarm-manager": {
                        "hosts": {"m1": {}, "m2": {}, "m3": {}, "w1": {}}
                    }
                }
            }
        }
        with mock.patch.object(shell, "stream", return_value=0) as stream:
            self.assertEqual(lab.forget_and_replace("m3"), 0)
        self.assertEqual(lab.managers, ["m1", "m2", "w1"])
        self.assertEqual(lab.live_managers(), ["m1", "m2", "w1"])
        saved = lab.inventory.save.call_args.args[0]
        self.assertEqual(
            list(saved["all"]["children"]["svc-swarm-manager"]["hosts"]),
            ["m1", "m2", "w1"],
        )
        self.assertIn("swarm-forget-node", stream.call_args.args[0])

    def test_finish_checker_signals_the_checker_container(self):
        cluster = mock.Mock(
            return_value=mock.Mock(returncode=0, stdout="k1\n", stderr="")
        )
        with mock.patch.object(shell, "execute", cluster):
            self._lab().finish_checker()
        self.assertEqual(
            cluster.call_args.args[0],
            ["docker", "exec", "w1", "docker", "kill", "--signal", "USR1", "k1"],
        )


def _once(predicate, **_):
    return predicate()


class TestSwarmLabSettling(unittest.TestCase):
    def _lab(self) -> SwarmLab:
        return SwarmLab(
            engine="postgres",
            managers=["m1", "m2", "m3"],
            spare="w1",
            network="lab",
            node_ips={"m2": "10.0.0.3"},
        )

    def _cluster(self, leaders: str, statuses: str):
        def answer(argv, *, stdin=None, timeout=None):
            out = ""
            if argv[-1] == "{{.Hostname}} {{.ManagerStatus}}":
                out = leaders
            elif argv[-1] == "{{.Hostname}} {{.Status}}":
                out = statuses
            elif argv[:3] == ["docker", "exec", "m2"] and argv[3:] == [
                "cat",
                "/etc/resolv.conf",
            ]:
                out = "nameserver 10.0.0.53\n"
            return mock.Mock(returncode=0, stdout=out, stderr="")

        return mock.Mock(side_effect=answer)

    def test_heal_fails_while_the_swarm_has_no_leader(self):
        lab = self._lab()
        lab._faulted = "m2"
        cluster = self._cluster("m1 Reachable\nm2 Reachable\n", "m1 Ready\nm2 Ready\n")
        with (
            mock.patch.object(shell, "execute", cluster),
            mock.patch.object(shell, "wait_until", _once),
            self.assertRaisesRegex(RuntimeError, "no leader"),
        ):
            lab.heal("partition")

    def test_heal_fails_while_the_healed_node_is_down(self):
        lab = self._lab()
        lab._faulted = "m2"
        cluster = self._cluster("m1 Leader\n", "m1 Ready\nm2 Down\n")
        with (
            mock.patch.object(shell, "execute", cluster),
            mock.patch.object(shell, "wait_until", _once),
            self.assertRaises(RuntimeError),
        ):
            lab.heal("partition")

    def test_heal_returns_once_a_leader_exists_and_the_node_is_ready(self):
        lab = self._lab()
        lab._faulted = "m2"
        cluster = self._cluster("m1 Leader\n", "m1 Ready\nm2 Ready\n")
        with (
            mock.patch.object(shell, "execute", cluster),
            mock.patch.object(shell, "wait_until", _once),
        ):
            lab.heal("partition")
        self.assertIsNone(lab._faulted)

    def test_every_node_fault_restores_the_resolver_on_heal(self):
        for injection in ("node", "hang", "partition"):
            with self.subTest(injection):
                lab = self._lab()
                cluster = self._cluster("m1 Leader\n", "m1 Ready\nm2 Ready\n")
                with (
                    mock.patch.object(shell, "execute", cluster),
                    mock.patch.object(shell, "wait_until", _once),
                ):
                    lab._fault(injection, "m2")
                    lab.heal(injection)
                restore = [
                    c
                    for c in cluster.call_args_list
                    if c.args[0][-1] == "cat > /etc/resolv.conf"
                ]
                self.assertEqual(len(restore), 1)
                self.assertEqual(restore[0].kwargs["stdin"], "nameserver 10.0.0.53\n")


class TestReadyForCase(unittest.TestCase):
    def _lab(self, inventory) -> SwarmLab:
        return SwarmLab(
            engine="postgres",
            managers=["m1"],
            spare="w1",
            network="lab",
            node_ips={},
            inventory=inventory,
        )

    def test_a_lab_without_inventory_counts_as_ready(self):
        self.assertEqual(self._lab(None).wait_ready_for_case(1)[0], True)

    def test_standalone_form_counts_as_ready(self):
        lab = self._lab(mock.Mock())
        with mock.patch.object(SwarmLab, "form", return_value="standalone"):
            self.assertTrue(lab.wait_ready_for_case(1)[0])

    def test_ha_form_waits_for_full_strength(self):
        lab = self._lab(mock.Mock())
        with (
            mock.patch.object(SwarmLab, "form", return_value="ha"),
            mock.patch.object(
                SwarmLab,
                "wait_full_strength",
                return_value=(False, "m2=Replica/starting"),
            ) as strength,
        ):
            self.assertEqual(
                lab.wait_ready_for_case(30), (False, "m2=Replica/starting")
            )
        strength.assert_called_once_with(30)


class TestWaitFullStrength(unittest.TestCase):
    def _lab(self) -> SwarmLab:
        return SwarmLab(
            engine="mariadb",
            managers=["m1"],
            spare="w1",
            network="lab",
            node_ips={},
        )

    def _wait(self, lab: SwarmLab, fatal: list[str], clock: list[float]):
        def ticking_wait(predicate, *, timeout_s, interval_s):
            while clock[0] < timeout_s:
                if predicate():
                    return True
                clock[0] += interval_s
            return False

        with (
            mock.patch.object(
                SwarmLab, "full_strength", return_value=(False, "replication stopped")
            ),
            mock.patch.object(SwarmLab, "fatal_replicas", return_value=fatal),
            mock.patch(
                "utils.failover.swarm.engine_ops.shell.wait_until",
                side_effect=ticking_wait,
            ),
            mock.patch(
                "utils.failover.swarm.engine_ops.time.monotonic",
                side_effect=lambda: clock[0],
            ),
        ):
            return lab.wait_full_strength(3600)

    def test_a_fatal_replica_ends_the_wait_after_the_grace(self):
        clock = [0.0]
        ok, detail = self._wait(self._lab(), ["mariadb_m2"], clock)
        self.assertFalse(ok)
        self.assertIn("fatal replication error", detail)
        self.assertLess(clock[0], 600)

    def test_a_transient_stop_waits_the_full_timeout(self):
        clock = [0.0]
        ok, detail = self._wait(self._lab(), [], clock)
        self.assertFalse(ok)
        self.assertEqual(detail, "replication stopped")
        self.assertGreaterEqual(clock[0], 3600)


class TestArrangeLeaderColocation(unittest.TestCase):
    def test_waits_out_a_leaderless_moment_instead_of_failing(self):
        lab = SwarmLab(
            engine="postgres",
            managers=["m1", "m2", "m3"],
            spare="w1",
            network="lab",
            node_ips={},
        )
        leaders = iter(["m2", None, "m1"])
        with (
            mock.patch.object(SwarmLab, "wait_swarm_settled") as settled,
            mock.patch.object(
                SwarmLab, "raft_leader", side_effect=lambda: next(leaders, "m1")
            ),
            mock.patch.object(SwarmLab, "restart_node") as restart,
            mock.patch.object(SwarmLab, "_stack_services", return_value=[]),
            mock.patch.object(SwarmLab, "move_primary_to"),
            mock.patch.object(SwarmLab, "wait_full_strength", return_value=(True, "")),
        ):
            lab.arrange_leader_colocation()
        restart.assert_called_once_with("m2")
        self.assertEqual(settled.call_count, 3)


class TestRestartNode(unittest.TestCase):
    def test_a_restart_keeps_the_installed_name_files(self):
        lab = SwarmLab(
            engine="postgres", managers=["m1"], spare="w1", network="lab", node_ips={}
        )
        calls = []
        contents = {
            "/etc/resolv.conf": "nameserver 127.0.0.1\n",
            "/etc/hosts": "192.168.244.10\tm2\n",
        }

        def answer(argv, *, stdin=None, timeout=None):
            calls.append((argv, stdin))
            out = contents.get(argv[-1], "") if argv[-2:-1] == ["cat"] else ""
            return mock.Mock(returncode=0, stdout=out, stderr="")

        with mock.patch.object(shell, "execute", answer):
            lab.restart_node("m2")
        argvs = [c[0] for c in calls]
        restart = argvs.index(["docker", "restart", "m2"])
        for path, content in contents.items():
            with self.subTest(path):
                restore = argvs.index(
                    ["docker", "exec", "-i", "m2", "sh", "-c", f"cat > {path}"]
                )
                self.assertLess(restart, restore)
                self.assertEqual(calls[restore][1], content)


class TestCheckerTaskLost(unittest.TestCase):
    def _lab(self) -> SwarmLab:
        lab = SwarmLab(
            engine="postgres", managers=["m1"], spare="w1", network="lab", node_ips={}
        )
        lab._checker_id = "sid"
        return lab

    def _answer(self, states: str):
        def answer(argv, *, stdin=None, timeout=None):
            out = states if "service" in argv and "ps" in argv else ""
            return mock.Mock(returncode=0, stdout=out, stderr="")

        return answer

    def test_a_vanished_checker_fails_instead_of_waiting(self):
        with (
            mock.patch.object(shell, "execute", self._answer("Failed 2 minutes ago\n")),
            self.assertRaisesRegex(RuntimeError, "ended without a container"),
        ):
            self._lab().checker_log()

    def test_a_rejected_checker_names_the_task_error(self):
        with (
            mock.patch.object(
                shell,
                "execute",
                self._answer("Rejected 1 second ago\tNo such image: x:1\n"),
            ),
            self.assertRaisesRegex(RuntimeError, "No such image: x:1"),
        ):
            self._lab().checker_log()

    def test_a_pending_checker_is_still_awaited(self):
        with mock.patch.object(
            shell, "execute", self._answer("Preparing 1 second ago\n")
        ):
            self.assertEqual(self._lab().checker_log(), "")


class TestSpareLogsByServiceId(unittest.TestCase):
    def test_checker_log_reads_only_the_current_service_containers(self):
        lab = SwarmLab(
            engine="postgres", managers=["m1"], spare="w1", network="lab", node_ips={}
        )
        lab._checker_id = "sid-new"

        def answer(argv, *, stdin=None, timeout=None):
            out = ""
            if "ps" in argv:
                out = "cnew\n" if argv[-1].endswith("service.id=sid-new") else "cold\n"
            elif argv[-1] == "docker logs cnew 2>&1":
                out = "new-log\n"
            elif argv[-1] == "docker logs cold 2>&1":
                out = "old-log\n"
            return mock.Mock(returncode=0, stdout=out, stderr="")

        with mock.patch.object(shell, "execute", answer):
            self.assertEqual(lab.checker_log(), "new-log\n")


class TestFireBackup(unittest.TestCase):
    def test_a_running_backup_is_waited_out_before_the_stamp(self):
        lab = SwarmLab(
            engine="mariadb",
            managers=["m1"],
            spare="w1",
            network="lab",
            node_ips={},
        )
        states = iter(["activating", "inactive"])
        calls: list[list[str]] = []

        def run(argv, **_):
            calls.append(argv)
            if "list-unit-files" in argv:
                return "svc-bkp-volume-2-local.service enabled\n"
            if "is-active" in argv:
                return next(states)
            return ""

        with (
            mock.patch.object(shell, "run", side_effect=run),
            mock.patch.object(
                shell,
                "wait_until",
                side_effect=lambda pred, **_: pred() or pred(),
            ),
        ):
            lab.fire_backup("m1")
        verbs = [argv[3] for argv in calls]
        self.assertEqual(
            verbs, ["systemctl", "systemctl", "systemctl", "touch", "systemctl"]
        )
        self.assertEqual(calls[-1][-2:], ["start", "svc-bkp-volume-2-local.service"])


class TestTopologyCleanup(unittest.TestCase):
    def _lab(self) -> SwarmLab:
        return SwarmLab(
            engine="redis",
            managers=["m1", "m2"],
            spare="w1",
            network="lab",
            node_ips={},
        )

    def test_wipe_engine_tolerates_a_network_still_in_use(self):
        def answer(argv, *, stdin=None, timeout=None):
            if argv[-3:] == ["stack", "rm", "redis"]:
                return mock.Mock(
                    returncode=1, stdout="", stderr="network redis is in use"
                )
            return mock.Mock(returncode=0, stdout="", stderr="")

        with (
            mock.patch.object(shell, "execute", answer),
            mock.patch.object(shell, "wait_until", _once),
        ):
            self._lab().wipe_engine()

    def test_volume_removal_prunes_exited_stack_containers_first(self):
        cluster = mock.Mock(return_value=mock.Mock(returncode=0, stdout="", stderr=""))
        with (
            mock.patch.object(shell, "execute", cluster),
            mock.patch.object(shell, "wait_until", _once),
        ):
            self._lab()._remove_stack_volumes("etcd")
        first = cluster.call_args_list[0].args[0]
        self.assertEqual(first[3:7], ["docker", "container", "prune", "--force"])
        self.assertEqual(first[-1], "label=com.docker.stack.namespace=etcd")

    def test_spare_gets_the_engine_image_copied_when_missing(self):
        lab = self._lab()
        calls = []

        def answer(argv, *, stdin=None, timeout=None):
            calls.append(argv)
            rc = 1 if argv[-3:-1] == ["image", "inspect"] else 0
            return mock.Mock(returncode=rc, stdout="", stderr="")

        with mock.patch.object(shell, "execute", answer):
            lab._seed_spare("reg/redis:8")
        self.assertEqual(calls[-1][:2], ["sh", "-c"])
        self.assertIn("docker save reg/redis:8", calls[-1][2])
        self.assertIn("docker exec -i w1 docker load", calls[-1][2])


class TestNodeListings(unittest.TestCase):
    def test_raft_leader_and_status(self):
        listing = "m1 Reachable\nm2 Leader\nw1\n"
        self.assertEqual(swarm.raft_leader(listing), "m2")
        self.assertIsNone(swarm.raft_leader("m1 Reachable\n"))
        self.assertEqual(swarm.node_status("m1 Ready\nm2 Down\n", "m2"), "Down")
        self.assertIsNone(swarm.node_status("m1 Ready\n", "m9"))

    def test_in_container_argv_keeps_stdin_on_both_hops(self):
        self.assertEqual(
            swarm.in_container_argv(
                "n1", "c1", ["psql"], user="postgres", interactive=True
            ),
            [
                "docker",
                "exec",
                "-i",
                "n1",
                "docker",
                "exec",
                "-i",
                "--user",
                "postgres",
                "c1",
                "psql",
            ],
        )


class TestInstanceServices(unittest.TestCase):
    def test_sentinels_and_the_endpoint_are_no_instances(self):
        self.assertTrue(swarm.is_instance_service("redis", "redis_redis-m1"))
        self.assertFalse(swarm.is_instance_service("redis", "redis_redis-sentinel-m1"))
        self.assertFalse(swarm.is_instance_service("redis", "redis_redis"))
        self.assertFalse(swarm.is_instance_service("redis", "redis_haproxy"))

    def test_primary_probe_runs_the_deployed_probe_on_the_node(self):
        for engine in ("postgres", "mariadb", "redis", "openldap"):
            with self.subTest(engine):
                argv = swarm.primary_probe_argv(
                    engine, node="n1", service=f"{engine}_{engine}-m1"
                )
                self.assertEqual(
                    argv,
                    [
                        "docker",
                        "exec",
                        "n1",
                        f"/usr/bin/primary-probe-{engine}",
                        engine,
                        f"{engine}-m1",
                    ],
                )


class TestCheckerService(unittest.TestCase):
    def test_checker_is_pinned_to_the_spare_worker_and_reads_a_secret(self):
        argv = swarm.checker_service_argv(
            engine="postgres",
            manager="m1",
            spare="w1",
            image="registry/postgres:18",
            network="postgres",
            run_id="r1",
            duration_s=60,
        )
        self.assertEqual(argv[:5], ["docker", "exec", "m1", "docker", "service"])
        self.assertIn("node.hostname==w1", argv)
        self.assertIn(
            f"source={swarm.secret_name('postgres')},target=failover-checker", argv
        )
        self.assertIn("ENGINE=postgres", argv)
        self.assertIn("RUN_ID=r1", argv)
        self.assertIn("DURATION_S=60", argv)
        self.assertIn("INTERVAL_S=0.2", argv)
        self.assertIn("TIMEOUT_S=1", argv)
        self.assertEqual(argv[-2:], ["registry/postgres:18", swarm.CHECKER_PATH])
        self.assertEqual(argv[argv.index("--entrypoint") + 1], "sh")

    def test_probe_service_shares_the_secret_and_placement(self):
        argv = swarm.oneshot_service_argv(
            name="failover-probe-redis",
            manager="m1",
            spare="w1",
            image="redis:8",
            network="redis",
            engine="redis",
            config="cfg",
            script_path=swarm.PROBE_PATH,
            env={"MODE": "idle", "ARG": "960"},
        )
        self.assertIn("node.hostname==w1", argv)
        self.assertIn(
            f"source={swarm.secret_name('redis')},target=failover-checker", argv
        )
        self.assertIn("MODE=idle", argv)
        self.assertEqual(argv[-2:], ["redis:8", swarm.PROBE_PATH])
        self.assertEqual(argv[argv.index("--entrypoint") + 1], "sh")

    def test_declared_volumes_become_tmpfs_mounts(self):
        argv = swarm.checker_service_argv(
            engine="postgres",
            manager="m1",
            spare="w1",
            image="registry/postgres:18",
            network="postgres",
            run_id="r1",
            duration_s=60,
            scratch_dirs=["/var/lib/postgresql/data"],
        )
        mount = argv.index("type=tmpfs,destination=/var/lib/postgresql/data")
        self.assertEqual(argv[mount - 1], "--mount")
        self.assertLess(mount, argv.index("registry/postgres:18"))

    def test_checker_script_ends_early_on_usr1(self):
        self.assertIn("trap 'deadline=0' USR1", read_text(str(swarm.CHECKER_SCRIPT)))


class TestLabOverrides(unittest.TestCase):
    def test_entries_for_absent_roles_and_undeclared_services_are_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            roles = Path(td)
            services_file = roles / "svc-db-postgres" / ROLE_FILE_META_SERVICES
            services_file.parent.mkdir(parents=True)
            services_file.write_text("postgres:\n  image: postgres\n")
            raw = {
                "applications": {
                    "svc-db-postgres": {
                        "services": {
                            "postgres": {"mem_limit": "768m"},
                            "haproxy": {"mem_limit": "64m"},
                        }
                    },
                    "svc-dcs-etcd": {"services": {"etcd": {"mem_limit": "256m"}}},
                }
            }
            out = swarm.filter_lab_overrides(raw, roles_dir=roles)
        self.assertEqual(
            out,
            {
                "applications": {
                    "svc-db-postgres": {"services": {"postgres": {"mem_limit": "768m"}}}
                }
            },
        )

    def test_shipped_lab_sizes_match_the_documented_limits(self):
        sizes = swarm.load_lab_sizes()["applications"]
        expect = {
            ("svc-db-postgres", "postgres"): "768m",
            ("svc-db-mariadb", "mariadb"): "512m",
            ("svc-db-openldap", "openldap"): "256m",
            ("svc-db-redis", "redis"): "128m",
            ("svc-dcs-etcd", "etcd"): "256m",
            ("svc-db-postgres", "haproxy"): "64m",
        }
        for (app, svc), limit in expect.items():
            self.assertEqual(
                sizes[app]["services"][svc]["mem_limit"], limit, (app, svc)
            )


class TestStartReplicaSql(unittest.TestCase):
    def _lab(self) -> SwarmLab:
        return SwarmLab(
            engine="mariadb", managers=["m1"], spare="w1", network="lab", node_ips={}
        )

    def test_returns_once_the_sql_thread_runs(self):
        lab = self._lab()
        with (
            mock.patch.object(lab, "_in", side_effect=self._answers(["No", "Yes"])),
            mock.patch.object(shell.time, "sleep"),
        ):
            lab.start_replica_sql("mariadb_m2", timeout_s=30)

    def test_raises_when_the_sql_thread_stays_stopped(self):
        lab = self._lab()
        with (
            mock.patch.object(lab, "_in", side_effect=self._answers(["No"] * 50)),
            mock.patch.object(shell.time, "sleep"),
            mock.patch.object(shell.time, "monotonic", side_effect=[0, 0, 60]),
            self.assertRaisesRegex(RuntimeError, "left the SQL thread stopped"),
        ):
            lab.start_replica_sql("mariadb_m2", timeout_s=30)

    @staticmethod
    def _answers(states: list[str]):
        """Alternate START SLAVE replies and SHOW SLAVE STATUS replies."""
        replies = []
        for state in states:
            replies.append(mock.Mock(returncode=0, stdout="", stderr=""))
            replies.append(
                mock.Mock(
                    returncode=0, stdout=f"Slave_SQL_Running: {state}\n", stderr=""
                )
            )
        return replies


if __name__ == "__main__":
    unittest.main()
