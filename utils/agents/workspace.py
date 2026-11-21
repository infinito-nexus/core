"""The ``workspace`` field of an agent role: where the agent lives and how it
reaches its models.

``kind`` picks the location: ``host`` (interactive only), ``server`` (the
server workspace under Kata or gVisor), ``agentbox`` (a local box under
sysbox or kata), or one of the VM kinds ``incus`` and ``proxmox``. A VM kind
names the inventory host of its hypervisor in ``target``, takes its size from
``resources`` and runs only a runtime the VM template ships.
"""

from __future__ import annotations

from ansible.errors import AnsibleFilterError

from utils.sizes import to_bytes

WORKSPACE_KINDS = ("host", "server", "agentbox", "incus", "proxmox")
VM_KINDS = ("incus", "proxmox")
BOX_RUNTIMES = ("sysbox", "kata")
MODEL_ACCESS = ("gateway", "login")
SETTINGS_MODES = ("autopilot", "copilot", "zero-trust")
WORKSPACE_KEYS = (
    "kind",
    "target",
    "box_runtime",
    "model_access",
    "settings_mode",
    "resources",
)
REQUIRED_KEYS = ("kind", "model_access")
RESOURCE_KEYS = ("vcpu", "memory", "disk")
INTERACTIVE_FIREWALL_ROLE = "interactive"


class WorkspaceError(AnsibleFilterError):
    """A workspace lacks a key its consumer needs."""


def inventory_hosts(inventory: dict) -> frozenset[str]:
    """Return every host name an Ansible YAML inventory declares, in any group.

    Args:
        inventory: the parsed inventory document.
    """
    hosts: set[str] = set()
    pending = list((inventory or {}).values())
    while pending:
        group = pending.pop()
        if not isinstance(group, dict):
            continue
        hosts.update((group.get("hosts") or {}).keys())
        pending.extend((group.get("children") or {}).values())
    return frozenset(hosts)


def is_autonomous(agent: dict) -> bool:
    """Return whether the role runs without a human in the loop: it binds no
    ``interactive`` firewall role.

    Args:
        agent: the merged agent configuration.
    """
    return INTERACTIVE_FIREWALL_ROLE not in (agent.get("firewall_roles") or [])


def vm_size(resources: dict) -> dict[str, int]:
    """Return the VM size as numbers: vCPU count, memory and disk in bytes.

    Args:
        resources: the ``workspace.resources`` mapping.
    """
    if not isinstance(resources, dict) or any(
        k not in resources for k in RESOURCE_KEYS
    ):
        raise WorkspaceError(
            f"workspace.resources must map {', '.join(RESOURCE_KEYS)}, got {resources!r}"
        )
    return {
        "vcpu": int(resources["vcpu"]),
        "memory": to_bytes(resources["memory"]),
        "disk": to_bytes(resources["disk"]),
    }


def _resource_problems(resources: object) -> list[str]:
    if not isinstance(resources, dict):
        return ["workspace.resources must map vcpu, memory and disk"]
    problems = [
        f"workspace.resources.{key} is missing"
        for key in RESOURCE_KEYS
        if key not in resources
    ]
    problems.extend(
        f"workspace.resources.{key} is not a resource key"
        for key in resources
        if key not in RESOURCE_KEYS
    )
    if problems:
        return problems
    try:
        size = vm_size(resources)
    except (TypeError, ValueError, AnsibleFilterError) as exc:
        return [f"workspace.resources does not parse: {exc}"]
    return [
        f"workspace.resources.{key} must be positive"
        for key, value in size.items()
        if not value or value <= 0
    ]


def problems(
    agent: dict,
    inventory_hosts: frozenset[str],
    template_runtimes: frozenset[str],
) -> list[str]:
    """Return every rule the agent's ``workspace`` breaks.

    Args:
        agent: the merged agent configuration of one role.
        inventory_hosts: the host names of the inventory the agents deploy from.
        template_runtimes: the runtimes the VM template ships.
    """
    raw = agent.get("workspace")
    if not isinstance(raw, dict):
        return ["workspace must be a mapping"]
    found = [
        f"workspace.{key} is not a workspace key"
        for key in raw
        if key not in WORKSPACE_KEYS
    ]
    missing = [key for key in REQUIRED_KEYS if key not in raw]
    if missing:
        return [*found, *(f"workspace.{key} is required" for key in missing)]
    workspace = raw
    kind = workspace["kind"]
    if kind not in WORKSPACE_KINDS:
        found.append(f"workspace.kind '{kind}' is not one of {WORKSPACE_KINDS}")
    if workspace["model_access"] not in MODEL_ACCESS:
        found.append(
            f"workspace.model_access '{workspace['model_access']}' "
            f"is not one of {MODEL_ACCESS}"
        )
    if workspace["model_access"] == "login" and kind not in VM_KINDS:
        found.append(
            f"workspace.model_access login applies to {' and '.join(VM_KINDS)} only; "
            f"kind {kind} reaches models through the gateway"
        )
    mode = workspace.get("settings_mode")
    if mode is not None and mode not in SETTINGS_MODES:
        found.append(f"workspace.settings_mode '{mode}' is not one of {SETTINGS_MODES}")
    runtime = workspace.get("box_runtime")
    if runtime is not None and runtime not in BOX_RUNTIMES:
        found.append(f"workspace.box_runtime '{runtime}' is not one of {BOX_RUNTIMES}")
    if runtime is not None and kind != "agentbox":
        found.append("workspace.box_runtime applies to kind agentbox only")
    if kind == "agentbox" and runtime is None:
        found.append("workspace.kind agentbox needs a box_runtime")
    if kind == "host" and is_autonomous(agent):
        found.append("workspace.kind host is for an interactive role only")
    if kind in VM_KINDS:
        found.extend(_vm_problems(agent, workspace, inventory_hosts, template_runtimes))
    else:
        found.extend(
            f"workspace.{key} applies to a VM kind only"
            for key in ("target", "resources")
            if workspace.get(key) is not None
        )
    return found


def _vm_problems(
    agent: dict,
    workspace: dict,
    inventory_hosts: frozenset[str],
    template_runtimes: frozenset[str],
) -> list[str]:
    kind = workspace["kind"]
    found: list[str] = []
    target = workspace.get("target")
    if not target or target not in inventory_hosts:
        found.append(
            f"workspace.kind {kind} needs a target that names an inventory host, "
            f"got '{target}'"
        )
    if agent.get("lifecycle") == "always_on":
        found.append(
            f"workspace.kind {kind} serves one task per VM and cannot run always_on"
        )
    if agent.get("runtime") not in template_runtimes:
        found.append(
            f"workspace.kind {kind}: runtime '{agent.get('runtime')}' "
            f"is not in the VM template {sorted(template_runtimes)}"
        )
    found.extend(_resource_problems(workspace.get("resources")))
    return found
