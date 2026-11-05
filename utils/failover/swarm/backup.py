"""Backup and restore steps of the Swarm lab adapter."""

from __future__ import annotations

import secrets

from utils.failover import engines
from utils.failover.swarm import shell
from utils.failover.swarm.commands import (
    BACKUP_ROLE,
    BACKUP_TIMEOUT_S,
    MARKER_DATABASE,
    SETTLE_TIMEOUT_S,
    backup_repo_name,
    backup_search_root,
)

BUSY_UNIT_STATES = ("active", "activating", "reloading", "deactivating")


class Backup:
    """Mixin of ``SwarmLabBase``: baudolo runs and scratch restores."""

    def seed_backup(self) -> None:
        self._playbook(
            "backup-seed.yml",
            {
                "engine": self.engine,
                "backup_instance": self.stack,
                "backup_database": MARKER_DATABASE[self.engine],
            },
            limit=self.role,
        )

    def fire_backup(self, node: str) -> str:
        """Run the backup unit on ``node``; return the stamp file newer dumps beat.

        A run already in progress, from the unit's own timer, is waited out
        first: ``systemctl start`` would join it instead of starting a new run,
        and its dump may predate the marker while its files still beat the stamp.
        """
        units = shell.run(
            [
                "docker",
                "exec",
                node,
                "systemctl",
                "list-unit-files",
                f"{BACKUP_ROLE}*.service",
                "--no-legend",
            ],
            check=False,
        ).split("\n")
        names = [line.split()[0] for line in units if line.strip()]
        if not names:
            raise RuntimeError(f"no {BACKUP_ROLE} unit installed on {node}")

        def idle() -> bool:
            states = shell.run(
                ["docker", "exec", node, "systemctl", "is-active", *names],
                check=False,
            ).split()
            return not any(state in BUSY_UNIT_STATES for state in states)

        if not shell.wait_until(idle, timeout_s=BACKUP_TIMEOUT_S, interval_s=5):
            raise RuntimeError(
                f"a {BACKUP_ROLE} run on {node} did not finish in {BACKUP_TIMEOUT_S}s"
            )
        stamp = f"/tmp/failover-backup-{secrets.token_hex(4)}"  # noqa: S108 - scratch stamp inside the DinD node
        shell.run(["docker", "exec", node, "touch", stamp])
        for unit in names:
            shell.run(
                ["docker", "exec", node, "systemctl", "start", unit],
                timeout=BACKUP_TIMEOUT_S,
            )
        return stamp

    def new_backup_files(self, node: str, stamp: str, *, pattern: str) -> list[str]:
        return shell.run(
            [
                "docker",
                "exec",
                node,
                "find",
                backup_search_root(),
                "-path",
                f"*/{backup_repo_name()}/*",
                "-type",
                "f",
                "-name",
                pattern,
                "-cnewer",
                stamp,
            ],
            check=False,
        ).split()

    def backup_contains(self, node: str, stamp: str, token: str) -> list[str]:
        return shell.run(
            [
                "docker",
                "exec",
                node,
                "find",
                backup_search_root(),
                "-path",
                f"*/{backup_repo_name()}/*",
                "-type",
                "f",
                "-cnewer",
                stamp,
                "-exec",
                "grep",
                "-l",
                "-F",
                token,
                "{}",
                "+",
            ],
            check=False,
        ).split()

    def verify_backup(self, node: str, stamp: str, token: str) -> tuple[bool, str]:
        """Return whether the backup taken after ``stamp`` restores the marker.

        Postgres and MariaDB replay the marker database's SQL dump into a
        scratch instance; OpenLDAP, copied as files, must carry the marker
        entry in the copied database files.
        """
        if self.engine == "openldap":
            hits = self.backup_contains(node, stamp, token)
            return bool(
                hits
            ), f"marker found in {hits}" if hits else "marker in no copied file"
        wanted = MARKER_DATABASE[self.engine]
        dumps = [
            d
            for d in self.new_backup_files(node, stamp, pattern="*.sql")
            if engines.dump_database(d) == wanted
        ]
        if not dumps:
            return False, f"no new SQL dump of database {wanted} on {node}"
        return self.restore_into_scratch(node, max(dumps), token)

    def restore_into_scratch(
        self, node: str, dump: str, token: str
    ) -> tuple[bool, str]:
        """Replay one SQL dump into a throwaway container on ``node`` and look for the marker."""
        name = f"failover-scratch-{self.engine}"
        database = engines.dump_database(dump)
        image = self._engine_image()
        shell.run(["docker", "exec", node, "docker", "rm", "-f", name], check=False)
        shell.run(
            [
                "docker",
                "exec",
                node,
                *engines.scratch_run(self.engine, name=name, image=image),
            ]
        )
        try:
            ready = shell.wait_until(
                lambda: (
                    shell.execute(
                        [
                            "docker",
                            "exec",
                            node,
                            "docker",
                            "exec",
                            name,
                            *engines.scratch_ready(self.engine),
                        ]
                    ).returncode
                    == 0
                ),
                timeout_s=SETTLE_TIMEOUT_S,
            )
            if not ready:
                return False, "scratch instance never became ready"
            if self.engine == "mariadb":
                shell.run(
                    [
                        "docker",
                        "exec",
                        node,
                        "docker",
                        "exec",
                        name,
                        *engines.scratch_sql(
                            self.engine,
                            "mysql",
                            f"CREATE DATABASE IF NOT EXISTS `{database}`",
                        ),
                    ]
                )
            load = shell.execute(
                [
                    "docker",
                    "exec",
                    node,
                    "sh",
                    "-c",
                    'exec docker exec -i "$@" < "$0"',
                    dump,
                    name,
                    *engines.scratch_load(self.engine, database),
                ],
                timeout=BACKUP_TIMEOUT_S,
            )
            found = shell.execute(
                [
                    "docker",
                    "exec",
                    node,
                    "docker",
                    "exec",
                    name,
                    *engines.scratch_sql(
                        self.engine,
                        database,
                        f"SELECT token FROM failover_marker WHERE token = '{token}'",  # noqa: S608 - token is a hex string the suite generated
                    ),
                ]
            ).stdout.strip()
            detail = f"replayed {dump} (rc={load.returncode}) into {database}"
            if load.returncode:
                detail += f": {load.stderr.strip()[-500:]}"
            if found != token:
                stamps = shell.execute(
                    [
                        "docker",
                        "exec",
                        node,
                        "grep",
                        "-E",
                        "^-- (Host|Server version|Dump completed)",
                        dump,
                    ]
                ).stdout.split("\n")
                detail += f"; dump header: {' | '.join(s for s in stamps if s)}"
            return found == token, detail
        finally:
            shell.run(["docker", "exec", node, "docker", "rm", "-f", name], check=False)
