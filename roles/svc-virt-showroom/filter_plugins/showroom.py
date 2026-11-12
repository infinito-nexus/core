from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleFilterError

from utils.cache.yaml import dump_yaml_str
from utils.sizes import to_bytes
from utils.templating.ansible import to_plain

FLAVOR_VM = "vm"
FLAVOR_CONTAINER = "container"
FLAVORS = (FLAVOR_VM, FLAVOR_CONTAINER)
ROOT_DEVICE = "root"
NIC_DEVICE = "eth0"
UPSTREAM_PORT = 443
SSHD_DROP_IN = "/etc/ssh/sshd_config.d/60-showroom.conf"


def _entries(projects: Any) -> list[tuple[str, Mapping[str, Any]]]:
    if not isinstance(projects, Mapping):
        raise AnsibleFilterError(
            f"services.showroom.projects must be a mapping, got {type(projects).__name__}"
        )
    entries = []
    for name, entry in sorted(projects.items()):
        if not isinstance(entry, Mapping):
            raise AnsibleFilterError(
                f"services.showroom.projects.{name} must be a mapping, "
                f"got {type(entry).__name__}"
            )
        entries.append((str(name), entry))
    return entries


def flavor_of(entry: Mapping[str, Any]) -> str:
    """Return the flavor of one project entry, ``vm`` when it names none.

    Args:
        entry: one value of ``services.showroom.projects``.
    """
    flavor = str(entry.get("flavor") or FLAVOR_VM)
    if flavor not in FLAVORS:
        raise AnsibleFilterError(f"flavor '{flavor}' is none of {', '.join(FLAVORS)}")
    return flavor


def budget_errors(projects: Any, budget_memory: Any) -> list[str]:
    """Return the refusal when the projects together exceed the memory budget.

    Args:
        projects: ``services.showroom.projects``.
        budget_memory: ``services.showroom.budget.memory``, such as ``16GiB``.

    Returns:
        One message naming every project and its memory, or nothing when the
        sum fits the budget.
    """
    entries = _entries(projects)
    budget = to_bytes(budget_memory)
    if budget is None:
        raise AnsibleFilterError("services.showroom.budget.memory is empty")
    total = sum(to_bytes(entry["memory"]) or 0 for _, entry in entries)
    if total <= budget:
        return []
    listing = ", ".join(f"{name}: {entry['memory']}" for name, entry in entries)
    return [
        (
            f"The showroom projects need {total} bytes of memory together "
            f"({listing}), which exceeds services.showroom.budget.memory "
            f"{budget_memory} ({budget} bytes). Lower a project's memory, drop a "
            "project, or raise the budget."
        )
    ]


def kvm_errors(projects: Any, kvm_present: bool) -> list[str]:
    """Return one refusal per ``vm`` project on a host without ``/dev/kvm``.

    Args:
        projects: ``services.showroom.projects``.
        kvm_present: whether the host exposes ``/dev/kvm``.
    """
    vms = [name for name, entry in _entries(projects) if flavor_of(entry) == FLAVOR_VM]
    if kvm_present:
        return []
    return [
        f"Project '{name}' runs flavor vm, but this host has no /dev/kvm. "
        f"Set flavor: container in services.showroom.projects.{name} to run "
        "it as a system container with nesting instead."
        for name in vms
    ]


def user_data(entry: Mapping[str, Any]) -> str:
    """Return the cloud-init user-data that admits the entry's keys for root.

    Args:
        entry: one value of ``services.showroom.projects``.
    """
    keys = [str(key) for key in entry.get("ssh_authorized_keys") or []]
    document = {
        "disable_root": False,
        "packages": ["openssh-server", "systemd-timesyncd"],
        "users": [{"name": "root", "ssh_authorized_keys": keys}],
        "write_files": [
            {
                "path": SSHD_DROP_IN,
                "permissions": "0644",
                "content": "PasswordAuthentication no\n",
            }
        ],
    }
    return "#cloud-config\n" + dump_yaml_str(document, sort_keys=True)


