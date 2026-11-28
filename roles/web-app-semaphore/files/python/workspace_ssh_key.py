from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# nocheck: project-root-import  standalone helper the runner runs with python3 -I from the core tree; no package container to import PROJECT_ROOT from
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from utils.openbao_client import OpenBaoError, login, parse_reference

KEY_VAR = "WORKSPACE_SSH_KEY"
TENANT_MOUNT = "tenant"
SCRIPT = "workspace_ssh_key.py"


def key_reference(host_vars, workspace):
    """Args:
    host_vars: the variables of the target host as ``ansible-inventory --host``
        prints them.
    workspace: the workspace id the task runs for.

    Returns:
        The OpenBao reference ``WORKSPACE_SSH_KEY`` holds; a missing one, a
        plain value and a reference outside ``tenant/ws-<workspace>/`` are
        refused, as are host variables that are no mapping.
    """
    if not isinstance(host_vars, dict):
        raise OpenBaoError("the host variables are no mapping")
    reference = parse_reference(host_vars.get(KEY_VAR), KEY_VAR)
    if reference is None:
        raise OpenBaoError(f"the host holds no OpenBao reference in {KEY_VAR}")
    if reference.mount != TENANT_MOUNT or not reference.path.startswith(
        f"ws-{workspace}/"
    ):
        raise OpenBaoError(
            f"{KEY_VAR} names {reference}, outside {TENANT_MOUNT}/ws-{workspace}/"
        )
    return reference


def main(stdin, stdout, env):
    """Args:
    stdin: the host variables as JSON.
    stdout: where the private key goes, the pipe into ``ssh-add -``.
    env: the task environment: ``WORKSPACE`` and the OpenBao login of
        ``utils.openbao_client.login``.

    Returns:
        0 once the key is written, 1 on a refusal, which names the reference
        and never a value.
    """
    try:
        reference = key_reference(json.load(stdin), env.get("WORKSPACE", ""))
        key = login(env).read(reference)
    except (OpenBaoError, ValueError) as error:
        print(f"{SCRIPT}: {error}", file=sys.stderr)
        return 1
    if not isinstance(key, str) or not key.strip():
        print(f"{SCRIPT}: {reference} holds no private key", file=sys.stderr)
        return 1
    stdout.write(key if key.endswith("\n") else f"{key}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.stdin, sys.stdout, os.environ))
