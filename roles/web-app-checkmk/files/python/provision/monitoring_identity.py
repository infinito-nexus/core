"""Environment:
CHECKMK_API:            REST API base, ending in /check_mk/api/1.0.
CHECKMK_ADMIN_USER:     administrator to act as.
CHECKMK_ADMIN_PASSWORD: that administrator's password.
CHECKMK_SITE:           site id, for the activation call.
MONITORING_USER:        username to converge.
MONITORING_SECRET:      automation secret to pin on it.
MONITORING_FOLDER:      the folder below the root the user manages.
MONITORING_GROUP:       the contact group that carries the folder grant.
MONITORING_ROLE:        the role id of the user.
AGENT_PROGRAM:          the agent datasource program inside the site.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import urllib.error
import urllib.request
from functools import partial

TIMEOUT = 30
TRANSIENT_STATUS = frozenset({0, 409, 429, 502, 503, 504})
BASE_ROLE = "user"
GRANTED = (
    "wato.use",
    "wato.edit",
    "wato.activate",
    "wato.hosts",
    "wato.edit_hosts",
    "wato.manage_hosts",
    "wato.edit_folders",
    "wato.manage_folders",
    "wato.services",
    "wato.rulesets",
    "wato.service_discovery_to_undecided",
    "wato.service_discovery_to_monitored",
    "wato.service_discovery_to_removed",
)
WATO_PERMISSIONS = (
    "wato.use",
    "wato.edit",
    "wato.seeall",
    "wato.activate",
    "wato.activateforeign",
    "wato.discard",
    "wato.discardforeign",
    "wato.auditlog",
    "wato.clear_auditlog",
    "wato.hosts",
    "wato.edit_hosts",
    "wato.parentscan",
    "wato.move_hosts",
    "wato.manage_hosts",
    "wato.rename_hosts",
    "wato.diag_host",
    "wato.clone_hosts",
    "wato.random_hosts",
    "wato.update_dns_cache",
    "wato.services",
    "wato.edit_folders",
    "wato.manage_folders",
    "wato.passwords",
    "wato.edit_all_passwords",
    "wato.edit_all_predefined_conditions",
    "wato.see_all_folders",
    # Exception: stays denied, since Checkmk confines Setup writes to the granted folders only then.
    "wato.all_folders",
    "wato.hosttags",
    "wato.global",
    "wato.rulesets",
    "wato.groups",
    "wato.timeperiods",
    "wato.sites",
    "wato.automation",
    "wato.users",
    "wato.user_migrate",
    "wato.show_last_user_activity",
    "wato.notifications",
    "wato.snapshots",
    "wato.backups",
    "wato.pattern_editor",
    "wato.icons",
    "wato.custom_attributes",
    "wato.download_agents",
    "wato.download_agent_output",
    "wato.set_read_only",
    "wato.analyze_config",
    "wato.diagnostics",
    "wato.add_or_modify_executables",
    "wato.service_discovery_to_undecided",
    "wato.service_discovery_to_monitored",
    "wato.service_discovery_to_ignored",
    "wato.service_discovery_to_removed",
    "wato.check_plugins",
)
DENIED = tuple(name for name in WATO_PERMISSIONS if name not in GRANTED)
AGENT_RULESET = "datasource_programs"
AGENT_RULE = "infinito-nexus monitoring agent over SSH"
# Exception: a value_raw above 4 KiB is not ours and is never parsed; the rule this script writes is one command line of a site path and two macros, well below it.
VALUE_RAW_LIMIT = 4096
UNREADABLE = (SyntaxError, ValueError, TypeError, MemoryError, RecursionError)


class Unredirected(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Exception: urllib re-sends the Authorization header to any redirect target, so a 3xx surfaces as its status instead.
OPENER = urllib.request.build_opener(Unredirected)


class CheckmkError(RuntimeError):
    """
    Args:
        message: what went wrong.
        status: the HTTP status that caused it, 0 without an answer.
    """

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def redacted(raw, secret):
    """Args:
    raw: an answer of the REST API.
    secret: the password the request carried.

    Returns:
        ``raw`` with every copy of ``secret`` replaced, as a site or proxy may
        echo the request, Authorization header included, into its answer.
    """
    return raw.replace(secret.encode(), b"<secret>") if secret else raw


# Never retried: Checkmk locks a user after ten failed logins, so a retried 401
# locks the administrator the deployment needs.
def call(api, user, password, method, path, payload=None, headers=None):
    """Args:
        api: REST API base.
        user: administrator to act as.
        password: that administrator's password.
        method: HTTP method.
        path: path below the API base.
        payload: JSON body, or None.
        headers: extra headers, or None.

    Returns:
        ``(status, parsed body)`` of the call.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(f"{api}{path}", data=data, method=method)  # noqa: S310 fixed internal http origin
    request.add_header("Authorization", f"Bearer {user} {password}")
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with OPENER.open(request, timeout=TIMEOUT) as response:
            body = redacted(response.read(), password)
            return response.status, json.loads(body or b"null")
    except urllib.error.HTTPError as error:
        body = redacted(error.read(), password)
        try:
            return error.code, json.loads(body or b"null")
        except ValueError:
            return error.code, {"detail": body.decode(errors="replace")}
    except OSError as error:
        return 0, {"detail": f"unreachable: {error}"}


