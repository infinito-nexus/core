"""
Args:
    argv[1]: the phase. ``prepare`` refuses MEMBERS_ACTION or makes its Keycloak
        change, except the membership end of ``remove``; ``settle`` ends that
        membership, places accepted invitees, drops the entries of invitations
        Keycloak no longer holds, writes the roster and prints the membership
        line; ``list`` prints the membership line and writes nothing.

Env:
    KC_URL: Keycloak base URL.
    KC_REALM: the platform realm.
    KC_CLIENT_ID: the client ``workspace-members``.
    KC_CLIENT_SECRET_FILE: file holding that client's secret.
    WORKSPACE: the workspace id, a lowercase UUID.
    MEMBERS_ACTION: sync, list, add, invite, uninvite, role or remove.
    WORKSPACE_MEMBER: Keycloak user id, for add, role and remove.
    WORKSPACE_ROLE: Owner, Admin, Operator, Billing or Viewer, for role.
    INVITE_KEY: the store's lowercase UUID key of a staged invitation, for invite and uninvite.
    KC_INVITE_CLIENT_ID: the store's client id an invitee returns to, for invite.
    BAO_ADDR: https URL of OpenBao, for invite.
    BAO_TOKEN_FILE: file holding the task's own OpenBao token, for invite.
    KC_RBAC_GROUP_ROOT: path of the RBAC group root, for remove.
    KC_SIGN_IN_GROUP: path of the RBAC group a member needs to sign in to
        Semaphore, which remove takes them out of unless another workspace
        still holds them, for remove.
    MEMBERS_ROSTER_FILE: file settle writes with mode 0600 for the Semaphore mirror.

Output: one ``change workspace=<id> action=<action> ...`` line per change; the
last line is the membership line, ``{"workspace":"<id>","absent":true}`` or
``{"workspace":"<id>","refused":"<reason>"}``.
Exit: 0 done, 3 refused, 1 failed.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import urllib.parse
from collections.abc import Callable

from invites import drop_key, invitations, record_key, staged, write_attributes
from keycloak_admin import KeycloakError, KeycloakHTTPError, ServiceAccount
from organization import ROLES, validate
from workspaces import (
    PENDING_PREFIX,
    RefusalError,
    Workspace,
    keycloak_id,
    marked_workspaces,
    rbac_groups,
    refusal_line,
    service_account,
    write_private,
)

ACTIONS = ("sync", "list", "add", "invite", "uninvite", "role", "remove")
PHASES = ("prepare", "settle", "list")
REFUSED = 3
FAILED = 1
CONFLICT = 409
NOT_FOUND = 404
BAD_REQUEST = 400
ERRORS = (
    KeycloakError,
    OSError,
    KeyError,
    TypeError,
    ValueError,
    http.client.HTTPException,
)

Log = Callable[[str], None]


def change(ws: Workspace, action: str, log: Log, **fields: str) -> None:
    """
    Args:
        ws: the workspace.
        action: the members action.
        log: sink of the line.
        **fields: what changed, such as ``user``, ``group`` and ``change``.
    """
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    log(f"change workspace={ws.workspace} action={action} {details}")


def join(kc: ServiceAccount, ws: Workspace, user_id: str, role: str, log: Log) -> None:
    """
    Args:
        kc: client.
        ws: the workspace, whose holders follow the change.
        user_id: a member.
        role: the role group the member joins.
        log: sink of the change line.
    """
    group = ws.role_groups[role]["id"]
    try:
        kc.call("PUT", f"{ws.base}/groups/{group}/members/{user_id}")
    except KeycloakHTTPError as error:
        if error.status != CONFLICT:
            raise
    ws.holders[role].add(user_id)
    change(ws, ws.action, log, user=user_id, group=role, change="joined")


def leave(kc: ServiceAccount, ws: Workspace, user_id: str, role: str, log: Log) -> None:
    """
    Args:
        kc: client.
        ws: the workspace, whose holders follow the change.
        user_id: a member.
        role: the role group the member leaves.
        log: sink of the change line.
    """
    group = ws.role_groups[role]["id"]
    try:
        kc.call("DELETE", f"{ws.base}/groups/{group}/members/{user_id}")
    except KeycloakHTTPError as error:
        if error.status != BAD_REQUEST:
            raise
    ws.holders[role].discard(user_id)
    change(ws, ws.action, log, user=user_id, group=role, change="left")


def place(kc: ServiceAccount, ws: Workspace, user_id: str, role: str, log: Log) -> None:
    """
    Args:
        kc: client.
        ws: the workspace.
        user_id: a member.
        role: the one role group the member holds afterwards; it is joined
            before any other role group is left.
        log: sink of the change lines.
    """
    if user_id not in ws.holders[role]:
        join(kc, ws, user_id, role, log)
    for other in ws.roles_of(user_id):
        if other != role:
            leave(kc, ws, user_id, other, log)


def add(kc: ServiceAccount, ws: Workspace, env: dict, log: Log) -> None:
    """
    Args:
        kc: client.
        ws: the workspace.
        env: the task environment with WORKSPACE_MEMBER.
        log: sink of the change lines.
    """
    user_id = keycloak_id(env["WORKSPACE_MEMBER"], "WORKSPACE_MEMBER")
    if list(ws.members) == [user_id] and ws.roles_of(user_id) == ["Owner"]:
        return
    others = [member for member in ws.members if member != user_id]
    if others or ws.entries() or invitations(kc, ws, status="PENDING"):
        raise RefusalError("not_first")
    if user_id not in ws.members:
        try:
            kc.call("POST", f"{ws.base}/members", user_id)
        except KeycloakHTTPError as error:
            if error.status != CONFLICT:
                raise
        ws.members[user_id] = {"id": user_id}
        change(ws, ws.action, log, user=user_id, change="joined_organization")
    place(kc, ws, user_id, "Owner", log)


def invite(kc: ServiceAccount, ws: Workspace, env: dict, log: Log) -> None:
    """
    Args:
        kc: client.
        ws: the workspace.
        env: the task environment with INVITE_KEY, KC_INVITE_CLIENT_ID, BAO_ADDR
            and BAO_TOKEN_FILE.
        log: sink of the change lines, which name the key and the role only.
    """
    key = keycloak_id(env["INVITE_KEY"], "INVITE_KEY")
    address, role = staged(env, ws.workspace, key)
    if any((m.get("email") or "").lower() == address for m in ws.members.values()):
        raise RefusalError("member_address")
    pending = invitations(kc, ws, email=address, status="PENDING")
    if pending and ws.entries().get(key) == {"role": role, "address": address}:
        return
    if not pending:
        query = urllib.parse.urlencode({"client_id": env["KC_INVITE_CLIENT_ID"]})
        try:
            kc.submit(f"{ws.base}/members/invite-user?{query}", {"email": address})
        except KeycloakHTTPError as error:
            if error.status != CONFLICT:
                raise
        change(ws, ws.action, log, invite=key, group=role, change="sent")
    write_attributes(
        kc, ws, lambda attributes: record_key(attributes, key, role, address)
    )
    change(ws, ws.action, log, invite=key, group=role, change="pending")


def uninvite(kc: ServiceAccount, ws: Workspace, env: dict, log: Log) -> None:
    """
    Args:
        kc: client.
        ws: the workspace.
        env: the task environment with INVITE_KEY.
        log: sink of the change lines.
    """
    key = keycloak_id(env["INVITE_KEY"], "INVITE_KEY")
    entry = ws.entries().get(key)
    if entry is None:
        return
    for invitation in invitations(kc, ws, email=entry["address"]):
        try:
            kc.call("DELETE", f"{ws.base}/invitations/{invitation['id']}")
        except KeycloakHTTPError as error:
            if error.status != NOT_FOUND:
                raise
        change(ws, ws.action, log, invite=key, change="invitation_deleted")
    write_attributes(kc, ws, lambda attributes: drop_key(attributes, key))
    change(ws, ws.action, log, invite=key, group=entry["role"], change="dropped")


def role(kc: ServiceAccount, ws: Workspace, env: dict, log: Log) -> None:
    """
    Args:
        kc: client.
        ws: the workspace.
        env: the task environment with WORKSPACE_MEMBER and WORKSPACE_ROLE.
        log: sink of the change lines.
    """
    user_id = keycloak_id(env["WORKSPACE_MEMBER"], "WORKSPACE_MEMBER")
    target = env["WORKSPACE_ROLE"]
    if target not in ROLES:
        raise ValueError("WORKSPACE_ROLE is no workspace role")
    if user_id not in ws.members:
        raise RefusalError("not_member")
    if ws.owners_after(user_id, [target]) == 0:
        raise RefusalError("last_owner")
    place(kc, ws, user_id, target, log)


def platform_roles(kc: ServiceAccount, user_id: str, env: dict) -> list[dict]:
    """
    Args:
        kc: client.
        user_id: the member to remove.
        env: the task environment with KC_RBAC_GROUP_ROOT and KC_SIGN_IN_GROUP.

    Returns:
        The RBAC groups the member holds besides the Semaphore sign-in group,
        which remove takes them out of itself.
    """
    return [
        group
        for group in rbac_groups(kc, user_id, env["KC_RBAC_GROUP_ROOT"])
        if group["path"] != env["KC_SIGN_IN_GROUP"]
    ]


def guard_removal(kc: ServiceAccount, ws: Workspace, user_id: str, env: dict) -> None:
    """
    Args:
        kc: client.
        ws: the workspace.
        user_id: the member to remove.
        env: the task environment with KC_RBAC_GROUP_ROOT and KC_SIGN_IN_GROUP.
    """
    if ws.members[user_id].get("membershipType") == "MANAGED":
        raise RefusalError("managed")
    if platform_roles(kc, user_id, env):
        raise RefusalError("platform_role")
    if ws.owners_after(user_id, []) == 0:
        raise RefusalError("last_owner")


def leave_sign_in(
    kc: ServiceAccount, ws: Workspace, user_id: str, env: dict, log: Log
) -> None:
    """
    Args:
        kc: client.
        ws: the workspace.
        user_id: the member to remove.
        env: the task environment with KC_RBAC_GROUP_ROOT and KC_SIGN_IN_GROUP.
        log: sink of the change line; a member of another marked organization
            keeps the sign-in group, which that workspace still needs.
    """
    if marked_workspaces(kc, user_id) - {ws.workspace}:
        return
    for group in rbac_groups(kc, user_id, env["KC_RBAC_GROUP_ROOT"]):
        if group["path"] != env["KC_SIGN_IN_GROUP"]:
            continue
        try:
            kc.call("DELETE", f"users/{user_id}/groups/{group['id']}")
        except KeycloakHTTPError as error:
            if error.status != NOT_FOUND:
                raise
        change(ws, ws.action, log, user=user_id, group=group["path"], change="left")


def remove(kc: ServiceAccount, ws: Workspace, env: dict, log: Log) -> None:
    """
    Args:
        kc: client.
        ws: the workspace.
        env: the task environment with WORKSPACE_MEMBER, KC_RBAC_GROUP_ROOT
            and KC_SIGN_IN_GROUP.
        log: sink of the change lines.
    """
    user_id = keycloak_id(env["WORKSPACE_MEMBER"], "WORKSPACE_MEMBER")
    if user_id not in ws.members:
        return
    guard_removal(kc, ws, user_id, env)
    for held in ws.roles_of(user_id):
        leave(kc, ws, user_id, held, log)
    leave_sign_in(kc, ws, user_id, env, log)


def sync(kc: ServiceAccount, ws: Workspace, env: dict, log: Log) -> None:
    """
    Args:
        kc: client.
        ws: the workspace.
        env: the task environment.
        log: sink of the change lines.
    """


PREPARE = {
    "sync": sync,
    "add": add,
    "invite": invite,
    "uninvite": uninvite,
    "role": role,
    "remove": remove,
}


def end_membership(kc: ServiceAccount, ws: Workspace, env: dict, log: Log) -> None:
    """
    Args:
        kc: client.
        ws: the workspace.
        env: the task environment with WORKSPACE_MEMBER, KC_RBAC_GROUP_ROOT
            and KC_SIGN_IN_GROUP.
        log: sink of the change line.
    """
    user_id = keycloak_id(env["WORKSPACE_MEMBER"], "WORKSPACE_MEMBER")
    if user_id not in ws.members:
        return
    remove(kc, ws, env, log)
    try:
        kc.call("DELETE", f"{ws.base}/members/{user_id}")
    except KeycloakHTTPError as error:
        if error.status not in (BAD_REQUEST, NOT_FOUND):
            raise
    del ws.members[user_id]
    change(ws, ws.action, log, user=user_id, change="left_organization")


def place_accepted(kc: ServiceAccount, ws: Workspace, log: Log) -> None:
    """
    Args:
        kc: client.
        ws: the workspace.
        log: sink of the change lines.
    """
    entries = ws.entries()
    by_address = {entry["address"]: key for key, entry in entries.items()}
    placed = []
    for user_id, member in sorted(ws.members.items()):
        key = by_address.get((member.get("email") or "").lower())
        if key is None or ws.roles_of(user_id):
            continue
        join(kc, ws, user_id, entries[key]["role"], log)
        placed.append(key)
    if not placed:
        return
    write_attributes(
        kc, ws, lambda attributes: [drop_key(attributes, k) for k in placed]
    )
    for key in placed:
        change(
            ws, ws.action, log, invite=key, group=entries[key]["role"], change="placed"
        )


def drop_stale(kc: ServiceAccount, ws: Workspace, log: Log) -> None:
    """
    Args:
        kc: client.
        ws: the workspace.
        log: sink of the change lines.
    """
    attributes = ws.org.get("attributes") or {}
    listed = {
        key
        for role_name in ROLES
        for key in attributes.get(PENDING_PREFIX + role_name, [])
    }
    entries = ws.entries()
    stale = sorted(
        key
        for key in listed
        if key not in entries or not invitations(kc, ws, email=entries[key]["address"])
    )
    if not stale:
        return
    write_attributes(
        kc, ws, lambda attributes: [drop_key(attributes, k) for k in stale]
    )
    for key in stale:
        change(ws, ws.action, log, invite=key, change="dropped")


def settle(kc: ServiceAccount, ws: Workspace, env: dict, log: Log) -> str:
    """
    Args:
        kc: client.
        ws: the workspace.
        env: the task environment with MEMBERS_ROSTER_FILE.
        log: sink of the change lines.

    Returns:
        The membership line of the settled workspace.
    """
    if ws.action == "remove":
        end_membership(kc, ws, env, log)
    place_accepted(kc, ws, log)
    drop_stale(kc, ws, log)
    settled = Workspace.load(kc, ws.workspace, ws.action)
    if settled is None:
        raise KeycloakError(f"the organization of {ws.workspace} vanished")
    write_private(env["MEMBERS_ROSTER_FILE"], settled.roster())
    return settled.line()


def run(phase: str, env: dict, log: Log) -> str | None:
    """
    Args:
        phase: one of PHASES.
        env: the task environment.
        log: sink of the change lines.

    Returns:
        The line the phase prints last, or None when it prints none.
    """
    workspace = validate(env["WORKSPACE"])
    action = env["MEMBERS_ACTION"]
    if phase not in PHASES or action not in ACTIONS:
        raise ValueError("the phase or MEMBERS_ACTION is unknown")
    if (phase == "list") != (action == "list"):
        raise ValueError("only the list action runs the list phase")
    kc = service_account(env)
    ws = Workspace.load(kc, workspace, action)
    if ws is None and action == "list":
        return json.dumps(
            {"workspace": workspace, "absent": True}, separators=(",", ":")
        )
    if ws is None:
        raise RefusalError("absent")
    if phase == "list":
        return ws.line()
    if phase == "prepare":
        PREPARE[action](kc, ws, env, log)
        return None
    return settle(kc, ws, env, log)


def main(argv: list[str]) -> int:
    """
    Args:
        argv: the command line, the phase its only argument.

    Returns:
        The exit status.
    """
    env = dict(os.environ)

    def log(line: str) -> None:
        print(line, flush=True)

    try:
        if len(argv) != 2:
            raise ValueError("members.py takes exactly the phase")
        last = run(argv[1], env, log)
    except RefusalError as refusal:
        print(refusal_line("workspace", env.get("WORKSPACE", ""), refusal.reason))
        return REFUSED
    except ERRORS as error:
        print(f"failed {error}", file=sys.stderr)
        return FAILED
    if last is not None:
        print(last)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
