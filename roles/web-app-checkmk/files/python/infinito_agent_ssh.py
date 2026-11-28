#!/usr/bin/env python3
"""Args:
    argv[1]: the Checkmk host name.
    argv[2]: the address Checkmk monitors it at.

Environment:
    OMD_ROOT: the site directory, whose .ssh/infinito_monitoring is the
        private half of the platform monitoring key.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOST_NAME = re.compile(r"ws-[0-9a-f-]{36}-[A-Za-z0-9_.-]{1,253}")
LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
HOSTNAME = re.compile(rf"(?=.{{1,253}}$){LABEL}(?:\.{LABEL})*")
SSH_USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
PORT = re.compile(r"[1-9][0-9]{0,4}")
KEY_TYPE = re.compile(r"ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)")
KEY = re.compile(r"[A-Za-z0-9+/]+={0,3}")
LABELS = {
    "user": ("infinito/ssh_user", SSH_USER),
    "port": ("infinito/ssh_port", PORT),
    "key_type": ("infinito/ssh_host_key_type", KEY_TYPE),
    "key": ("infinito/ssh_host_key", KEY),
}
WORKSPACE = re.compile(
    r"ws-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
WORKSPACE_LABEL = "workspace"
SECTION = b"<<<infinito_workspace>>>"
TIMEOUT = 60
KEY_FILE = "infinito_monitoring"


class RefusedError(Exception):
    pass


def checked_name(value):
    if "\n" in value or not HOST_NAME.fullmatch(value):
        raise RefusedError("the host name is no workspace host")
    return value


def bound_workspace(name, labels):
    """Args:
    name: the checked Checkmk host name.
    labels: the host labels Livestatus reports.

    Returns:
        The ``workspace`` label ``monitoring apply`` sets from its own
        workspace, never from the inventory, which also has to open ``name``.
    """
    value = labels.get(WORKSPACE_LABEL)
    if (
        not isinstance(value, str)
        or not WORKSPACE.fullmatch(value)
        or not name.startswith(f"{value}-")
    ):
        raise RefusedError(
            f"the label {WORKSPACE_LABEL} is missing, malformed or not the host's own"
        )
    return value


def agent_output(stdout, workspace):
    """Args:
    stdout: what the host's forced command printed.
    workspace: the workspace of the Checkmk host.

    Returns:
        The agent output after the ``SECTION`` the host's own deploy writes
        into its ``authorized_keys`` line, which names its workspace.

    Raises:
        RefusedError: the section is missing or names another workspace.
    """
    section, _, rest = (stdout or b"").partition(b"\n")
    named, _, rest = rest.partition(b"\n")
    if section != SECTION:
        raise RefusedError(
            "the host printed no workspace section: its agent line is no "
            "workspace-bound line of the platform, deploy the host again"
        )
    if named != workspace.encode():
        raise RefusedError(
            f"the host's agent line was installed for another workspace than {workspace}"
        )
    return rest


def checked_address(value):
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if "\n" in value or not HOSTNAME.fullmatch(value):
            raise RefusedError(
                "the host address is neither an IP address nor a hostname"
            ) from None
        return value


def access(labels):
    """Args:
    labels: the host labels Livestatus reports.

    Returns:
        ``user``, ``port``, ``key_type`` and ``key``, each checked.
    """
    found = {}
    for field, (label, pattern) in LABELS.items():
        value = labels.get(label)
        if not isinstance(value, str) or "\n" in value or not pattern.fullmatch(value):
            raise RefusedError(f"the label {label} is missing or malformed")
        found[field] = value
    if int(found["port"]) > 65535:
        raise RefusedError("the label infinito/ssh_port is no TCP port")
    return found


def command(key_file, address, ssh):
    """Returns:
    The ssh argv: publickey with the platform key only, the host key pinned
    through ``KnownHostsCommand`` and every known_hosts file switched off.
    """
    return [
        "ssh",
        "-T",
        "-F",
        "/dev/null",
        "-i",
        key_file,
        "-p",
        ssh["port"],
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "PreferredAuthentications=publickey",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "UpdateHostKeys=no",
        "-o",
        f"KnownHostsCommand=/bin/echo %H {ssh['key_type']} {ssh['key']}",
        "-o",
        "ConnectTimeout=10",
        "-l",
        ssh["user"],
        address,
    ]


# Real I/O by default: __main__ passes none, tests pass stand-ins.
def labels_of(name, query=subprocess.run):
    result = query(
        ["lq"],
        input=f"GET hosts\nColumns: labels\nFilter: name = {name}\nOutputFormat: json\n\n",
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=False,
    )
    rows = json.loads(result.stdout) if result.stdout else []
    if len(rows) != 1:
        raise RefusedError(f"Livestatus knows {len(rows)} hosts named {name}")
    return rows[0][0]


# Real I/O by default: __main__ passes none, tests pass stand-ins.
def main(argv, env, query=subprocess.run, run=subprocess.run, out=None):
    if len(argv) != 2:
        sys.stderr.write("infinito_agent_ssh: expects the host name and address\n")
        return 2
    name, address = argv
    try:
        labels = labels_of(checked_name(name), query)
        workspace = bound_workspace(name, labels)
        argv_ssh = command(
            str(Path(env["OMD_ROOT"]) / ".ssh" / KEY_FILE),
            checked_address(address),
            access(labels),
        )
    except RefusedError as error:
        sys.stderr.write(f"infinito_agent_ssh: {error}\n")
        return 2
    result = run(argv_ssh, check=False, timeout=TIMEOUT, stdout=subprocess.PIPE)
    try:
        output = agent_output(result.stdout, workspace)
    except RefusedError as error:
        sys.stderr.write(f"infinito_agent_ssh: {error}\n")
        return result.returncode or 2
    (out or sys.stdout.buffer).write(output)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ))
