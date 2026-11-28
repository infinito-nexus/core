"""Converge Pixelfed's admin flag on the administrator role group.

Runs as a host hook of ``sys-ctl-mtn-rbac-sync`` against the database
container: Pixelfed's OIDC login reads no groups claim, and the MariaDB client
reads no variable from the environment, so the plan is computed on the node
and only account ids reach the SQL text.

Environment:
    RBAC_SYNC_CONTAINER_BIN, RBAC_SYNC_CID: how to reach the database container.
    MYSQL_PWD: password of the Pixelfed database user, forwarded by name.
    PIXELFED_DB_USER: the Pixelfed database user.
    PIXELFED_DB_NAME: the Pixelfed database.
    RBAC_ADMINISTRATORS: JSON list of the administrator role's members.
    PIXELFED_RBAC_KEPT: JSON list of usernames whose flag the run never changes.

Output:
    One ``CHANGED <username> admin=<true|false>`` line per changed account, else ``UNCHANGED``.
"""

import json
import os
import subprocess
import sys

SELECT_USERS = (
    "SELECT JSON_OBJECT('id', id, 'username', username, 'email', email, 'is_admin', is_admin)"
    " FROM users ORDER BY username;"
)
SELECT_MAPPINGS = "SELECT JSON_OBJECT('user_id', user_id, 'oidc_id', oidc_id) FROM user_oidc_mappings;"


def mariadb(environ, run, sql):
    """Return the output lines of one ``mariadb`` call in the database container.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        sql: the statements, sent on standard input.
    """
    argv = [
        environ["RBAC_SYNC_CONTAINER_BIN"],
        "exec",
        "-i",
        "-e",
        "MYSQL_PWD",
        environ["RBAC_SYNC_CID"],
        "mariadb",
        "-u",
        environ["PIXELFED_DB_USER"],
        "-D",
        environ["PIXELFED_DB_NAME"],
        "--batch",
        "--raw",
        "--skip-column-names",
    ]
    result = run(argv, input=sql, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result.stdout.splitlines()


def plan(users, mappings, administrators, kept):
    """Split the accounts into those to promote and those to demote.

    Args:
        users: ``{id, username, email, is_admin}`` per Pixelfed account.
        mappings: ``{user_id, oidc_id}`` per OIDC mapping.
        administrators: ``[{username, email, name}]`` of the administrator role.
        kept: usernames whose flag is never changed.

    Returns:
        ``{"promote": [...], "demote": [...]}`` as accounts. An account matches
        a member by username, e-mail or the subject of its OIDC mapping, all
        case-insensitive.
    """
    usernames = {member["username"].lower() for member in administrators}
    emails = {member["email"].lower() for member in administrators if member["email"]}
    mapped = {
        mapping["user_id"]
        for mapping in mappings
        if (mapping["oidc_id"] or "").lower() in usernames
    }
    skipped = {username.lower() for username in kept}
    promote = []
    demote = []
    for user in users:
        username = user["username"].lower()
        if username in skipped:
            continue
        member = (
            username in usernames
            or (user["email"] or "").lower() in emails
            or user["id"] in mapped
        )
        if member and not user["is_admin"]:
            promote.append(user)
        if user["is_admin"] and not member:
            demote.append(user)
    return {"promote": promote, "demote": demote}


def set_flag(flag, accounts):
    """Return the statement that sets the admin flag of the accounts.

    Args:
        flag: 1 to promote, 0 to demote.
        accounts: the accounts, each with an integer ``id``.
    """
    ids = ", ".join(str(int(account["id"])) for account in accounts)
    return f"UPDATE users SET is_admin = {int(flag)} WHERE id IN ({ids});"  # noqa: S608 only integers cast above reach the text


def main(environ, run):
    """Promote the members, demote every other flagged account, print the result.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
    """
    users = [json.loads(line) for line in mariadb(environ, run, SELECT_USERS)]
    mappings = [json.loads(line) for line in mariadb(environ, run, SELECT_MAPPINGS)]
    result = plan(
        users,
        mappings,
        json.loads(environ["RBAC_ADMINISTRATORS"]),
        json.loads(environ["PIXELFED_RBAC_KEPT"]),
    )
    statements = [
        set_flag(flag, accounts)
        for flag, accounts in ((1, result["promote"]), (0, result["demote"]))
        if accounts
    ]
    if statements:
        mariadb(environ, run, "\n".join(statements))
    lines = [f"CHANGED {user['username']} admin=true" for user in result["promote"]]
    lines += [f"CHANGED {user['username']} admin=false" for user in result["demote"]]
    print("\n".join(lines) if lines else "UNCHANGED")


if __name__ == "__main__":
    main(os.environ, subprocess.run)
