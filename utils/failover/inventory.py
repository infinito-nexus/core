"""The lab inventory the failover suite redeploys from, and the commands it runs."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.yaml import dump_yaml, load_yaml, load_yaml_any
from utils.handler.yaml import YamlHandler

SWARM_EXTRAS_VARS = "inventories/development/swarm.yml"
DEPLOY_EXTRAS = "swarm-nfs-extras.deploy.yml"
SUITE_EXTRAS = "failover-extras.yml"
PLAYBOOK_DIR = PROJECT_ROOT / "playbooks"
_MEMORY = re.compile(r"^(\d+)([kmg])$", re.IGNORECASE)
_UNIT_MB = {"k": 1 / 1024, "m": 1, "g": 1024}


def find_inventory(base: str) -> Path:
    """Return the newest ``devices.yml`` under ``base`` or a ``base-<n>`` round dir.

    Args:
        base: the swarm-test inventory base the matrix provisioned under.
    """
    root = Path(base.rstrip("/"))
    candidates = [
        *root.glob("devices.yml"),
        *root.parent.glob(f"{root.name}-*/devices.yml"),
    ]
    if not candidates:
        raise RuntimeError(f"no devices.yml under {base} or {base}-<n>")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def group_hosts(inventory: dict, group: str) -> list[str]:
    children = (inventory.get("all") or {}).get("children") or {}
    return list(((children.get(group) or {}).get("hosts") or {}).keys())


def set_group_hosts(inventory: dict, group: str, hosts: list[str]) -> dict:
    """Return a copy whose ``group`` lists exactly ``hosts``, in that order.

    Host variables of a host already known anywhere in the inventory are reused.

    Args:
        inventory: parsed ``devices.yml``.
        group: inventory group to rewrite.
        hosts: hostnames in their new order.
    """
    out = copy.deepcopy(inventory)
    children = out.setdefault("all", {}).setdefault("children", {})
    known: dict[str, dict] = {}
    for child in children.values():
        for host, host_vars in ((child or {}).get("hosts") or {}).items():
            known.setdefault(host, dict(host_vars or {}))
    missing = [h for h in hosts if h not in known]
    if missing:
        raise ValueError(f"set_group_hosts: unknown hosts {missing}")
    children.setdefault(group, {})["hosts"] = {h: dict(known[h]) for h in hosts}
    return out


def replace_host(inventory: dict, old: str, new: str) -> dict:
    """Return a copy where ``new`` takes ``old``'s position in every group listing ``old``.

    Args:
        inventory: parsed ``devices.yml``.
        old: host that is gone.
        new: replacement host, already known to the inventory.
    """
    out = copy.deepcopy(inventory)
    for name, child in list(((out.get("all") or {}).get("children") or {}).items()):
        hosts = list(((child or {}).get("hosts") or {}).keys())
        if old in hosts:
            order = [new if h == old else h for h in hosts if h != new]
            out = set_group_hosts(out, name, order)
    return out


def memory_mb(value: str) -> int:
    match = _MEMORY.match(str(value).strip())
    if not match:
        raise ValueError(f"unparsable memory size {value!r}")
    return int(int(match.group(1)) * _UNIT_MB[match.group(2).lower()])


def bump_memory(host_vars: dict, *, app_id: str, service: str, delta_mb: int) -> dict:
    """Return a copy with the service's ``mem_limit`` and ``mem_reservation`` raised.

    Args:
        host_vars: parsed ``host_vars/<host>.yml``.
        app_id: the engine role.
        service: the role's service key.
        delta_mb: megabytes to add.
    """
    out = copy.deepcopy(host_vars)
    entry = out["applications"][app_id]["services"][service]
    for key in ("mem_limit", "mem_reservation"):
        if key in entry:
            entry[key] = f"{memory_mb(entry[key]) + delta_mb}m"
    if "mem_limit" not in entry:
        raise ValueError(f"{app_id}.{service} has no mem_limit to change")
    return out


class LabInventory:
    """The provisioned inventory directory of the running lab.

    Args:
        devices: path of its ``devices.yml``.
    """

    def __init__(self, devices: Path):
        self.devices = devices
        self.dir = devices.parent
        self.password = self.dir / ".password"

    def load(self) -> dict:
        return load_yaml(str(self.devices))

    def save(self, inventory: dict) -> None:
        dump_yaml(str(self.devices), inventory)

    def host_vars_files(self) -> list[Path]:
        return sorted((self.dir / "host_vars").glob("*.yml"))

    def bump_memory(self, *, app_id: str, service: str, delta_mb: int) -> int:
        """Raise one service's memory in every host's vars; return the files changed."""
        changed = 0
        for path in self.host_vars_files():
            data = YamlHandler.wrap_existing_vaults(
                load_yaml_any(str(path), default_if_missing={})
            )
            services = ((data.get("applications") or {}).get(app_id) or {}).get(
                "services"
            ) or {}
            if "mem_limit" not in (services.get(service) or {}):
                continue
            data = bump_memory(data, app_id=app_id, service=service, delta_mb=delta_mb)
            dump_yaml(str(path), data)
            changed += 1
        return changed

    def write_suite_extras(self, app_id: str) -> Path:
        path = self.dir / SUITE_EXTRAS
        dump_yaml(str(path), {"PRIMARY_APPS": [app_id]})
        return path


def deploy_options(inventory: LabInventory) -> list[str]:
    """Return the deploy options the swarm matrix uses, after the inventory path."""
    return [
        "-p",
        str(inventory.password),
        "--skip-build",
        "--skip-cleanup",
        "--skip-backup",
        "-e",
        f"@{SWARM_EXTRAS_VARS}",
        "-e",
        f"@{inventory.dir / DEPLOY_EXTRAS}",
        "-e",
        f"@{inventory.dir / SUITE_EXTRAS}",
    ]


def deploy_argv(inventory: LabInventory, python: str) -> list[str]:
    return [
        python,
        "-m",
        "cli.administration.deploy.swarm",
        str(inventory.devices),
        *deploy_options(inventory),
    ]


def forget_argv(inventory: LabInventory, host: str) -> list[str]:
    """Return the ``make swarm-forget-node`` call that forgets ``host`` and redeploys."""
    return [
        "make",
        "--no-print-directory",
        "swarm-forget-node",
        f"host={host}",
        f"inventory={inventory.devices}",
        f"args={' '.join(deploy_options(inventory))}",
    ]


def playbook_argv(
    inventory: LabInventory, playbook: str, extra_vars: dict, limit: str = ""
) -> list[str]:
    """Return the ``ansible-playbook`` call of one suite playbook in ``PLAYBOOK_DIR``.

    Args:
        inventory: the lab inventory.
        playbook: file name under ``PLAYBOOK_DIR``.
        extra_vars: passed as one JSON ``-e``.
        limit: host pattern for ``--limit``; empty runs on every host the
            playbook targets.
    """
    argv = [
        "ansible-playbook",
        "-i",
        str(inventory.devices),
        "--vault-password-file",
        str(inventory.password),
        "-e",
        json.dumps(extra_vars, sort_keys=True),
    ]
    if limit:
        argv += ["--limit", limit]
    return [*argv, str(PLAYBOOK_DIR / playbook)]