def instances(projects: Any, pool: str, bridge: str) -> list[dict[str, Any]]:
    """Return the Incus instance every project entry asks for.

    Args:
        projects: ``services.showroom.projects``.
        pool: the storage pool the root disks live in.
        bridge: the managed bridge every instance's NIC joins.

    Returns:
        One dict per project with ``project``, ``name``, ``image``, ``vm``,
        ``config`` (instance keys reconciled on every run), ``user_data``
        (set at creation only, cloud-init reads it on first boot) and
        ``devices``.
    """
    result = []
    for name, entry in _entries(projects):
        flavor = flavor_of(entry)
        config = {
            "limits.cpu": str(entry["cpus"]),
            "limits.memory": str(entry["memory"]),
        }
        if flavor == FLAVOR_CONTAINER:
            config["security.nesting"] = "true"
        result.append(
            {
                "project": name,
                "name": name,
                "image": str(entry["image"]),
                "vm": flavor == FLAVOR_VM,
                "config": config,
                "user_data": user_data(entry),
                "devices": {
                    ROOT_DEVICE: {
                        "type": "disk",
                        "path": "/",
                        "pool": str(pool),
                        "size": str(entry["disk"]),
                    },
                    NIC_DEVICE: {
                        "type": "nic",
                        "network": str(bridge),
                        "ipv4.address": str(entry["address"]),
                    },
                },
            }
        )
    return result


def creation_yaml(instance: Mapping[str, Any]) -> str:
    """Return the instance document ``incus create`` reads from stdin.

    Args:
        instance: one item of :func:`instances`.
    """
    document = {
        "config": {
            **instance["config"],
            "cloud-init.user-data": instance["user_data"],
        },
        "devices": instance["devices"],
    }
    return dump_yaml_str(to_plain(document), sort_keys=True)


def settings(instances_: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Return every instance key and device key a run reconciles.

    Args:
        instances_: the output of :func:`instances`.

    Returns:
        One dict per key with ``project``, ``name``, ``device`` (empty for an
        instance key), ``key`` and ``value``.
    """
    result = []
    for instance in instances_:
        base = {"project": instance["project"], "name": instance["name"]}
        for key, value in sorted(instance["config"].items()):
            result.append({**base, "device": "", "key": key, "value": value})
        result.append(
            {
                **base,
                "device": ROOT_DEVICE,
                "key": "size",
                "value": instance["devices"][ROOT_DEVICE]["size"],
            }
        )
        result.append(
            {
                **base,
                "device": NIC_DEVICE,
                "key": "ipv4.address",
                "value": instance["devices"][NIC_DEVICE]["ipv4.address"],
            }
        )
    return result


def domains(projects: Any) -> list[str]:
    """Return every domain of every project, sorted.

    Args:
        projects: ``services.showroom.projects``.
    """
    return sorted(
        str(domain)
        for _, entry in _entries(projects)
        for domain in entry.get("domains") or []
    )


def vhosts(projects: Any) -> list[dict[str, str]]:
    """Return one front-proxy target per domain of every project.

    Args:
        projects: ``services.showroom.projects``.

    Returns:
        One dict per domain with ``domain``, ``project`` and ``upstream``
        (``<address>:443`` of the project's server).
    """
    seen: dict[str, str] = {}
    result = []
    for name, entry in _entries(projects):
        for domain in map(str, entry.get("domains") or []):
            if domain in seen:
                raise AnsibleFilterError(
                    f"domain '{domain}' is listed by project '{seen[domain]}' "
                    f"and project '{name}'"
                )
            seen[domain] = name
            result.append(
                {
                    "domain": domain,
                    "project": name,
                    "upstream": f"{entry['address']}:{UPSTREAM_PORT}",
                }
            )
    return result


class FilterModule:
    def filters(self):
        return {
            "showroom_budget_errors": budget_errors,
            "showroom_kvm_errors": kvm_errors,
            "showroom_instances": instances,
            "showroom_creation_yaml": creation_yaml,
            "showroom_settings": settings,
            "showroom_domains": domains,
            "showroom_vhosts": vhosts,
        }