def permissions(inherited):
    """Args:
    inherited: every permission the role holds before the write, as Checkmk
        reports it.

    Returns:
        The full permission map of the monitoring role: ``GRANTED`` ``yes``,
        every other known ``wato.*`` permission and every inherited one
        ``no``.
    """
    return {
        **dict.fromkeys(sorted(set(inherited) - set(GRANTED)), "no"),
        **dict.fromkeys(DENIED, "no"),
        **dict.fromkeys(GRANTED, "yes"),
    }


def folder_permissions(group):
    """Args:
    group: the contact group of the monitoring user.

    Returns:
        The ``contactgroups`` attribute that grants the group write access to
        the folder and its subfolders without making it a contact of any host.
    """
    return {
        "groups": [group],
        "use": False,
        "use_for_services": False,
        "recurse_use": False,
        "recurse_perms": True,
    }


def _ids(body):
    return {str(entry.get("id")) for entry in (body or {}).get("value") or []}


def _check(status, body, allowed, what):
    if status not in allowed:
        raise CheckmkError(f"{what} answered {status}: {body}", status)


def ensure_group(api, group):
    status, body = api("GET", "/domain-types/contact_group_config/collections/all")
    _check(status, body, (200,), "listing contact groups")
    if group in _ids(body):
        return False
    status, body = api(
        "POST",
        "/domain-types/contact_group_config/collections/all",
        {"name": group, "alias": "Workspace monitoring"},
    )
    _check(status, body, (200, 201), f"creating contact group {group}")
    return True


def ensure_role(api, role):
    status, body = api("GET", "/domain-types/user_role/collections/all")
    _check(status, body, (200,), "listing user roles")
    created = role not in _ids(body)
    if created:
        status, body = api(
            "POST",
            "/domain-types/user_role/collections/all",
            {
                "role_id": BASE_ROLE,
                "new_role_id": role,
                "new_alias": "Workspace monitoring",
            },
        )
        _check(status, body, (200, 201), f"cloning {BASE_ROLE}")
    status, body = api("GET", f"/objects/user_role/{role}")
    _check(status, body, (200,), f"reading the permissions of {role}")
    inherited = ((body or {}).get("extensions") or {}).get("permissions") or []
    status, body = api(
        "PUT",
        f"/objects/user_role/{role}",
        {"new_permissions": permissions(inherited)},
        {"If-Match": "*"},
    )
    _check(status, body, (200,), f"setting the permissions of {role}")
    return created


def ensure_folder(api, folder, group):
    status, body = api("GET", f"/objects/folder_config/~{folder}")
    attributes = {"contactgroups": folder_permissions(group)}
    if status == 404:
        status, body = api(
            "POST",
            "/domain-types/folder_config/collections/all",
            {"name": folder, "title": folder, "parent": "/", "attributes": attributes},
        )
        _check(status, body, (200, 201), f"creating folder /{folder}")
        return True
    _check(status, body, (200,), f"reading folder /{folder}")
    held = ((body or {}).get("extensions") or {}).get("attributes") or {}
    if held.get("contactgroups") == attributes["contactgroups"]:
        return False
    status, body = api(
        "PUT",
        f"/objects/folder_config/~{folder}",
        {"update_attributes": attributes},
        {"If-Match": "*"},
    )
    _check(status, body, (200,), f"granting /{folder} to {group}")
    return True


