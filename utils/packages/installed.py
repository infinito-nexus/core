"""Prove from the local package database that a package call has nothing to do.

The action plugin runs the argv built here through ``ansible.builtin.command``
and hands the result back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from utils.packages.calls import GENERIC_PACKAGE, STATE_PRESENT, STATES, ModuleCall

if TYPE_CHECKING:
    from collections.abc import Callable

PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9+._-]*")
"""Names carrying a version, an architecture, a path or a URL go to the
package manager module unqueried."""

INSTALLED = "i"
GONE = frozenset({"n", "c"})
"""dpkg status letters: ``n`` (not-installed) and ``c`` (config-files) leave
no package behind. Every letter besides these and ``i`` marks a half-done
transaction that only the package manager module can finish."""

C_LOCALE = ("env", "LC_ALL=C")
"""The not-found messages are translated; only the C locale makes them
comparable."""


def _dpkg_entry(line: str) -> tuple[str, str] | None:
    name, tab, abbrev = line.partition("\t")
    flags = abbrev.rstrip()
    if not tab or len(flags) not in (2, 3):
        return None
    return name, flags[1:]


def _pacman_entry(line: str) -> tuple[str, str] | None:
    fields = line.split(" ")
    return (fields[0], INSTALLED) if len(fields) == 2 else None


def _rpm_entry(line: str) -> tuple[str, str] | None:
    return (line, INSTALLED) if line.split() == [line] else None


@dataclass(frozen=True)
class _Query:
    """How one package database is asked about a list of names.

    Args:
        argv: the command, to which the names are appended.
        entry: parses one stdout line into ``(name, state)``, None if foreign.
        missing: the message naming a package the database does not know.
    """

    argv: tuple[str, ...]
    entry: Callable[[str], tuple[str, str] | None]
    missing: str


_RPM = _Query(
    (*C_LOCALE, "rpm", "--query", "--queryformat=%{NAME}\n"),
    _rpm_entry,
    "package {} is not installed",
)

QUERIES: dict[str, _Query] = {
    "apt": _Query(
        (
            *C_LOCALE,
            "dpkg-query",
            "--show",
            "--showformat=${Package}\t${db:Status-Abbrev}\n",
            "--",
        ),
        _dpkg_entry,
        "dpkg-query: no packages found matching {}",
    ),
    "pacman": _Query(
        (*C_LOCALE, "pacman", "--query", "--"),
        _pacman_entry,
        "error: package '{}' was not found",
    ),
    "dnf": _RPM,
    "dnf5": _RPM,
    "yum": _RPM,
}


def query_argv(call: ModuleCall, pkg_mgr: str) -> list[str] | None:
    """Return the argv of the query that can prove *call* has nothing to do.

    Args:
        call: one module call of a package plan.
        pkg_mgr: the target's ``ansible_facts.pkg_mgr``.

    Returns:
        None unless *call* is a plain host package manager call over plain
        names, on a manager whose database this module can read.
    """
    names = call.args.get("name")
    if (
        call.module != GENERIC_PACKAGE
        or call.become_user is not None
        or set(call.args) != {"name", "state"}
        or call.args["state"] not in STATES
        or pkg_mgr not in QUERIES
        or not isinstance(names, list)
        or not names
        or not all(isinstance(n, str) and PLAIN_NAME.fullmatch(n) for n in names)
    ):
        return None
    return [*QUERIES[pkg_mgr].argv, *names]


def state_holds(call: ModuleCall, pkg_mgr: str, result: dict[str, Any]) -> bool:
    """Tell whether the query result proves *call* has nothing to do.

    Args:
        call: a call :func:`query_argv` built a query for.
        pkg_mgr: the target's ``ansible_facts.pkg_mgr``.
        result: the ``ansible.builtin.command`` result of that query.

    Returns:
        True only when every name is proven to be in the requested state.
        A result that cannot be read in full returns False.
    """
    states = _states(QUERIES[pkg_mgr], call.args["name"], result)
    if states is None:
        return False
    if call.args["state"] == STATE_PRESENT:
        return all(found == {INSTALLED} for found in states.values())
    return all(found <= GONE for found in states.values())


def _states(
    query: _Query, names: list[str], result: dict[str, Any]
) -> dict[str, set[str]] | None:
    rc, stdout, stderr = result.get("rc"), result.get("stdout"), result.get("stderr")
    if (
        result.get("skipped")
        or not isinstance(rc, int)
        or not isinstance(stdout, str)
        or not isinstance(stderr, str)
    ):
        return None
    wanted = set(names)
    messages = {query.missing.format(name): name for name in wanted}
    states: dict[str, set[str]] = {}
    missing: set[str] = set()
    for line in stdout.splitlines():
        if line in messages:
            missing.add(messages[line])
            continue
        entry = query.entry(line)
        if entry is None or entry[0] not in wanted:
            return None
        states.setdefault(entry[0], set()).add(entry[1])
    for line in stderr.splitlines():
        if line not in messages:
            return None
        missing.add(messages[line])
    if (
        states.keys() & missing
        or states.keys() | missing != wanted
        or (rc == 0) == bool(missing)
    ):
        return None
    return {**states, **{name: set() for name in missing}}
