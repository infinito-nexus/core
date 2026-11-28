from __future__ import annotations

import json
import re

from utils.sizes import docker_to_bytes

STORAGE_ID = re.compile(r"[a-z][a-z0-9._-]*[a-z0-9]", re.IGNORECASE)


def _payload(result: dict) -> object:
    if not isinstance(result, dict) or result.get("rc") != 0:
        return None
    try:
        return json.loads(result["stdout"])
    except (KeyError, TypeError, ValueError):
        return None


def _entries(result: dict) -> list[dict]:
    payload = _payload(result)
    if not isinstance(payload, list):
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


def _thin_used(thin: dict) -> dict[str, int]:
    payload = _payload(thin)
    reports = payload.get("report") if isinstance(payload, dict) else None
    used: dict[str, int] = {}
    for report in reports or []:
        for volume in report.get("lv") or []:
            try:
                data = int(
                    float(volume["lv_size"]) * float(volume["data_percent"]) / 100
                )
            except (KeyError, TypeError, ValueError):
                continue
            name = str(volume.get("lv_name", ""))
            used[name] = min(used.get(name, data), data)
    return used


def proxmox_image_storages(resources: dict, node: str, storage: str) -> list[str]:
    """Args:
        resources: the registered ``pvesh get /cluster/resources`` call.
        node: the Proxmox VE node of this host.
        storage: the one storage that holds the agent disks as a fixed pool;
            "" when the agent disks may live on every local image storage.

    Returns:
        The available storages of ``node`` that hold VM images and are not
        shared, so the space their volumes take is space of this host, and
        only ``storage`` when it is set; an id outside the Proxmox VE storage
        id format is left out.
    """
    return sorted(
        str(entry.get("storage"))
        for entry in _entries(resources)
        if entry.get("type") == "storage"
        and entry.get("node") == node
        and entry.get("status") == "available"
        and not entry.get("shared")
        and "images" in str(entry.get("content", "")).split(",")
        and STORAGE_ID.fullmatch(str(entry.get("storage")))
        and (not storage or entry.get("storage") == storage)
    )


def proxmox_agent_pool(status: dict, storage: str, guest_disk: str) -> dict:
    """Args:
        status: the registered loop of ``pvesh get
            /nodes/<node>/storage/<storage>/status`` over ``storage``.
        storage: the guest storage that holds the agent disks under the
            ``vm`` flavor; "" under ``container``.
        guest_disk: ``services.proxmox.guest.disk``, in QEMU notation, where
            every suffix is binary.

    Returns:
        ``size`` and ``used`` of the fixed pool the agent disks live in: the
        ``total`` and ``used`` the storage reports, or, while it reports
        none, the whole guest disk with nothing used, so a first deploy still
        bounds the agent disks by the guest disk; ``""`` and 0 without
        ``storage``, as the agent disks then take the free space of the
        Docker root.
    """
    if not storage:
        return {"size": "", "used": 0}
    for call in (status or {}).get("results") or []:
        payload = _payload(call)
        try:
            total = int(payload["total"])
            used = int(payload.get("used") or 0)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if total > 0:
            return {"size": str(total), "used": used}
    return {"size": str(docker_to_bytes(guest_disk)), "used": 0}


def proxmox_agent_usage(
    resources: dict, volumes: dict, thin: dict, pool: str
) -> dict[str, int]:
    """Args:
        resources: the registered ``pvesh get /cluster/resources`` call; a
            skipped or failed call reads as no agent VM.
        volumes: the registered loop of ``pvesh get
            /nodes/<node>/storage/<storage>/content`` over
            ``proxmox_image_storages``.
        thin: the registered ``lvs --reportformat json`` call; it carries the
            data of the LVM-thin volumes, for which Proxmox VE lists no use.
        pool: the resource pool the agent VMs live in.

    Returns:
        ``memory``: the bytes the running agent VMs of ``pool`` hold, from
        the host's view (``memhost``); ``disk``: the bytes their volumes take
        on the local image storages. A template counts for neither.
    """
    agents = [
        entry
        for entry in _entries(resources)
        if entry.get("type") == "qemu"
        and entry.get("pool") == pool
        and not entry.get("template")
    ]
    owners = {str(entry.get("vmid")) for entry in agents}
    thin_used = _thin_used(thin)
    disk = 0
    for call in (volumes or {}).get("results") or []:
        for volume in _entries(call):
            if str(volume.get("vmid")) not in owners:
                continue
            name = str(volume.get("volid", "")).partition(":")[2].rpartition("/")[2]
            disk += int(volume.get("used") or 0) or thin_used.get(name, 0)
    memory = sum(
        int(entry.get("memhost") or 0)
        for entry in agents
        if entry.get("status") == "running"
    )
    return {"memory": memory, "disk": disk}


class FilterModule:
    def filters(self):
        return {
            "proxmox_agent_pool": proxmox_agent_pool,
            "proxmox_agent_usage": proxmox_agent_usage,
            "proxmox_image_storages": proxmox_image_storages,
        }
