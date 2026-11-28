"""Hand the pre-provisioned accounts to the OIDC plugin, then converge every account's role.

The hook runs on the node of the database container and reaches only that
container. tasks/rbac/provision.yml creates the missing accounts through the
PeerTube API at deploy time, inside PeerTube's network namespace.

Files:
    link-preprovisioned-accounts.sql, reconcile-roles.sql:
        beside this script, run through psql in the database container.

Environment:
    RBAC_SYNC_CONTAINER_BIN, RBAC_SYNC_CID: how to reach the database container.
    PGPASSWORD: password of the PeerTube database user.
    PEERTUBE_DB_USER, PEERTUBE_DB_NAME: the PeerTube database user and database.
    PEERTUBE_ROOT_USERNAME: the local root account, never handed to the plugin.
    PEERTUBE_RBAC_ROLE_IDS: JSON ``{role: PeerTube role id}`` of administrator and moderator.
    PEERTUBE_OIDC_PLUGIN: name of the OIDC plugin the accounts belong to.
    RBAC_MEMBERS: JSON ``{role: [{username, email, name}]}`` of administrator and moderator.

Output:
    One ``CHANGED <username> linked`` line per account handed to the plugin, then
    the lines of reconcile-roles.sql, or ``UNCHANGED``. An account is handed over
    when one role group member carries both its username and its e-mail and
    nobody has logged into it or holds a token of it, so a deploy that stopped
    between creating and linking heals on the next run, while a self-registered
    account someone uses is never taken over. reconcile-roles.sql also deletes
    every password-grant token (``authName`` NULL) of a plugin account, since
    PeerTube refuses password logins to those: such a token can only stem from
    a grant that read the account just before the link committed, and the link
    statement's own snapshot cannot see it. A second statement of
    reconcile-roles.sql then sets ``noWelcomeModal`` on every plugin account
    that holds the Administrator role, printing ``CHANGED <username> setup
    wizard dismissed``.
"""

import os
import subprocess
from pathlib import Path


def psql(environ, run, script, names):
    """Return the output of one SQL file run through psql in the database container.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        script: name of the SQL file beside this script.
        names: variables the SQL reads, forwarded into the container by name.
    """
    argv = [environ["RBAC_SYNC_CONTAINER_BIN"], "exec", "-i", "-e", "PGPASSWORD"]
    for name in names:
        argv += ["-e", name]
    argv += [
        environ["RBAC_SYNC_CID"],
        "psql",
        "-U",
        environ["PEERTUBE_DB_USER"],
        "-d",
        environ["PEERTUBE_DB_NAME"],
        "-v",
        "ON_ERROR_STOP=1",
        "-qtA",
    ]
    result = run(
        argv,
        input=Path(script).read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        check=True,
        env=environ,
    )
    return result.stdout


def main(environ, run=subprocess.run):
    """Link the role group members' accounts to the OIDC plugin and converge the roles.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
    """
    linked = psql(
        environ,
        run,
        "link-preprovisioned-accounts.sql",
        ["PEERTUBE_OIDC_PLUGIN", "PEERTUBE_ROOT_USERNAME", "RBAC_MEMBERS"],
    ).splitlines()
    lines = [f"CHANGED {username} linked" for username in linked if username]
    lines += psql(
        environ,
        run,
        "reconcile-roles.sql",
        ["RBAC_MEMBERS", "PEERTUBE_RBAC_ROLE_IDS", "PEERTUBE_OIDC_PLUGIN"],
    ).splitlines()
    changes = [line for line in lines if line and line != "UNCHANGED"]
    print("\n".join(changes) if changes else "UNCHANGED")


if __name__ == "__main__":
    main(os.environ)
