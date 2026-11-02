"""Topology changes of the Swarm lab adapter: leaders, redeploys, forget, wipes."""

from __future__ import annotations

import os

from utils.failover import engines
from utils.failover.inventory import (
    deploy_argv,
    forget_argv,
    playbook_argv,
    replace_host,
    set_group_hosts,
)
from utils.failover.swarm import shell
from utils.failover.swarm.commands import (
    ARRANGE_ATTEMPTS,
    COORDINATION_ROLE,
    DEPLOY_TIMEOUT_S,
    RAFT_ARRANGE_ATTEMPTS,
    SETTLE_TIMEOUT_S,
    sentinel_failover_argv,
)
from utils.failover.targets import RECLONE_CEILING_S
from utils.roles.db.instances import instance_service
from utils.roles.entity.name import get_entity_name

REDIS_PREFERRED_PRIORITY = "1"
REDIS_DEFAULT_PRIORITY = "100"
NETWORK_SETTLE_S = 30


class Topology:
    """Mixin of ``SwarmLabBase``: Raft and etcd leaders, inventory edits and redeploys."""

    def _etcd_member_on(self, host: str) -> str:
        etcd_stack = get_entity_name(COORDINATION_ROLE)
        for service in self._stack_services(etcd_stack):
            location = self._locate(service)
            if location and location[0] == host:
                return service
        raise RuntimeError(f"no etcd member runs on {host}")

    def _playbook(self, playbook: str, params: dict, limit: str) -> None:
        rc = shell.stream(
            playbook_argv(self._inventory(), playbook, {"failover": params}, limit),
            env=os.environ.copy(),
            timeout=900,
        )
        if rc != 0:
            raise RuntimeError(f"{playbook} {params.get('op', '')} failed rc={rc}")

    def move_etcd_leader(self, host: str) -> None:
        service = self._etcd_member_on(host)
        etcd_stack = get_entity_name(COORDINATION_ROLE)
        self._playbook(
            "etcd-operation.yml",
            {
                "op": "move-leader",
                "etcd_service": service,
                "etcd_member": service[len(etcd_stack) + 1 :],
            },
            limit=host,
        )

    def delete_engine_keys(self) -> None:
        host = next(m for m in self.managers if m not in self._dead)
        self._playbook(
            "etcd-operation.yml",
            {
                "op": "delete-prefix",
                "etcd_service": self._etcd_member_on(host),
                "engine_role": self.role,
            },
            limit=host,
        )

    def _instance_on(self, host: str) -> str:
        for service in self._instances():
            location = self._locate(service)
            if location and location[0] == host:
                return service
        raise RuntimeError(f"no {self.engine} instance runs on {host}")

    def _hand_over(self, primary: str, target: str) -> None:
        if self.engine == "postgres":
            user, argv = engines.patroni_switchover(
                self.stack,
                engines.member_of(self.engine, primary),
                engines.member_of(self.engine, target),
            )
            proc = self._in(primary, argv, user=user, timeout=120)
            if proc.returncode != 0:
                raise RuntimeError(f"patronictl switchover: {proc.stderr.strip()}")
        elif self.engine == "redis":
            member = engines.member_of(self.engine, target)
            sidecar = instance_service(
                engines.role_of(self.engine),
                {"service": member, "host_id": member.split("-", 1)[1]},
                "sentinel",
            )
            sentinel = f"{self.stack}_{sidecar}"
            self._set_replica_priorities(primary, target)
            self._in(sentinel, sentinel_failover_argv())
        else:
            node, cid = self._locate(primary) or (None, None)
            if node is None:
                raise RuntimeError(f"{primary} has no running container")
            shell.run(
                ["docker", "exec", node, "docker", "stop", "-t", "60", cid], timeout=180
            )
        self.wait_new_primary(primary)

    def _set_replica_priorities(self, primary: str | None, target: str | None) -> None:
        """Sentinel promotes the replica with the lowest priority, else any.

        Args:
            primary: current master, left untouched; ``None`` touches every instance.
            target: replica to prefer, ``None`` to restore the default.
        """
        for service in self._instances():
            if service == primary:
                continue
            priority = (
                REDIS_PREFERRED_PRIORITY
                if service == target
                else REDIS_DEFAULT_PRIORITY
            )
            self._in(
                service,
                engines.redis_cli("CONFIG", "SET", "replica-priority", priority),
            )

    def move_primary_to(self, host: str) -> None:
        target = self._instance_on(host)
        for _ in range(ARRANGE_ATTEMPTS):
            if not self.wait_primary():
                raise RuntimeError(f"no {self.engine} primary while arranging")
            primary = self.primary_instance()
            if primary == target:
                if self.engine == "redis":
                    self._set_replica_priorities(None, None)
                return
            self._hand_over(primary, target)
        raise RuntimeError(
            f"primary did not land on {host} in {ARRANGE_ATTEMPTS} handovers"
        )

    def arrange_leader_colocation(self) -> None:
        """Put the Raft leader, the etcd leader (when etcd runs) and the primary on ``STACK_HOST``."""
        stack_host = self.managers[0]
        for _ in range(RAFT_ARRANGE_ATTEMPTS):
            self.wait_swarm_settled(self.live_managers())
            leader = self.raft_leader()
            if leader == stack_host:
                break
            if leader is not None:
                self.restart_node(leader)
        else:
            raise RuntimeError(f"Raft leadership did not land on {stack_host}")
        ok, detail = self.wait_full_strength(RECLONE_CEILING_S)
        if not ok:
            raise RuntimeError(
                f"not at full strength after moving the Raft leader: {detail}"
            )
        if self._stack_services(get_entity_name(COORDINATION_ROLE)):
            self.move_etcd_leader(stack_host)
        self.move_primary_to(stack_host)
        ok, detail = self.wait_full_strength(RECLONE_CEILING_S)
        if not ok:
            raise RuntimeError(
                f"replicas did not follow the arranged primary: {detail}"
            )
        if self.raft_leader() != stack_host:
            raise RuntimeError("Raft leadership moved away while arranging the primary")

    def _deploy_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["APP_ID"] = self.role
        env["ANSIBLE_VAULT_PASSWORD_FILE"] = str(self._inventory().password)
        return env

    def redeploy(self) -> int:
        inventory = self._inventory()
        inventory.write_suite_extras(self.role)
        return shell.stream(
            deploy_argv(inventory, self.python),
            env=self._deploy_env(),
            timeout=DEPLOY_TIMEOUT_S,
        )

    def set_engine_hosts(self, hosts: list[str]) -> None:
        inventory = self._inventory()
        inventory.save(set_group_hosts(inventory.load(), self.role, hosts))

    def live_managers(self) -> list[str]:
        return [m for m in self.managers if m not in self._dead]

    def forget_and_replace(self, victim: str) -> int:
        """Swap ``victim`` for the spare in the inventory, then forget it and redeploy."""
        inventory = self._inventory()
        inventory.save(replace_host(inventory.load(), victim, self.spare))
        inventory.write_suite_extras(self.role)
        self._dead.add(victim)
        self.managers = [self.spare if m == victim else m for m in self.managers]
        if self._faulted == victim:
            self._faulted = None
        return shell.stream(
            forget_argv(inventory, victim),
            env=self._deploy_env(),
            timeout=DEPLOY_TIMEOUT_S,
        )

    def bump_engine_memory(self, delta_mb: int) -> int:
        return self._inventory().bump_memory(
            app_id=self.role, service=self.engine, delta_mb=delta_mb
        )

    def _remove_stack_volumes(self, stack: str) -> None:
        for node in self.live_managers():

            def removed(node: str = node) -> bool:
                shell.run(
                    [
                        "docker",
                        "exec",
                        node,
                        "docker",
                        "container",
                        "prune",
                        "--force",
                        "--filter",
                        f"label=com.docker.stack.namespace={stack}",
                    ],
                    check=False,
                )
                names = shell.run(
                    [
                        "docker",
                        "exec",
                        node,
                        "docker",
                        "volume",
                        "ls",
                        "-q",
                        "--filter",
                        f"label=com.docker.stack.namespace={stack}",
                    ],
                    check=False,
                ).split()
                for name in names:
                    shell.run(
                        ["docker", "exec", node, "docker", "volume", "rm", name],
                        check=False,
                    )
                return not names

            if not shell.wait_until(removed, timeout_s=SETTLE_TIMEOUT_S):
                raise RuntimeError(f"volumes of {stack} stayed on {node}")

    def wipe_etcd(self) -> None:
        etcd_stack = get_entity_name(COORDINATION_ROLE)
        members = self._stack_services(etcd_stack)
        if not members:
            raise RuntimeError("no etcd member service to wipe")
        for service in members:
            self.scale(service, 0)
        for service in members:
            if not self.wait_running(service, False):
                raise RuntimeError(f"{service} kept running after scale 0")
        self._remove_stack_volumes(etcd_stack)

    def wipe_engine(self) -> None:
        """Remove the engine stack and its volumes.

        Its networks get only a short wait: a network another stack still uses
        stays, so demanding that every one goes would wait for nothing.
        """
        self._on_manager("docker", "stack", "rm", self.stack, check=False)
        if not shell.wait_until(
            lambda: not self._stack_services(self.stack), timeout_s=SETTLE_TIMEOUT_S
        ):
            raise RuntimeError(f"stack {self.stack} did not go away")
        shell.wait_until(
            lambda: (
                not self._on_manager(
                    "docker",
                    "network",
                    "ls",
                    "-q",
                    "--filter",
                    f"label=com.docker.stack.namespace={self.stack}",
                    check=False,
                ).split()
            ),
            timeout_s=NETWORK_SETTLE_S,
        )
        self._remove_stack_volumes(self.stack)
        if self.engine != "redis":
            self.delete_engine_keys()