def ensure_user(api, user, secret, role, group):
    status, body = api("GET", "/domain-types/user_config/collections/all")
    _check(status, body, (200,), "listing users")
    auth = {
        "auth_type": "automation",
        "secret": secret,
        "store_automation_secret": False,
    }
    if user in _ids(body):
        status, body = api(
            "PUT",
            f"/objects/user_config/{user}",
            {"auth_option": auth, "roles": [role], "contactgroups": [group]},
            {"If-Match": "*"},
        )
        _check(status, body, (200,), f"rotating {user}")
        return False
    status, body = api(
        "POST",
        "/domain-types/user_config/collections/all",
        {
            "username": user,
            "fullname": "Workspace monitoring",
            "roles": [role],
            "contactgroups": [group],
            "auth_option": auth,
            "disable_login": False,
        },
    )
    _check(status, body, (200, 201), f"creating {user}")
    return True


def agent_command(program):
    """Returns:
    The datasource command line of every agent host below ``/workspaces``.
    """
    return f"{program} $HOSTNAME$ $HOSTADDRESS$"


def ensure_agent_rule(api, folder, program):
    """Args:
    api: the administrator's REST API call.
    folder: the folder the rule applies to.
    program: the agent datasource program the rule calls.

    Returns:
        True when the rule had to be created or rewritten.
    """
    status, body = api(
        "GET", f"/domain-types/rule/collections/all?ruleset_name={AGENT_RULESET}"
    )
    _check(status, body, (200,), f"listing {AGENT_RULESET}")
    ours = [
        rule
        for rule in (body or {}).get("value") or []
        if (((rule.get("extensions") or {}).get("properties") or {}).get("description"))
        == AGENT_RULE
    ]
    wanted = agent_command(program)
    payload = {
        "properties": {"description": AGENT_RULE, "disabled": False},
        "value_raw": repr(wanted),
        "conditions": {},
    }
    for extra in ours[1:]:
        status, body = api(
            "DELETE", f"/objects/rule/{extra['id']}", None, {"If-Match": "*"}
        )
        _check(status, body, (200, 204), "deleting a duplicate agent rule")
    if not ours:
        status, body = api(
            "POST",
            "/domain-types/rule/collections/all",
            {"ruleset": AGENT_RULESET, "folder": f"/{folder}", **payload},
        )
        _check(status, body, (200, 201), "creating the agent rule")
        return True
    extensions = ours[0].get("extensions") or {}
    raw = extensions.get("value_raw") or ""
    try:
        held = (
            ast.literal_eval(raw)
            if isinstance(raw, str) and len(raw) <= VALUE_RAW_LIMIT
            else None
        )
    except UNREADABLE:
        held = None
    if (
        held == wanted
        and extensions.get("folder") in (None, f"/{folder}")
        and len(ours) == 1
    ):
        return False
    status, body = api(
        "PUT", f"/objects/rule/{ours[0]['id']}", payload, {"If-Match": "*"}
    )
    _check(status, body, (200,), "rewriting the agent rule")
    return True


def activate(api, site):
    status, body = api(
        "POST",
        "/domain-types/activation_run/actions/activate-changes/invoke",
        {"redirect": False, "sites": [site], "force_foreign_changes": False},
        {"If-Match": "*"},
    )
    _check(status, body, (200, 201, 302, 422), "activating changes")


def provision(api, env):
    """Args:
    api: the REST call of :func:`call`, bound to the site.
    env: MONITORING_USER, MONITORING_SECRET, MONITORING_FOLDER,
        MONITORING_GROUP, MONITORING_ROLE, AGENT_PROGRAM and CHECKMK_SITE.

    Returns:
        True when the group, role, folder, user or agent rule had to be
        created or the folder grant or agent rule rewritten.
    """
    group = env["MONITORING_GROUP"]
    role = env["MONITORING_ROLE"]
    folder = env["MONITORING_FOLDER"]
    changed = ensure_group(api, group)
    changed = ensure_role(api, role) or changed
    changed = ensure_folder(api, folder, group) or changed
    changed = (
        ensure_user(api, env["MONITORING_USER"], env["MONITORING_SECRET"], role, group)
        or changed
    )
    changed = ensure_agent_rule(api, folder, env["AGENT_PROGRAM"]) or changed
    activate(api, env["CHECKMK_SITE"])
    return changed


def main():
    env = os.environ
    api = partial(
        call,
        env["CHECKMK_API"].rstrip("/"),
        env["CHECKMK_ADMIN_USER"],
        env["CHECKMK_ADMIN_PASSWORD"],
    )
    try:
        changed = provision(api, env)
    except CheckmkError as error:
        marker = "PENDING" if error.status in TRANSIENT_STATUS else "REJECTED"
        sys.stderr.write(f"{marker} {error}\n")
        return 1
    print("CHANGED" if changed else "UNCHANGED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
