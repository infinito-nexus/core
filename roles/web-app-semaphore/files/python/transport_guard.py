from __future__ import annotations

import json
import sys

SCRIPT = "transport_guard.py"
SSH = "ssh"
REFUSED = (
    "ansible_ssh_args",
    "ansible_ssh_common_args",
    "ansible_ssh_extra_args",
    "ansible_scp_extra_args",
    "ansible_sftp_extra_args",
    "ansible_ssh_executable",
    "ansible_scp_executable",
    "ansible_sftp_executable",
    "ansible_ssh_pkcs11_provider",
)
CONNECTION = "ansible_connection"


def findings(host_vars):
    """Args:
    host_vars: the variables of the target host as ``ansible-inventory --host``
        prints them.

    Returns:
        Every host variable that would take the task's connection away from
        the ``ANSIBLE_SSH_ARGS`` it pins, with the pinned known-hosts line and
        ``StrictHostKeyChecking=yes``, or run something on the runner: an
        ``ansible_ssh_args``, which replaces the pin since inventory variables
        outrank the environment; the common and extra arguments of ssh, scp
        and sftp, whose ``ProxyCommand``, ``LocalCommand``,
        ``KnownHostsCommand``, ``-F`` or forwardings run a command on the
        runner or open its network whatever the pin holds; the ssh, scp and
        sftp executables; a PKCS#11 provider, a library the runner loads; and
        an ``ansible_connection`` other than ``ssh``.
    """
    if not isinstance(host_vars, dict):
        return ["the host variables are no mapping"]
    found = [f"{name} is set" for name in REFUSED if name in host_vars]
    connection = host_vars.get(CONNECTION, SSH)
    if connection != SSH:
        found.append(f"{CONNECTION} is not {SSH}")
    return found


def main(stdin, stderr):
    """Args:
    stdin: the host variables as JSON.
    stderr: where a refusal goes.

    Returns:
        0 when the pinned transport holds, 1 on a refusal.
    """
    try:
        found = findings(json.load(stdin))
    except ValueError as error:
        found = [f"the host variables are no JSON: {error}"]
    if found:
        print(
            f"{SCRIPT}: the inventory overrides the pinned SSH transport: "
            + "; ".join(found),
            file=stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.stdin, sys.stderr))
