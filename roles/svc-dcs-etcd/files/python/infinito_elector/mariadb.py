"""MariaDB role backend: ``read_only`` toggle and GTID-based promotion."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .roles import ReseedRequired, RestartRequired, Role, RoleError, run_command

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


@dataclass(frozen=True, order=True)
class GtidPosition:
    """A GTID position ordered by its total sequence number."""

    total: int
    text: str = field(compare=False, default="")

    @classmethod
    def parse(cls, text: str) -> GtidPosition:
        total = 0
        for gtid in filter(None, (part.strip() for part in text.split(","))):
            pieces = gtid.split("-")
            if len(pieces) != 3 or not all(piece.isdigit() for piece in pieces):
                raise RoleError(f"unparsable GTID {gtid!r}")
            total += int(pieces[2])
        return cls(total, text.strip())


BOOTSTRAP_MARKER = "/var/lib/mysql/.infinito-ha-bootstrap"
RECOVERED_MARKER = "/var/lib/mysql/.infinito-ha-recovered"
DIVERGED_ERRNO = "1236"
ACK_HOLDERS = 2


def _quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


class MariaDBRole(Role):
    """One MariaDB instance driven through the ``mariadb`` client.

    Args:
        host_id: this instance's host id.
        peers: the other instances' host ids.
        defaults_file: client option file holding the elector's SQL user.
        socket: the local server socket.
        local_user: SQL user authenticated by ``unix_socket`` for the local
            server, so a rotated password never locks the elector out of its
            own instance.
        peer_address: maps a host id to the address its instance listens on.
        replication_user: user replicas connect as.
        replication_password: that user's password, or a callable that reads
            it at each use so a rotated password reaches the next CHANGE MASTER.
        run: command runner, ``(argv, stdin) -> stdout``.
        relay_wait_seconds: how long one promotion attempt waits for the
            relay log; kept under the runner's 5 s timeout and the renew
            deadline, a lagging relay log is retried on the next tick.
        bootstrap_marker: file whose presence lets this instance promote alone.
        recovered_marker: file a former writer leaves before its forced
            restart, so the restarted instance follows instead of restarting again.
        silence_grace_seconds: how long a peer must stay unanswering before a
            promotion may leave it out of the ranking.
        diverged_grace_seconds: how long replication must stay on error 1236
            before the instance asks to be re-seeded.
        clock: monotonic clock, injectable for tests.
    """

    QUERY_POSITION = "SELECT @@GLOBAL.gtid_current_pos"

    def __init__(
        self,
        *,
        host_id: str,
        peers: Sequence[str],
        defaults_file: str,
        socket: str,
        peer_address: Callable[[str], str],
        local_user: str,
        replication_user: str,
        replication_password: str | Callable[[], str],
        run: Callable[[Sequence[str], str | None], str] = run_command,
        relay_wait_seconds: int = 3,
        bootstrap_marker: str = BOOTSTRAP_MARKER,
        recovered_marker: str = RECOVERED_MARKER,
        silence_grace_seconds: float = 8.0,
        diverged_grace_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.host_id = host_id
        self.peers = [peer for peer in peers if peer != host_id]
        self._defaults = defaults_file
        self._socket = socket
        self._local_user = local_user
        self._address = peer_address
        self._repl_user = replication_user
        self._repl_password = replication_password
        self._run = run
        self._relay_wait = relay_wait_seconds
        self._following: str | None = None
        self._bootstrap_marker = bootstrap_marker
        self._recovered_marker = recovered_marker
        self._silence_grace = silence_grace_seconds
        self._diverged_grace = diverged_grace_seconds
        self._clock = clock
        self._unranked_since: dict[str, float] = {}
        self._diverged_since: float | None = None
        self._claimed: GtidPosition | None = None
        self._relay_lost = False

    def _sql(self, query: str, host: str | None = None) -> str:
        """Run *query*, fed on stdin so the replication password never shows
        up in the process list."""
        target = self._remote(host) if host else self._local()
        return self._run(["mariadb", *target, "-N", "-B"], query).strip()

    def _remote(self, host: str) -> list[str]:
        return [
            f"--defaults-extra-file={self._defaults}",
            "-h",
            host,
            "--connect-timeout=1",
        ]

    def _local(self) -> list[str]:
        return [
            "--no-defaults",
            "--user",
            self._local_user,
            "--socket",
            self._socket,
        ]

    def _slave_status(self, host: str | None = None) -> dict[str, str]:
        target = self._remote(host) if host else self._local()
        out = self._run(["mariadb", *target, "-E"], "SHOW SLAVE STATUS")
        status: dict[str, str] = {}
        for line in out.splitlines():
            key, sep, value = line.partition(":")
            if sep:
                status[key.strip()] = value.strip()
        return status

    def is_ready_to_compete(self) -> bool:
        try:
            self._sql("SELECT 1")
        except RoleError:
            return False
        return True

    def _position(self, host: str | None = None) -> GtidPosition:
        """Rank by the newer of the applied and the received position.

        Semi-sync acknowledges a commit once a replica's relay log holds it,
        before the replica applies it, so ranking by the applied position
        alone can promote a replica that lacks an acknowledged write.
        """
        applied = GtidPosition.parse(self._sql(self.QUERY_POSITION, host))
        received = self._slave_status(host).get("Gtid_IO_Pos", "")
        return max(applied, GtidPosition.parse(received)) if received else applied

    def quorum(self) -> int:
        """A majority of all instances, or one while the bootstrap marker exists.

        The deploy places the marker on the first writer before any other
        instance holds data and removes it once every instance is seeded.

        An acknowledged write sits on the writer and one replica. A majority
        of three always holds one of them, so a silent peer delays a promotion
        only in larger groups, where a majority can miss both.
        """
        if Path(self._bootstrap_marker).exists():
            return 1
        majority = super().quorum()
        if len(self.peers) + 1 - majority >= ACK_HOLDERS and any(
            self._clock() - since < self._silence_grace
            for since in self._unranked_since.values()
        ):
            return len(self.peers) + 1
        return majority

    def rank(self) -> GtidPosition:
        """The position this instance competes with.

        After a promotion found its relay log could not deliver the received
        position, only the applied one counts until it follows a writer again.
        """
        if self._relay_lost:
            self._claimed = GtidPosition.parse(self._sql(self.QUERY_POSITION))
        else:
            self._claimed = self._position()
        return self._claimed

    def peer_ranks(self) -> dict[str, GtidPosition]:
        """Rank every answering peer, remembering since when the others are silent.

        Semi-sync needs one acknowledgement, so the only holder of the newest
        acknowledged write may be the one peer that answers late; ``quorum``
        blocks a promotion until each silent peer has stayed silent for the
        grace period.
        """
        ranks: dict[str, GtidPosition] = {}
        for peer in self.peers:
            try:
                ranks[peer] = self._position(self._address(peer))
                self._unranked_since.pop(peer, None)
            except RoleError:
                self._unranked_since.setdefault(peer, self._clock())
        return ranks

    def is_writable(self) -> bool:
        """Report whether the server accepts writes.

        Returns:
            True when ``read_only`` is off: ``OFF`` from MariaDB 11.7 on, where
            it became an ENUM, and ``0`` on older servers.
        """
        return self._sql("SELECT @@GLOBAL.read_only") in ("0", "OFF")

    def become_read_only(self) -> None:
        self._sql("SET GLOBAL read_only = 1")

    def _wait_relay_log(self) -> None:
        status = self._slave_status()
        if not status:
            return
        self._sql("STOP SLAVE IO_THREAD")
        self._sql("START SLAVE SQL_THREAD")
        status = self._slave_status()
        io_pos = status.get("Gtid_IO_Pos", "")
        if not io_pos:
            return
        result = self._sql(
            f"SELECT MASTER_GTID_WAIT({_quote(io_pos)}, {self._relay_wait})"
        )
        if result != "0":
            raise RoleError(f"relay log not applied within {self._relay_wait}s")

    def become_writer(self) -> None:
        """Promote only once the applied position reached the claimed rank.

        An IO thread reconnect can leave the relay log empty while
        ``Gtid_IO_Pos`` still reports the received position, and promoting
        then would discard acknowledged writes a peer still holds.
        """
        self._wait_relay_log()
        applied = GtidPosition.parse(self._sql(self.QUERY_POSITION))
        if self._claimed is not None and applied < self._claimed:
            self._relay_lost = True
            raise RoleError(
                f"applied {applied.text or 'nothing'} is behind the claimed "
                f"{self._claimed.text}; the relay log no longer holds the difference"
            )
        self._sql("STOP SLAVE")
        self._sql("RESET SLAVE ALL")
        self._following = None
        self._sql("SET GLOBAL rpl_semi_sync_master_enabled = 1")
        self._sql("SET GLOBAL read_only = 0")

    def follow(self, writer: str | None) -> None:
        """Replicate from *writer*; a former writer first restarts once.

        The restart comes before semi-sync is turned off: turning it off first
        would release and commit the writes still waiting for an
        acknowledgement, the errant GTIDs recovery is meant to drop. After the
        restart, a former writer's ``gtid_slave_pos`` predates its own writes,
        and asking the new writer for them again breaks ``gtid_strict_mode``,
        so it starts from ``gtid_current_pos`` instead.
        """
        if writer is None or writer in (self.host_id, self._following):
            return
        former_writer = not self._slave_status()
        if former_writer and not Path(self._recovered_marker).exists():
            open(self._recovered_marker, "w").close()  # noqa: PTH123 - touch
            raise RestartRequired(
                f"{self.host_id} was a writer; restarting so recovery drops "
                "binlog writes no replica acknowledged"
            )
        self._sql("SET GLOBAL rpl_semi_sync_master_enabled = 0")
        self._sql("STOP SLAVE")
        if former_writer:
            os.remove(self._recovered_marker)  # noqa: PTH107
            self._sql("SET GLOBAL gtid_slave_pos = @@GLOBAL.gtid_current_pos")
        self._replicate_from(writer)

    def _replicate_from(self, host: str) -> None:
        self._sql(
            "CHANGE MASTER TO "
            f"MASTER_HOST={_quote(self._address(host))}, "
            f"MASTER_USER={_quote(self._repl_user)}, "
            f"MASTER_PASSWORD={_quote(self._repl_password() if callable(self._repl_password) else self._repl_password)}, "
            "MASTER_USE_GTID=slave_pos, MASTER_CONNECT_RETRY=1"
        )
        self._sql("START SLAVE")
        self._following = host
        self._diverged_since = None
        self._relay_lost = False

    def watch(self) -> None:
        """Ask for a re-seed once replication stays on error 1236.

        The writer then lacks transactions this instance holds, or has purged
        the binary log it needs; neither heals by reconnecting.
        """
        if self._following is None:
            return
        try:
            status = self._slave_status()
        except RoleError:
            return
        if status.get("Last_IO_Errno") != DIVERGED_ERRNO:
            self._diverged_since = None
            return
        if self._diverged_since is None:
            self._diverged_since = self._clock()
        if self._clock() - self._diverged_since < self._diverged_grace:
            return
        try:
            local = self._sql("SELECT @@GLOBAL.gtid_binlog_pos")
        except RoleError as error:
            local = f"unknown ({error})"
        raise ReseedRequired(
            f"{self.host_id} diverged from {self._following} "
            f"(local gtid_binlog_pos {local}): {status.get('Last_IO_Error', '')[:200]}"
        )

    def donor_kind(self) -> str | None:
        """``writer`` or ``replica`` when this instance may donate a seed, else ``None``."""
        try:
            if self.is_writable():
                return "writer"
            status = self._slave_status()
        except RoleError:
            return None
        if (
            status.get("Slave_IO_Running") == "Yes"
            and status.get("Slave_SQL_Running") == "Yes"
        ):
            return "replica"
        return None

    def attach_seed(self, donor: str, position: str) -> None:
        """Replicate a freshly restored copy from its donor, starting at *position*.

        Args:
            donor: host id of the instance that streamed the copy.
            position: GTID position the copy ends at.
        """
        self._sql("STOP SLAVE")
        self._sql(f"SET GLOBAL gtid_slave_pos = {_quote(position)}")
        self._replicate_from(donor)
