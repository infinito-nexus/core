"""Converge Mattermost's system_admin role on the administrator role group.

Environment:
    RBAC_SYNC_CONTAINER_BIN, RBAC_SYNC_CID: how to reach the Mattermost container.
    MATTERMOST_MMCTL: path of ``mmctl`` inside the container.
    RBAC_ADMINISTRATORS: JSON list of the administrator role's members.
    MATTERMOST_RBAC_KEEP: JSON list of usernames that keep ``system_admin``.

Output:
    One ``CHANGED <username> <role>`` line per changed account, else ``UNCHANGED``.
"""

import json
import os
import subprocess

from mattermost_rbac import mattermost_rbac_plan


def mmctl(environ, run, *args):
    """Return the standard output of one ``mmctl --local`` call in the container.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        args: the ``mmctl`` arguments.
    """
    argv = [
        environ["RBAC_SYNC_CONTAINER_BIN"],
        "exec",
        "-i",
        environ["RBAC_SYNC_CID"],
        environ["MATTERMOST_MMCTL"],
        "--local",
        *args,
    ]
    return run(argv, capture_output=True, text=True, check=True).stdout


def main(environ, run=subprocess.run):
    """Promote the members, demote every other human holder, print the result.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
    """
    users = json.loads(
        mmctl(environ, run, "--json", "--suppress-warnings", "user", "list", "--all")
    )
    plan = mattermost_rbac_plan(
        users,
        json.loads(environ["RBAC_ADMINISTRATORS"]),
        json.loads(environ["MATTERMOST_RBAC_KEEP"]),
    )
    lines = []
    if plan["promote"]:
        mmctl(environ, run, "roles", "system_admin", *plan["promote"])
        lines += [f"CHANGED {username} system_admin" for username in plan["promote"]]
    if plan["demote"]:
        mmctl(environ, run, "roles", "member", *plan["demote"])
        lines += [f"CHANGED {username} member" for username in plan["demote"]]
    print("\n".join(lines) if lines else "UNCHANGED")


if __name__ == "__main__":
    main(os.environ)
