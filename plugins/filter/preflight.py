"""Filters that read the host probes of the constructor pre-flight."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleFilterError

from utils.preflight.host import disk_usage_errors
from utils.preflight.ports import (
    containerised_pids,
    parse_listeners,
    port_conflicts,
    probed_pids,
    suspect_pids,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def _ports(ports: Mapping[str, Sequence[str]]) -> dict[int, list[str]]:
    return {int(port): list(owners) for port, owners in ports.items()}


def preflight_disk_usage(
    df_output: str, paths: Sequence[str], maximum: Any
) -> list[str]:
    """Every probed path whose filesystem is fuller than the limit.

    Args:
        df_output: the stdout of ``df -P -- <paths>``.
        paths: the paths ``df`` was asked about, in that order.
        maximum: the highest usage in percent a filesystem may reach.
    """
    try:
        return disk_usage_errors(list(paths), str(df_output), int(maximum))
    except ValueError as exc:
        raise AnsibleFilterError(f"preflight_disk_usage: {exc}") from exc


def preflight_port_cgroups(
    ss_output: str, ports: Mapping[str, Sequence[str]]
) -> list[str]:
    """The cgroup files of the host processes on a public port of the deploy.

    Args:
        ss_output: the stdout of ``ss -Htlnpu``.
        ports: the ``lookup('public_ports', group_names)`` mapping.

    Returns:
        ``/proc/<pid>/cgroup`` of every process other than docker's own that
        listens on one of ``ports``; empty when there is none.
    """
    try:
        listeners = parse_listeners(str(ss_output))
    except ValueError as exc:
        raise AnsibleFilterError(f"preflight_port_cgroups: {exc}") from exc
    return [f"/proc/{pid}/cgroup" for pid in suspect_pids(listeners, _ports(ports))]


def preflight_port_conflicts(
    ss_output: str, cgroup_probe: Mapping[str, Any], ports: Mapping[str, Sequence[str]]
) -> list[str]:
    """Every public port of the deploy a host process outside docker holds.

    Args:
        ss_output: the stdout of ``ss -Htlnpu``.
        cgroup_probe: the registered result of ``grep -H . <cgroup files>``
            over :func:`preflight_port_cgroups`; skipped when that was empty.
        ports: the ``lookup('public_ports', group_names)`` mapping.
    """
    try:
        listeners = parse_listeners(str(ss_output))
    except ValueError as exc:
        raise AnsibleFilterError(f"preflight_port_conflicts: {exc}") from exc
    cgroups = "" if cgroup_probe.get("skipped") else str(cgroup_probe["stdout"])
    return port_conflicts(
        listeners, containerised_pids(cgroups), _ports(ports), probed_pids(cgroups)
    )


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {
            "preflight_disk_usage": preflight_disk_usage,
            "preflight_port_cgroups": preflight_port_cgroups,
            "preflight_port_conflicts": preflight_port_conflicts,
        }
