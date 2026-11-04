"""Converge Mailu's global administrators and domain managers on the role groups.

Environment:
    RBAC_SYNC_CONTAINER_BIN, RBAC_SYNC_CID: how to reach the Mailu admin container.
    MAILU_API_BEARER: the admin API token; it reaches the container by name only.
    MAILU_API_BASE_URL: the admin API base URL inside the container.
    MAILU_DOMAIN: the mail domain whose managers are converged.
    MAILU_CURL_READ, MAILU_CURL_WRITE: the curl base commands of reads and writes.
    MAILU_RBAC_KEEP: JSON list of usernames that keep ``global_admin``.
    RBAC_ADMINISTRATORS: JSON list of the administrator role's usernames.
    RBAC_DOMAIN_MANAGERS: JSON list of the domain-manager role's usernames.

Output:
    One ``CHANGED <method> <mailbox> <path>`` line per request, else ``UNCHANGED``.
"""

import json
import os
import subprocess

from mailu_rbac import mailu_rbac_mailboxes, mailu_rbac_plan

AUTHORIZATION = '-H "Authorization: Bearer $MAILU_API_BEARER"'


def admin_shell(environ, run, script, args, body):
    """Return the standard output of one ``sh -c`` call in the admin container.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        script: the ``sh -c`` script; ``$MAILU_API_BEARER`` expands inside the container.
        args: the positional parameters of the script.
        body: the standard input of the call.
    """
    argv = [
        environ["RBAC_SYNC_CONTAINER_BIN"],
        "exec",
        "-i",
        "-e",
        "MAILU_API_BEARER",
        environ["RBAC_SYNC_CID"],
        "sh",
        "-c",
        script,
        "_",
        *args,
    ]
    return run(argv, input=body, capture_output=True, text=True, check=True).stdout


def main(environ, run=subprocess.run):
    """Promote the members, demote every other holder, print the result.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
    """
    base = environ["MAILU_API_BASE_URL"]
    domain = environ["MAILU_DOMAIN"]
    read = f'{environ["MAILU_CURL_READ"]} -S --fail {AUTHORIZATION} "$1"'
    write = (
        f'{environ["MAILU_CURL_WRITE"]} -S -o /dev/null -w "%{{http_code}}" -X "$1" '
        f'{AUTHORIZATION} -H "Content-Type: application/json" --data-binary @- "$2"'
    )
    users = json.loads(admin_shell(environ, run, read, [f"{base}/user"], ""))
    managers = json.loads(
        admin_shell(environ, run, read, [f"{base}/domain/{domain}/manager"], "")
    )["managers"]
    requests = mailu_rbac_plan(
        users,
        managers,
        mailu_rbac_mailboxes(
            json.loads(environ["MAILU_RBAC_KEEP"])
            + json.loads(environ["RBAC_ADMINISTRATORS"]),
            domain,
        ),
        mailu_rbac_mailboxes(json.loads(environ["RBAC_DOMAIN_MANAGERS"]), domain),
        domain,
    )
    for request in requests:
        url = (
            base
            + request["path"]
            + (request["email"] if request["path"].endswith("/") else "")
        )
        body = (
            {**request["body"], "user_email": request["email"]}
            if request["method"] == "POST"
            else request["body"]
        )
        status = admin_shell(
            environ, run, write, [request["method"], url], json.dumps(body)
        )
        if status.strip() != "200":
            raise SystemExit(
                f"{request['method']} {url} answered HTTP {status.strip()}"
            )
        print(
            f"CHANGED {request['method']} {request['email']} {request['path']}",
            flush=True,
        )
    if not requests:
        print("UNCHANGED")


if __name__ == "__main__":
    main(os.environ)
