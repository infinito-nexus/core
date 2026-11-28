from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from release.host import BASE_COUNTS, COUNTS, SHARE_COUNTS

SCRIPT = "proof_of_release.py"
PROOF_SSH_ARGS = (
    "-o ControlMaster=no -o ControlPath=none -o BatchMode=yes -o IdentitiesOnly=yes "
    "-o StrictHostKeyChecking=yes -o GlobalKnownHostsFile=/dev/null "
    "-o PreferredAuthentications=publickey -o PasswordAuthentication=no "
    "-o KbdInteractiveAuthentication=no"
)
DENIED = "Permission denied ("
REFUSED_LOGIN = 3


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


def tallied(removed, names):
    """Args:
    removed: the ``removed`` value of a result line.
    names: the counts it must hold.

    Returns:
        Whether it maps exactly ``names`` to non-negative integers.
    """
    return (
        isinstance(removed, dict)
        and set(removed) == set(names)
        and all(type(number) is int and number >= 0 for number in removed.values())
    )


def counted(body, names):
    """Args:
    body: the last stdout object of ``apply``.
    names: the counts its ``removed`` holds, ``COUNTS`` with the monitoring
        share, ``BASE_COUNTS`` without it.

    Returns:
        Whether it is the result line ``release`` prints.
    """
    if body is None or set(body) != {"kept", "removed"}:
        return False
    kept = body["kept"]
    return type(kept) is int and kept >= 0 and tallied(body["removed"], names)


def shared(body):
    """Args:
    body: the last stdout object of ``share``.

    Returns:
        Whether it is the share line ``release`` prints.
    """
    return (
        body is not None
        and set(body) == {"removed"}
        and tallied(body["removed"], SHARE_COUNTS)
    )


def ended(host, **reason):
    """Args:
    host: the target host.
    reason: the ``refused`` or ``failed`` field.

    Returns:
        The line of a release that did not happen.
    """
    return {"host": host, "released": False, **reason}


def outcome(host, result, valid):
    """Args:
    host: the target host.
    result: the task result of ``share`` or ``apply``.
    valid: the check of its result line.

    Returns:
        ``(exit code, last stdout line)`` of a refusal or a failure, None
        when the helper ended with a valid result line.
    """
    body = last_object(result)
    rc = result.get("rc")
    if rc == 2 and body and set(body) == {"refused"}:
        return 2, ended(host, refused=str(body["refused"]))
    if rc == 1 and body and set(body) == {"failed"}:
        return 1, ended(host, failed=f"the release on {host} failed: {body['failed']}")
    if rc != 0 or result.get("failed") or not valid(body):
        return 1, ended(host, failed=f"the release on {host} ended without its result")
    return None


def share(host, result):
    """Args:
    host: the target host.
    result: the task result of ``share``.

    Returns:
        ``(exit code, line)``: 0 with the share line once the host proved
        its monitoring share gone on disk, ``REFUSED_LOGIN`` with none when
        the host refused the task agent key, which only a release marker
        can explain, 2 on a refusal and 1 on a failure with a line naming
        why.
    """
    if denied(result):
        return REFUSED_LOGIN, None
    return outcome(host, result, shared) or (0, last_object(result))


def check(host, result):
    """Args:
    host: the target host.
    result: the task result of ``check``.

    Returns:
        ``(exit code, line)``: 0 with none once the host would release, or
        refused the task agent key, which the share step judges next; 2 on
        a refusal and 1 on a failure, each with a line naming why.
    """
    if denied(result):
        return 0, None
    return outcome(host, result, lambda body: body == {"checked": True}) or (0, None)


def stopped(host, status, reason):
    """Args:
    host: the target host.
    status: the exit status a step of the task ended it with before any
        result line.
    reason: why it stopped.

    Returns:
        ``(exit code, line)``: 2 with a ``refused`` line for a refusal,
        which every step exiting 2 is, else 1 with a ``failed`` line.
    """
    if status == 2:
        return 2, ended(host, refused=reason)
    return 1, ended(host, failed=reason)


def finish(host, recorded, status, reason):
    """Args:
    host: the target host.
    recorded: the file every result line of the task's helpers went to.
    status: the exit status the task ended with.
    reason: why it stopped, for a task whose helpers printed no line.

    Returns:
        ``(exit code, text)``: the last recorded result line as its helper
        printed it, with 0 for a release, 2 for a refusal and 1 for a
        failure, whatever ``status`` a signal left; without one the line
        of :func:`stopped`.
    """
    try:
        lines = Path(recorded).read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for text in reversed(lines):
        try:
            body = json.loads(text)
        except ValueError:
            continue
        if isinstance(body, dict) and "released" in body:
            if body["released"] is True:
                return 0, text
            return (2 if "refused" in body else 1), text
    code, line = stopped(host, status, reason)
    return code, json.dumps(line, sort_keys=True)


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


