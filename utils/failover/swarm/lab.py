"""Core of the Swarm lab adapter: instances, primary and faults."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from utils.failover import engines
from utils.failover.sampling import Round, epoch_ms
from utils.failover.swarm import shell
from utils.failover.swarm.commands import (
    NAME_FILES,
    QUORUM_TIMEOUT_S,
    SETTLE_TIMEOUT_S,
    heal_argv,
    in_container_argv,
    inject_argv,
    is_instance_service,
    node_status,
    primary_probe_argv,
    raft_leader,
)

if TYPE_CHECKING:
    from utils.failover.inventory import LabInventory

LOCATE_TIMEOUT_S = 30.0


class SwarmLabBase:
    """Lab adapter driving the DinD Swarm lab from the lab host.

    Args:
        engine: engine under test.
        managers: DinD containers of the managers, stack host first.
        spare: DinD container (and hostname) of the spare worker.
        network: lab network name.
        node_ips: fixed lab address per node container.
        inventory: the provisioned lab inventory; required by the cases
            that redeploy.
        python: interpreter the deploy and forget commands run with.
    """

    def __init__(
        self,
        *,
        engine: str,
        managers: list[str],
        spare: str,
        network: str,
        node_ips: dict[str, str],
        inventory: LabInventory | None = None,
        python: str = "python3",
    ):
        self.engine = engine
        self.managers = list(managers)
        self.spare = spare
        self.client_node = spare
        self.network = network
        self.node_ips = node_ips
        self.inventory = inventory
        self.python = python
        self.stack = engines.stack_of(engine)
        self.role = engines.role_of(engine)
        self._faulted: str | None = None
        self._faulted_at: dict[str, tuple[str, str]] = {}
        self._dead: set[str] = set()
        self._resolv: dict[str, str] = {}
        self._checker_id = ""

    def _manager(self) -> str:
        return next(
            m for m in self.managers if m != self._faulted and m not in self._dead
        )

    def _on_manager(
        self,
        *argv: str,
        stdin: str | None = None,
        check: bool = True,
        timeout: int = 120,
    ) -> str:
        return shell.run(
            ["docker", "exec", "-i", self._manager(), *argv],
            stdin=stdin,
            check=check,
            timeout=timeout,
        )

    def _inventory(self) -> LabInventory:
        if self.inventory is None:
            raise RuntimeError(
                "this case needs the lab inventory (INFINITO_INVENTORY_DIR)"
            )
        return self.inventory

    def _instances(self) -> list[str]:
        names = self._on_manager(
            "docker", "service", "ls", "--format", "{{.Name}}"
        ).split()
        instances = sorted(n for n in names if is_instance_service(self.engine, n))
        if not instances:
            raise RuntimeError(f"no HA instance service of {self.engine}")
        return instances

    def instances(self) -> list[str]:
        return self._instances()

    def _stack_services(self, stack: str) -> list[str]:
        return self._on_manager(
            "docker",
            "service",
            "ls",
            "--filter",
            f"label=com.docker.stack.namespace={stack}",
            "--format",
            "{{.Name}}",
        ).split()

    def _engine_image(self) -> str:
        return self._on_manager(
            "docker",
            "service",
            "inspect",
            self._instances()[0],
            "--format",
            "{{.Spec.TaskTemplate.ContainerSpec.Image}}",
        ).strip()

    def _endpoint_image(self) -> str:
        return self._on_manager(
            "docker",
            "service",
            "inspect",
            f"{self.stack}_{self.stack}",
            "--format",
            "{{.Spec.TaskTemplate.ContainerSpec.Image}}",
        ).strip()

    def _locate(self, service: str) -> tuple[str, str] | None:
        nodes = self._on_manager(
            "docker",
            "service",
            "ps",
            service,
            "--filter",
            "desired-state=running",
            "--format",
            "{{.Node}}",
            check=False,
        ).split()
        if not nodes:
            return None
        cids = shell.run(
            [
                "docker",
                "exec",
                nodes[0],
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label=com.docker.swarm.service.name={service}",
            ],
            check=False,
        ).split()
        return (nodes[0], cids[0]) if cids else None

    def _in(
        self,
        service: str,
        argv: list[str],
        *,
        user: str | None = None,
        stdin: str | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess:
        location = self._locate(service) or self._faulted_at.get(service)
        if location is None:
            raise RuntimeError(f"{service} has no running container")
        node, cid = location
        return shell.execute(
            in_container_argv(
                node, cid, argv, user=user, interactive=stdin is not None
            ),
            stdin=stdin,
            timeout=timeout,
        )

    def is_writer(self, service: str) -> bool | None:
        location = self._locate(service)
        if location is None:
            return None
        node, _cid = location
        return (
            shell.execute(
                primary_probe_argv(self.engine, node=node, service=service)
            ).returncode
            == 0
        )

    def _primary(self) -> tuple[str, str]:
        for service in self._instances():
            location = self._locate(service)
            if location is None:
                continue
            node, cid = location
            probe = primary_probe_argv(self.engine, node=node, service=service)
            if shell.execute(probe).returncode == 0:
                return node, cid
        raise RuntimeError(f"no {self.engine} instance reports itself primary")

    def primary_instance(self) -> str:
        for service in self._instances():
            if self.is_writer(service):
                return service
        raise RuntimeError(f"no {self.engine} instance reports itself primary")

    def _locate_settled(self, service: str) -> tuple[str, str]:
        """Locate ``service``, waiting out a task replacement before a fault."""
        found: list[tuple[str, str]] = []

        def located() -> bool:
            location = self._locate(service)
            if location is not None:
                found.append(location)
            return location is not None

        if not shell.wait_until(located, timeout_s=LOCATE_TIMEOUT_S, interval_s=2):
            raise RuntimeError(f"{service} has no running container")
        return found[-1]

    def node_of(self, service: str) -> str:
        return self._locate_settled(service)[0]

    def gtid(self, service: str) -> str | None:
        user, argv = engines.sql("mariadb", "SELECT @@GLOBAL.gtid_current_pos")
        try:
            proc = self._in(service, argv, user=user, timeout=10)
        except (RuntimeError, subprocess.TimeoutExpired):
            return None
        return proc.stdout.strip() if proc.returncode == 0 else None

    def writer_round(self) -> Round:
        at_ms = epoch_ms()
        services = self._instances()
        writers: dict[str, bool | None] = {}
        gtids: dict[str, str | None] = {}
        for service in services:
            try:
                writers[service] = self.is_writer(service)
            except subprocess.TimeoutExpired:
                writers[service] = None
            if self.engine == "mariadb":
                gtids[service] = self.gtid(service)
        return Round(at_ms=at_ms, writers=writers, gtids=gtids)

    def prepare(self, injection: str) -> None:
        if injection == "leader":
            self.arrange_leader_colocation()

    def inject(self, injection: str) -> None:
        if injection == "leader":
            self._fault("node", self.managers[0])
            return
        node, container = self._primary()
        self._fault(injection, node, container)

    def _fault(self, injection: str, node: str, container: str | None = None) -> None:
        if injection != "kill":
            self._faulted = node
            self._resolv = self._read_name_files(node)
        shell.run(
            inject_argv(injection, node=node, network=self.network, container=container)
        )

    def inject_at(self, injection: str, service: str) -> str:
        """Inject a fault on one instance, or on the node it runs on; return the node."""
        node, cid = self._locate_settled(service)
        self._faulted_at = {service: (node, cid)}
        self._fault(injection, node, cid)
        return node

    def crash_node(self, node: str) -> None:
        self._fault("node", node)

    def _read_name_files(self, node: str) -> dict[str, str]:
        """Snapshot the name-resolution files a node container restart regenerates.

        ``docker start`` and ``docker network connect`` rewrite them: the
        resolver the deploy installed is dropped, and the node's own name
        resolves to its first network's address, where the deploy registry
        would then bind.
        """
        return {
            path: shell.run(["docker", "exec", node, "cat", path], check=False)
            for path in NAME_FILES
        }

    def _write_name_files(self, node: str, files: dict[str, str]) -> None:
        for path, content in files.items():
            if content:
                shell.run(
                    ["docker", "exec", "-i", node, "sh", "-c", f"cat > {path}"],
                    stdin=content,
                )

    def restart_node(self, node: str) -> None:
        """Restart a node container and keep the name files the deploy installed."""
        files = self._read_name_files(node)
        shell.run(["docker", "restart", node], timeout=300)
        self._write_name_files(node, files)

    def heal(self, injection: str) -> None:
        node = self._faulted
        if node is None:
            return
        argv = heal_argv(
            injection, node=node, network=self.network, ip=self.node_ips.get(node)
        )
        if argv:
            shell.run(argv)
        self._write_name_files(node, self._resolv)
        self._resolv = {}
        self._faulted = None
        self._faulted_at = {}
        self.wait_swarm_settled([node])

    def wait_swarm_settled(
        self, nodes: list[str], timeout_s: float = QUORUM_TIMEOUT_S
    ) -> None:
        """Wait until the swarm has a Raft leader and every one of ``nodes`` is ``Ready``.

        A healed partition can leave the swarm leaderless for minutes, and every
        later case fails on "swarm does not have a leader" until it re-elects.
        """

        def settled() -> bool:
            leaders = self._on_manager(
                "docker", "node", "ls", "--format", "{{.Hostname}} {{.ManagerStatus}}"
            )
            statuses = self._on_manager(
                "docker", "node", "ls", "--format", "{{.Hostname}} {{.Status}}"
            )
            return raft_leader(leaders) is not None and all(
                node_status(statuses, node) == "Ready" for node in nodes
            )

        if not shell.wait_until(settled, timeout_s=timeout_s, interval_s=5):
            raise RuntimeError(
                f"swarm had no leader or one of {nodes} was not Ready after {timeout_s:.0f}s"
            )

    def stop_replica_sql(self, service: str) -> None:
        user, argv = engines.sql("mariadb", "STOP SLAVE SQL_THREAD")
        proc = self._in(service, argv, user=user)
        if proc.returncode != 0:
            raise RuntimeError(
                f"STOP SLAVE SQL_THREAD on {service}: {proc.stderr.strip()}"
            )

    def start_replica_sql(
        self, service: str, timeout_s: float = SETTLE_TIMEOUT_S
    ) -> None:
        """Restart the SQL thread stop_replica_sql halted and wait until it runs.

        A silent miss leaves the replica stopped, and every later case then
        waits out its full-strength deadline instead of failing here.
        """
        user, argv = engines.sql("mariadb", "START SLAVE SQL_THREAD")
        last_error = ""

        def sql_running() -> bool:
            nonlocal last_error
            proc = self._in(service, argv, user=user)
            last_error = proc.stderr.strip()
            status = engines.parse_slave_status(
                self._in(service, engines.slave_status()).stdout
            )
            return status.get("Slave_SQL_Running") == "Yes"

        if not shell.wait_until(sql_running, timeout_s=timeout_s, interval_s=5):
            raise RuntimeError(
                f"START SLAVE SQL_THREAD on {service} left the SQL thread stopped "
                f"after {timeout_s:.0f}s: {last_error}"
            )

    def scale(self, service: str, replicas: int) -> None:
        self._on_manager(
            "docker", "service", "scale", "--detach", f"{service}={replicas}"
        )

    def running(self, service: str) -> bool:
        return self._locate(service) is not None

    def wait_running(
        self, service: str, running: bool, timeout_s: float = SETTLE_TIMEOUT_S
    ) -> bool:
        return shell.wait_until(
            lambda: self.running(service) == running, timeout_s=timeout_s
        )

    def wait_new_primary(
        self, old: str, timeout_s: float = SETTLE_TIMEOUT_S
    ) -> str | None:
        found: list[str] = []

        def moved() -> bool:
            current = self.primary_instance()
            if current != old:
                found.append(current)
                return True
            return False

        return found[-1] if shell.wait_until(moved, timeout_s=timeout_s) else None

    def wait_primary(self, timeout_s: float = SETTLE_TIMEOUT_S) -> bool:
        return shell.wait_until(
            lambda: bool(self.primary_instance()), timeout_s=timeout_s
        )
