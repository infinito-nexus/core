"""Converge the Mobilizon role of every Keycloak account on the role groups.

Environment:
    RBAC_SYNC_CONTAINER_BIN, RBAC_SYNC_CID: how to reach the Mobilizon container.
    MOBILIZON_CLI: path of the release command inside the container.
    RBAC_ADMINISTRATORS: JSON list of the administrator role's member e-mails.
    RBAC_MODERATORS: JSON list of the moderator role's member e-mails.
    MOBILIZON_RBAC_BOOTSTRAP: e-mail of the platform administrator, never changed.
    MOBILIZON_RBAC_PROVIDER: login provider of the Keycloak accounts.

Output:
    One ``CHANGED <email> <change>`` line per created or changed account, else ``UNCHANGED``.
"""

import json
import os
import subprocess
from pathlib import Path

PROGRAM = "rbac.exs"
DONE = "MOBILIZON_RBAC=done"


def payload(environ):
    """Return the standard input of ``rbac.exs``; members without an e-mail are dropped.

    Args:
        environ: the process environment.
    """
    return {
        "administrators": [
            email for email in json.loads(environ["RBAC_ADMINISTRATORS"]) if email
        ],
        "moderators": [
            email for email in json.loads(environ["RBAC_MODERATORS"]) if email
        ],
        "bootstrap": environ["MOBILIZON_RBAC_BOOTSTRAP"],
        "provider": environ["MOBILIZON_RBAC_PROVIDER"],
    }


def main(environ, run):
    """Run ``rbac.exs`` through ``mobilizon rpc`` and print the changes it made.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
    """
    program = Path(__file__).with_name(PROGRAM).read_text(encoding="utf-8")
    argv = [
        environ["RBAC_SYNC_CONTAINER_BIN"],
        "exec",
        "-i",
        environ["RBAC_SYNC_CID"],
        environ["MOBILIZON_CLI"],
        "rpc",
        program,
    ]
    result = run(
        argv,
        input=json.dumps(payload(environ)),
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    )
    lines = result.stdout.splitlines()
    if not lines or lines[-1] != DONE:
        raise SystemExit(f"mobilizon rpc ended without {DONE}")
    changes = lines[:-1]
    print("\n".join(changes) if changes else "UNCHANGED")


if __name__ == "__main__":
    main(os.environ, subprocess.run)