def report(host, release_result, proofs, marked=False, share_line=None):
    """Args:
    host: the target host.
    release_result: the task result of ``apply``, or of ``share`` on a
        rerun the host refused.
    proofs: the task results of the fresh logins after it, empty before
        they ran.
    marked: whether ``release/federation.py marked`` found the release
        marker an earlier run wrote once it proved the share gone.
    share_line: the share line of this run, whose counts add to the ones
        of ``apply``.

    Returns:
        ``(exit code, last stdout line)``: 0 with no line while the proofs
        are due, 0 with the release once the host refuses the task agent key
        on every login, 2 on a refusal and 1 on a failure, each with a line
        naming why. A host that refuses the task agent key to the release
        itself counts as released by an earlier run only when ``marked``,
        so a rerun goes on to the OpenBao erase and ends ``{"host",
        "released": true, "already": true}`` once every proof login is
        refused too; without the marker the refusal fails. With neither
        ``marked`` nor ``share_line`` the release ran without the monitoring
        share, as on a platform without monitoring: ``apply`` counts
        ``BASE_COUNTS`` alone and a refused login is a release without its
        result.
    """
    monitored = marked or share_line is not None
    already = monitored and denied(release_result)
    if already and not marked:
        return 1, ended(
            host,
            failed=f"{host} refuses the platform key to the release; restore "
            "access or remove the agent binary, the monitoring key line and the "
            "federation digest file manually",
        )
    if not already:
        names = COUNTS if monitored else BASE_COUNTS
        failure = outcome(host, release_result, lambda body: counted(body, names))
        if failure:
            return failure
        body = last_object(release_result)
        extra = (share_line or {}).get("removed", {})
        body["removed"] = {
            **body["removed"],
            **{name: body["removed"][name] + count for name, count in extra.items()},
        }
    if not proofs:
        return 0, None
    if any(proof and not proof.get("unreachable") for proof in proofs):
        return 1, ended(
            host, failed=f"the task agent key still logs in to {host} after the release"
        )
    if not all(denied(proof) for proof in proofs):
        return 1, ended(
            host,
            failed=f"a fresh login to {host} was neither refused nor let in, "
            "so the release is unproven",
        )
    return 0, {
        "host": host,
        "released": True,
        **({"already": True} if already else body),
    }


def parser():
    """Returns:
    The command line of ``check``, ``share``, ``report``,
    ``finish HOST RECORDED STATUS REASON`` and ``proof-vars``, run in the
    task.
    """
    command = argparse.ArgumentParser(prog=SCRIPT)
    actions = command.add_subparsers(dest="action", required=True)
    checked = actions.add_parser("check")
    checked.add_argument("host")
    checked.add_argument("result")
    removal = actions.add_parser("share")
    removal.add_argument("host")
    removal.add_argument("result")
    removal.add_argument("out")
    task = actions.add_parser("report")
    task.add_argument("--marked", action="store_true")
    task.add_argument("--share")
    task.add_argument("host")
    task.add_argument("release")
    task.add_argument("proof", nargs="*")
    stop = actions.add_parser("finish")
    stop.add_argument("host")
    stop.add_argument("recorded")
    stop.add_argument("status", type=int)
    stop.add_argument("reason")
    login = actions.add_parser("proof-vars")
    login.add_argument("workdir")
    login.add_argument("--user")
    return command


def main(argv, stdout):
    """Args:
    argv: the command line without the program name.
    stdout: where the result line goes.

    Returns:
        The exit code: 0 done, 1 failed, 2 refused, ``REFUSED_LOGIN`` for a
        share the host refused the login to.
    """
    arguments = parser().parse_args(argv)
    if arguments.action == "proof-vars":
        print(json.dumps(proof_vars(arguments.workdir, arguments.user)), file=stdout)
        return 0
    if arguments.action == "finish":
        code, text = finish(
            arguments.host, arguments.recorded, arguments.status, arguments.reason
        )
        print(text, file=stdout)
        return code
    if arguments.action == "check":
        code, line = check(arguments.host, load_result(arguments.result))
    elif arguments.action == "share":
        code, line = share(arguments.host, load_result(arguments.result))
        if code == 0:
            Path(arguments.out).write_text(
                json.dumps(line, sort_keys=True), encoding="utf-8"
            )
            return 0
    else:
        code, line = report(
            arguments.host,
            load_result(arguments.release),
            [load_result(path) for path in arguments.proof],
            arguments.marked,
            load_result(arguments.share),
        )
    if line is not None:
        print(json.dumps(line, sort_keys=True), file=stdout)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdout))
