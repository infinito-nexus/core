"""OpenLDAP role backend: ``olcReadOnly`` toggle, ranked by contextCSN."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .roles import Role, RoleError, run_command

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def _attribute(ldif: str, name: str) -> list[str]:
    prefix = name.lower() + ":"
    return [
        line.split(":", 1)[1].strip()
        for line in ldif.splitlines()
        if line.lower().startswith(prefix)
    ]


class OpenLDAPRole(Role):
    """One slapd instance driven through ``ldapmodify``/``ldapsearch``.

    The local instance is reached over ``ldapi:///`` with SASL EXTERNAL, so
    the elector needs no local password. Peers are read with a simple bind.

    Args:
        host_id: this instance's host id.
        peers: the other instances' host ids.
        database_dn: the cn=config entry of the replicated database, e.g.
            ``olcDatabase={1}mdb,cn=config``.
        suffix: the database suffix whose contextCSN is compared.
        peer_url: maps a host id to its ``ldap://`` URL.
        bind_dn: DN used to read peers.
        bind_password_file: file holding that DN's password.
        run: command runner, ``(argv, stdin) -> stdout``.
    """

    def __init__(
        self,
        *,
        host_id: str,
        peers: Sequence[str],
        database_dn: str,
        suffix: str,
        peer_url: Callable[[str], str],
        bind_dn: str,
        bind_password_file: str,
        run: Callable[[Sequence[str], str | None], str] = run_command,
    ) -> None:
        self.host_id = host_id
        self.peers = [peer for peer in peers if peer != host_id]
        self._database_dn = database_dn
        self._suffix = suffix
        self._peer_url = peer_url
        self._bind_dn = bind_dn
        self._bind_password_file = bind_password_file
        self._run = run

    def _set_read_only(self, value: str) -> None:
        self._run(
            ["ldapmodify", "-Q", "-Y", "EXTERNAL", "-H", "ldapi:///"],
            f"dn: {self._database_dn}\n"
            "changetype: modify\n"
            "replace: olcReadOnly\n"
            f"olcReadOnly: {value}\n",
        )

    def _local_csns(self) -> list[str]:
        out = self._run(
            [
                "ldapsearch",
                "-Q",
                "-LLL",
                "-Y",
                "EXTERNAL",
                "-H",
                "ldapi:///",
                "-s",
                "base",
                "-b",
                self._suffix,
                "contextCSN",
            ],
            None,
        )
        return sorted(_attribute(out, "contextCSN"))

    def _peer_csns(self, peer: str) -> list[str]:
        out = self._run(
            [
                "ldapsearch",
                "-LLL",
                "-x",
                "-o",
                "nettimeout=1",
                "-H",
                self._peer_url(peer),
                "-D",
                self._bind_dn,
                "-y",
                self._bind_password_file,
                "-s",
                "base",
                "-b",
                self._suffix,
                "contextCSN",
            ],
            None,
        )
        return sorted(_attribute(out, "contextCSN"))

    def is_ready_to_compete(self) -> bool:
        """Ready once the initial syncrepl refresh is done: the local
        contextCSN set equals a reachable peer's. With no peer reachable the
        instance competes on its own data, which is how a cold start of the
        whole cluster gets a writer at all."""
        try:
            local = self._local_csns()
        except RoleError:
            return False
        reachable = list(self.peer_ranks_raw().values())
        return not reachable or local in reachable

    def peer_ranks_raw(self) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for peer in self.peers:
            try:
                found[peer] = self._peer_csns(peer)
            except RoleError:
                continue
        return found

    def rank(self) -> str:
        csns = self._local_csns()
        return max(csns) if csns else ""

    def peer_ranks(self) -> dict[str, str]:
        return {
            peer: max(csns) if csns else ""
            for peer, csns in self.peer_ranks_raw().items()
        }

    def is_writable(self) -> bool:
        out = self._run(
            [
                "ldapsearch",
                "-Q",
                "-LLL",
                "-Y",
                "EXTERNAL",
                "-H",
                "ldapi:///",
                "-s",
                "base",
                "-b",
                self._database_dn,
                "olcReadOnly",
            ],
            None,
        )
        values = _attribute(out, "olcReadOnly")
        return not values or values[0].upper() != "TRUE"

    def become_read_only(self) -> None:
        self._set_read_only("TRUE")

    def become_writer(self) -> None:
        self._set_read_only("FALSE")

    def follow(self, writer: str | None) -> None:
        """Nothing to do: every instance runs syncrepl against all peers, so
        the replication topology does not change with the writer."""
