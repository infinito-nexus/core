from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

# nocheck: project-root-import  standalone helper the runner runs with python3 -I from the core tree; no package container to import PROJECT_ROOT from
CORE = Path(__file__).resolve().parents[4]

SCRIPT = "lockout_guard.py"
ROOT = "root"
LOGIN_VAR = "ansible_user"
PERMIT_VAR = "SYS_SVC_SSHD_PERMIT_ROOT_LOGIN"
KEY_LOGIN = ("prohibit-password", "yes")
LOGIN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
KEY_TYPE = re.compile(r"^(ssh-|ecdsa-sha2-|sk-)[A-Za-z0-9@.-]+$")
KEYWORD = re.compile(r"^[a-z-]{1,32}$")


class LockoutError(Exception):
    pass


def key_blobs(lines):
    """Args:
    lines: OpenSSH public key lines, ``authorized_keys`` entries with options
        and comments included.

    Returns:
        The ``(type, base64 blob)`` of every line that holds a key.
    """
    blobs = set()
    for line in lines:
        tokens = line.split() if isinstance(line, str) else []
        for index, token in enumerate(tokens[:-1]):
            if KEY_TYPE.match(token):
                blobs.add((token, tokens[index + 1]))
                break
    return blobs


def fingerprint(blob):
    """Args:
    blob: the ``(type, base64 blob)`` of a public key.

    Returns:
        Its ``SHA256:`` fingerprint as ``ssh-keygen -l`` prints it.
    """
    try:
        raw = base64.b64decode(blob[1], validate=True)
    except binascii.Error:
        raw = blob[1].encode()
    digest = base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
    return f"{blob[0]} SHA256:{digest}"


def sshd_default():
    """Returns:
    ``SYS_SVC_SSHD_PERMIT_ROOT_LOGIN`` as the defaults of ``sys-svc-sshd`` set it.
    """
    if str(CORE) not in sys.path:
        sys.path.insert(0, str(CORE))
    from utils.cache.yaml import load_yaml_any
    from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN

    defaults = CORE / "roles" / "sys-svc-sshd" / ROLE_FILE_DEFAULTS_MAIN
    return load_yaml_any(str(defaults)).get(PERMIT_VAR)


def check(host_vars, agent_keys, permit_default):
    """Args:
    host_vars: the variables of the target host as ``ansible-inventory --host``
        prints them.
    agent_keys: the ``ssh-add -L`` lines of the task agent.
    permit_default: the ``sys-svc-sshd`` default of ``PERMIT_VAR``.

    Raises:
        LockoutError: the run would end with no key login for its login user: the
            host names no login user, the agent holds no key, a key of the
            agent is not among the login user's ``authorized_keys``, or the
            login user is root and ``PermitRootLogin`` refuses keys. The
            message names a fingerprint or a setting, never a key.
    """
    if not isinstance(host_vars, dict):
        raise LockoutError("the host variables are no mapping")
    login = host_vars.get(LOGIN_VAR)
    if not isinstance(login, str) or not LOGIN.match(login):
        raise LockoutError(f"the host names no valid {LOGIN_VAR}")
    agent = key_blobs(agent_keys)
    if not agent:
        raise LockoutError("the task agent holds no key")
    users = host_vars.get("users")
    entry = users.get(login) if isinstance(users, dict) else None
    authorized = entry.get("authorized_keys") if isinstance(entry, dict) else None
    if not isinstance(authorized, list):
        raise LockoutError(f"users.{login}.authorized_keys is no list in the inventory")
    missing = sorted(agent - key_blobs(authorized))
    if missing:
        raise LockoutError(
            f"users.{login}.authorized_keys lacks {', '.join(map(fingerprint, missing))}"
            ", the key this task logs in with"
        )
    if login != ROOT:
        return
    permit = host_vars.get(PERMIT_VAR, permit_default)
    if permit not in KEY_LOGIN:
        shown = (
            permit
            if isinstance(permit, str) and KEYWORD.match(permit)
            else "no PermitRootLogin keyword"
        )
        raise LockoutError(
            f"{PERMIT_VAR} is {shown} while the login user is {ROOT}; "
            f"key login needs {' or '.join(KEY_LOGIN)}"
        )


def main(stdin, stderr):
    """Args:
    stdin: the host variables as JSON.
    stderr: where a refusal goes.

    Returns:
        0 when the run keeps its key login, 1 on a refusal.
    """
    try:
        listed = subprocess.run(
            ["ssh-add", "-L"], capture_output=True, text=True, check=False
        )
        check(json.load(stdin), listed.stdout.splitlines(), sshd_default())
    except (LockoutError, ValueError, OSError) as error:
        print(f"{SCRIPT}: {error}", file=stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.stdin, sys.stderr))
