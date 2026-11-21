from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from release_host import COUNTS

SCRIPT = "proof_of_release.py"
PROOF_SSH_ARGS = (
    "-o ControlMaster=no -o ControlPath=none -o BatchMode=yes -o IdentitiesOnly=yes "
    "-o StrictHostKeyChecking=yes -o GlobalKnownHostsFile=/dev/null "
    "-o PreferredAuthentications=publickey -o PasswordAuthentication=no "
    "-o KbdInteractiveAuthentication=no"
)
DENIED = "Permission denied ("


def load_result(path):
    """Args:
    path: the file ``ansible --tree`` wrote for the host, None for none.

    Returns:
        The task result it holds, an empty mapping when it holds none, None
        without a path.
    """
    if path is None:
        return None
    try:
        with Path(path).open(encoding="utf-8") as stream:
            result = json.load(stream)
    except (OSError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def denied(result):
    """Args:
    result: a task result.

    Returns:
        Whether the host refused the SSH login.
    """
    return bool(result.get("unreachable")) and DENIED in str(result.get("msg", ""))


def last_object(result):
    """Args:
    result: a task result.

    Returns:
        The JSON object of the last stdout line, None without one.
    """
    lines = str(result.get("stdout") or "").splitlines()
    try:
        body = json.loads(lines[-1]) if lines else None
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def counted(body):
    """Args:
    body: the last stdout object of ``apply``.

    Returns:
        Whether it is the result line ``release`` prints.
    """
    if body is None or set(body) != {"kept", "removed"}:
        return False
    removed = body["removed"]
    if not isinstance(removed, dict) or set(removed) != set(COUNTS):
        return False
    return all(
        type(number) is int and number >= 0
        for number in (body["kept"], *removed.values())
    )


def proof_vars(workdir, user):
    """Args:
    workdir: the task directory holding ``agent.pub`` and ``known_hosts``.
    user: the account the proof logs in as, None for the inventory's own.

    Returns:
        The extra vars of the proof login. Extra vars outrank every inventory
        variable, so no ``ansible_ssh_args``, ``ansible_ssh_private_key_file``,
        common or extra ssh args, password or connection the inventory sets
        can offer another identity, reuse a master or loosen the pinned host
        key.
    """
    directory = Path(workdir)
    key = str(directory / "agent.pub")
    known = shlex.quote(str(directory / "known_hosts"))
    values = {
        "ansible_connection": "ssh",
        "ansible_ssh_executable": "ssh",
        "ansible_private_key_file": key,
        "ansible_ssh_private_key_file": key,
        "ansible_ssh_args": f"{PROOF_SSH_ARGS} -o UserKnownHostsFile={known}",
        "ansible_ssh_common_args": "",
        "ansible_ssh_extra_args": "",
        "ansible_password": "",
        "ansible_ssh_pass": "",
        "ansible_ssh_password": "",
    }
    if user is not None:
        values["ansible_user"] = user
    return values


def report(host, release_result, proofs):
    """Args:
    host: the target host.
    release_result: the task result of ``apply``.
    proofs: the task results of the fresh logins after it, empty before
        they ran.

    Returns:
        ``(exit code, last stdout line)``: 0 with no line while the proofs
        are due, 0 with the release once the host refuses the task agent key
        on every login, 2 on a refusal and 1 on a failure, each with a line
        naming why.
    """

    def end(**reason):
        return {"host": host, "released": False, **reason}

    if denied(release_result):
        return 2, end(
            refused=f"{host} refuses the task agent key already, "
            "so it is released or never let this task in"
        )
    body = last_object(release_result)
    rc = release_result.get("rc")
    if rc == 2 and body and set(body) == {"refused"}:
        return 2, end(refused=str(body["refused"]))
    if rc != 0 or release_result.get("failed") or not counted(body):
        return 1, end(failed=f"the release on {host} ended without its result")
    if not proofs:
        return 0, None
    if any(proof and not proof.get("unreachable") for proof in proofs):
        return 1, end(
            failed=f"the task agent key still logs in to {host} after the release"
        )
    if not all(denied(proof) for proof in proofs):
        return 1, end(
            failed=f"a fresh login to {host} was neither refused nor let in, "
            "so the release is unproven"
        )
    return 0, {"host": host, "released": True, **body}


def parser():
    """Returns:
    The command line of ``report`` and ``proof-vars``, run in the task.
    """
    command = argparse.ArgumentParser(prog=SCRIPT)
    actions = command.add_subparsers(dest="action", required=True)
    task = actions.add_parser("report")
    task.add_argument("host")
    task.add_argument("release")
    task.add_argument("proof", nargs="*")
    login = actions.add_parser("proof-vars")
    login.add_argument("workdir")
    login.add_argument("--user")
    return command


def main(argv, stdout):
    """Args:
    argv: the command line without the program name.
    stdout: where the result line goes.

    Returns:
        The exit code: 0 done, 1 failed, 2 refused.
    """
    arguments = parser().parse_args(argv)
    if arguments.action == "proof-vars":
        print(json.dumps(proof_vars(arguments.workdir, arguments.user)), file=stdout)
        return 0
    code, line = report(
        arguments.host,
        load_result(arguments.release),
        [load_result(path) for path in arguments.proof],
    )
    if line is not None:
        print(json.dumps(line, sort_keys=True), file=stdout)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdout))
