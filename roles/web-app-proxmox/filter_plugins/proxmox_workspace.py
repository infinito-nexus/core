from __future__ import annotations

import re

from ansible.errors import AnsibleFilterError

WORKSPACE_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
WORKSPACE_ROLE = "InfinitoWorkspace"
STORAGE_ROLE = "InfinitoWorkspaceStorage"
BRIDGE_ROLE = "InfinitoWorkspaceBridge"
TEMPLATE_ROLE = "InfinitoTemplateClone"


def proxmox_workspace_acls(workspace: str, workspaces: dict) -> list[dict]:
    """Args:
        workspace: the workspace id, a lowercase UUID.
        workspaces: ``services.proxmox.workspaces`` with ``storage``,
            ``bridge`` and ``templates`` (``kvm`` and ``emulated`` VM ids).

    Returns:
        Every ACL the workspace's user and its token hold, as
        ``{"path", "role", "propagate"}``: its pool, its storage, its bridge
        and the two templates it may clone.
    """
    if not WORKSPACE_ID.fullmatch(str(workspace)):
        raise AnsibleFilterError(f"workspace id {workspace!r} is no lowercase UUID")
    templates = workspaces["templates"]
    return [
        {"path": f"/pool/ws-{workspace}", "role": WORKSPACE_ROLE, "propagate": 1},
        {
            "path": f"/storage/{workspaces['storage']}",
            "role": STORAGE_ROLE,
            "propagate": 0,
        },
        {
            "path": f"/sdn/zones/localnetwork/{workspaces['bridge']}",
            "role": BRIDGE_ROLE,
            "propagate": 0,
        },
        {"path": f"/vms/{templates['kvm']}", "role": TEMPLATE_ROLE, "propagate": 0},
        {
            "path": f"/vms/{templates['emulated']}",
            "role": TEMPLATE_ROLE,
            "propagate": 0,
        },
    ]


class FilterModule:
    def filters(self):
        return {"proxmox_workspace_acls": proxmox_workspace_acls}
