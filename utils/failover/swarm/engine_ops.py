"""Engine-level queries and writes of the Swarm lab adapter."""

from __future__ import annotations

import shlex
import time

from utils.failover import engines
from utils.failover.inventory import (
    group_hosts,
)
from utils.failover.swarm import shell
from utils.failover.swarm.commands import (
    SETTLE_TIMEOUT_S,
    node_status,
    raft_leader,
)

CSN_SLACK_S = 5.0
FATAL_GRACE_S = 300.0


class EngineOps:
    """Mixin of ``SwarmLabBase``: direct instance writes, LDAP views and strength."""

    def local_write(self, service: str, key: str) -> tuple[bool, str]:
        """Write straight into one instance, bypassing the endpoint.

        Returns ``(accepted, output)``; Redis sets a key, OpenLDAP adds an entry.
        """
        if self.engine == "redis":
            proc = self._in(
                service,
                engines.redis_cli("SET", f"failover:local:{key}", "1"),
                timeout=10,
            )
            return engines.redis_write_accepted(proc.stdout), proc.stdout.strip()
        if self.engine == "openldap":
            suffix = self.ldap_suffix(service)
            argv, stdin = engines.ldap_add_entry(
                f"cn=local-{key},ou=failover-check,{suffix}"
            )
            proc = self._in(service, argv, stdin=stdin, timeout=10)
            output = f"{proc.stdout}{proc.stderr}".strip()
            return proc.returncode == 0, f"rc={proc.returncode} {output}"
        raise ValueError(f"local_write: {self.engine} is written through SQL")

    def ldap_unwilling(self, service: str, key: str) -> tuple[bool, str]:
        suffix = self.ldap_suffix(service)
        argv, stdin = engines.ldap_add_entry(
            f"cn=demoted-{key},ou=failover-check,{suffix}"
        )
        proc = self._in(service, argv, stdin=stdin, timeout=10)
        output = f"{proc.stdout}{proc.stderr}".strip()
        return engines.ldap_unwilling(
            proc.returncode, output
        ), f"rc={proc.returncode} {output}"

    def ldap_suffix(self, service: str) -> str:
        proc = self._in(service, engines.ldap_suffix())
        values = engines.ldap_values(proc.stdout, "olcSuffix")
        if not values:
            raise RuntimeError(f"{service}: no olcSuffix on its data database")
        return values[0]

    def memberof_views(self) -> dict[str, list[str]]:
        views: dict[str, list[str]] = {}
        for service in self._instances():
            suffix = self.ldap_suffix(service)
            proc = self._in(
                service,
                engines.ldapi(
                    "ldapsearch", "-LLL", "-b", suffix, "(memberOf=*)", "memberOf"
                ),
            )
            views[service] = sorted(engines.ldap_values(proc.stdout, "memberOf"))
        return views

    def engine_hosts(self) -> list[str]:
        return group_hosts(self._inventory().load(), self.role)

    def full_strength(self) -> tuple[bool, str]:
        """Return whether every listed instance runs and replicates, with detail."""
        expected = len(self.engine_hosts())
        services = self._instances()
        if len(services) != expected or not all(self.running(s) for s in services):
            return False, f"{len(services)} of {expected} instances running"
        primary = self.primary_instance()
        if self.engine == "postgres":
            user, argv = engines.patroni_list()
            proc = self._in(primary, argv, user=user)
            return engines.patroni_strength(proc.stdout, expected)
        if self.engine == "redis":
            proc = self._in(primary, engines.redis_cli("INFO", "replication"))
            slaves = engines.redis_connected_slaves(proc.stdout)
            return slaves == expected - 1, f"master {primary} has {slaves} replicas"
        if self.engine == "mariadb":
            lagging = []
            for service in services:
                if service == primary:
                    continue
                proc = self._in(service, engines.slave_status())
                status = engines.parse_slave_status(proc.stdout)
                if not engines.replica_running(status):
                    reason = (
                        status.get("Last_IO_Error")
                        or status.get("Last_SQL_Error")
                        or ""
                    )
                    lagging.append(f"{service}: {reason[:160]}" if reason else service)
            return (
                not lagging,
                f"replication stopped on {lagging}" if lagging else "all replicating",
            )
        csns = {}
        for service in services:
            suffix = self.ldap_suffix(service)
            proc = self._in(
                service,
                engines.ldapi(
                    "ldapsearch", "-LLL", "-s", "base", "-b", suffix, "contextCSN"
                ),
            )
            csns[service] = tuple(
                sorted(engines.ldap_values(proc.stdout, "contextCSN"))
            )
        if engines.csns_converged(csns, CSN_SLACK_S):
            return True, f"contextCSN per instance: {csns}"
        return (
            False,
            f"contextCSN per instance: {csns}; syncrepl: {self._syncrepl_log()}",
        )

    def _syncrepl_log(self) -> dict[str, list[str]]:
        tails: dict[str, list[str]] = {}
        for service in self._instances():
            try:
                out = self._on_manager(
                    "sh",
                    "-c",
                    f"docker service logs --raw --tail 400 {shlex.quote(service)} 2>&1",
                )
            except RuntimeError as error:
                tails[service] = [str(error)[:160]]
                continue
            lines = [
                line.strip()[:200]
                for line in out.splitlines()
                if "syncrep" in line or "rid=" in line
            ]
            tails[service] = [self._root_pw_digest(service), *lines[-6:]]
        return tails

    def elector_log(self, service: str, lines: int = 12) -> list[str]:
        """Return the last elector lines (INFO/WARNING/ERROR) of one instance.

        Args:
            service: the instance's Swarm service.
            lines: how many matching lines to keep.
        """
        try:
            out = self._on_manager(
                "sh",
                "-c",
                f"docker service logs --raw --tail 600 {shlex.quote(service)} 2>&1",
            )
        except RuntimeError as error:
            return [str(error)[:160]]
        picked = [
            line.strip()[:240]
            for line in out.splitlines()
            if any(level in line for level in (" INFO ", " WARNING ", " ERROR "))
        ]
        return picked[-lines:]

    def _root_pw_digest(self, service: str) -> str:
        """A 12-hex digest prefix of the instance's root password and its age.

        The password is hashed inside the container so it never reaches the log.
        """
        try:
            proc = self._in(
                service,
                [
                    "sh",
                    "-c",
                    (
                        'printf %s "$LDAP_ROOT_PW" | sha256sum | cut -c1-12; '
                        "echo $(( $(date +%s) - $(stat -c %Y /proc/1) ))"
                    ),
                ],
                timeout=15,
            )
        except RuntimeError as error:
            return f"pw=? ({str(error)[:80]})"
        digest, _, age = proc.stdout.strip().partition("\n")
        return f"pw={digest} age={age}s"

    def fatal_replicas(self) -> list[str]:
        """Return the MariaDB replicas whose IO thread stopped on an error no reconnect clears."""
        if self.engine != "mariadb":
            return []
        primary = self.primary_instance()
        return [
            service
            for service in self._instances()
            if service != primary
            and engines.replica_fatal(
                engines.parse_slave_status(
                    self._in(service, engines.slave_status()).stdout
                )
            )
        ]

    def wait_full_strength(self, timeout_s: float) -> tuple[bool, str]:
        """Wait until ``full_strength`` holds, or give up early on a fatal replica.

        A replica that stays stopped on a fatal error for ``FATAL_GRACE_S``
        ends the wait, since waiting out the full timeout cannot heal it.
        """
        detail: list[str] = []
        fatal_since: dict[str, float] = {}

        def settled() -> bool:
            ok, text = self.full_strength()
            detail.append(text)
            if ok:
                fatal_since.clear()
                return True
            if not self.fatal_replicas():
                fatal_since.clear()
                return False
            started = fatal_since.setdefault("at", time.monotonic())
            return time.monotonic() - started >= FATAL_GRACE_S

        ok = shell.wait_until(settled, timeout_s=timeout_s, interval_s=15)
        last = detail[-1] if detail else "never checked"
        if ok and fatal_since:
            return False, f"fatal replication error for {FATAL_GRACE_S:.0f}s: {last}"
        return ok, last

    def wait_ready_for_case(self, timeout_s: float) -> tuple[bool, str]:
        """Wait for full strength when the engine runs in HA form.

        A standalone engine, or a lab without its inventory, counts as ready.
        """
        if self.inventory is None or self.form() != "ha":
            return True, "no HA form to check"
        return self.wait_full_strength(timeout_s)

    def _node_listing(self, fmt: str) -> str:
        return self._on_manager("docker", "node", "ls", "--format", fmt)

    def raft_leader(self) -> str | None:
        return raft_leader(self._node_listing("{{.Hostname}} {{.ManagerStatus}}"))

    def wait_node_status(
        self, node: str, status: str, timeout_s: float = SETTLE_TIMEOUT_S
    ) -> bool:
        return shell.wait_until(
            lambda: (
                node_status(self._node_listing("{{.Hostname}} {{.Status}}"), node)
                == status
            ),
            timeout_s=timeout_s,
        )

    def form(self) -> str:
        """Return ``ha`` when instance services exist, ``standalone`` otherwise."""
        try:
            self._instances()
        except RuntimeError:
            return "standalone"
        return "ha"

    def endpoint_mode(self) -> str:
        return self._on_manager(
            "docker",
            "service",
            "inspect",
            f"{self.stack}_{self.stack}",
            "--format",
            "{{.Spec.EndpointSpec.Mode}}",
        ).strip()
