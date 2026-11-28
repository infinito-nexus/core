"""Run every registered RBAC hook against the current members of its role groups.

Once the deploy applied the mailbox layout and wrote ``mailbox.json``, a run
without ``--only`` first gives every account without a primary address its
mailbox address.

Args:
    --directory: the directory that holds ``config.json``, ``hooks/`` and,
        under the applied mailbox layout, ``mailbox.json``.
    --only: run only the hook of this application.
    --members-file: JSON ``{role: [{username, email, name, uuid}]}`` used instead of
        a directory lookup, each member with an ``attributes`` map when the hook
        declares attributes; requires ``--only``, and a missing container is
        then an error rather than a skip.
    --remote-directory: OpenLDAP runs on another node, so a missing socket is
        one SKIPPED line instead of a failure. The node's own unit carries it,
        because swarm nodes share ``--directory`` over NFS and every node
        would overwrite a per-node value in ``config.json``.

Output:
    Every line a hook prints, prefixed with its application id, and every
    mailbox address set, prefixed with ``[mailbox]``; exit code 1 when any
    hook or address failed.
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from backup_maintenance import active
from hook_runner import run_hook, unchanged_since
from ldap_client import Connection, DirectoryError, SocketMissingError
from mailbox_seed import read_mailbox, seed_mailboxes
from member_reader import hook_members

DIRECTORY_APPLICATION = "svc-db-openldap"
HOOK_FILE = "hook.json"
MAILBOX_FILE = "mailbox.json"


def paused(hook):
    """Return whether app-control paused the hook's application.

    Args:
        hook: the parsed hook; ``paused_marker`` is the path of its app-control
            state marker, empty for an application outside app control and
            absent from a hook registered before app-control existed.
    """
    path = hook.get("paused_marker", "")
    if not path:
        return False
    marker = Path(path)
    return marker.is_file() and marker.read_text(encoding="utf-8").strip() == "stopped"


def stopped_for_backup(config, now):
    """Return whether the backup's maintenance signal holds OpenLDAP stopped at ``now``.

    Args:
        config: the parsed ``config.json``.
        now: the current time in seconds.

    Returns:
        False also for a signal that cannot be read, so the missing socket stays a failure.
    """
    moment = datetime.fromtimestamp(now, UTC)
    try:
        return DIRECTORY_APPLICATION in active(Path(config["maintenance_file"]), moment)
    except (OSError, TypeError, ValueError):
        return False


def missing_socket_reason(config, remote, now):
    """Return why a missing socket is no failure here, or an empty string when it is one.

    Args:
        config: the parsed ``config.json``.
        remote: whether OpenLDAP runs on another node than this one.
        now: the current time in seconds.
    """
    if remote:
        return "OpenLDAP runs on another node"
    if stopped_for_backup(config, now):
        return f"the backup stopped {DIRECTORY_APPLICATION}"
    return ""


def reach_directory(connect, config, remote, now):
    """Return ``(connection, None)``, or ``(None, exit code)`` after one line saying why not.

    Args:
        connect: ``ldap_client.Connection`` or a stand-in.
        config: the parsed ``config.json``.
        remote: whether OpenLDAP runs on another node than this one.
        now: the current time in seconds.

    Returns:
        Exit code 0 where OpenLDAP does not run on this node or is stopped for the
        backup, 1 for every other directory that does not answer.
    """
    uri = config["ldap"]["uri"]
    try:
        return connect(uri), None
    except SocketMissingError as error:
        reason = missing_socket_reason(config, remote, now)
        if reason:
            print(f"SKIPPED {error}: {reason}, no hook runs here")
            return None, 0
        failure = error
    except (DirectoryError, OSError) as error:
        failure = error
    print(
        f"FAILED directory {uri} unreachable: {type(failure).__name__}: {failure}",
        file=sys.stderr,
    )
    return None, 1


def load_hooks(hooks_dir, only):
    """Return ``(hook directory, parsed hook)`` pairs, sorted by application id.

    Args:
        hooks_dir: the directory that holds one directory per hook.
        only: an application id to restrict to, or an empty string.
    """
    hooks = [
        (path.parent, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(hooks_dir.glob(f"*/{HOOK_FILE}"))
    ]
    return [
        (path, hook)
        for path, hook in hooks
        if not only or hook["application_id"] == only
    ]


def main(argv, run=subprocess.run, connect=Connection, clock=time.time):
    """Run the selected hooks and return the exit code.

    Args:
        argv: the command line arguments.
        run: ``subprocess.run`` or a stand-in.
        connect: ``ldap_client.Connection`` or a stand-in.
        clock: ``time.time`` or a stand-in.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--directory", required=True)
    parser.add_argument("--only", default="")
    parser.add_argument("--members-file", default="")
    parser.add_argument("--remote-directory", action="store_true")
    options = parser.parse_args(argv)
    if options.members_file and not options.only:
        parser.error("--members-file requires --only")

    directory = Path(options.directory)
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    hooks = load_hooks(directory / "hooks", options.only)
    if options.only and not hooks:
        print(f"no hook registered for {options.only}", file=sys.stderr)
        return 1

    if options.members_file:
        given = json.loads(Path(options.members_file).read_text(encoding="utf-8"))
        hook_dir, hook = hooks[0]
        return (
            1
            if run_hook(config, hook_dir, hook, given, True, run, clock()) == "failed"
            else 0
        )

    ldap = config["ldap"]
    if not ldap:
        print("SKIPPED no directory is deployed, role groups are inventory grants")
        return 0
    mailbox_file = directory / MAILBOX_FILE
    connection, code = reach_directory(
        connect, config, options.remote_directory, clock()
    )
    if connection is None:
        return code
    seeded = True
    if mailbox_file.is_file() and not options.only:
        mailbox, seeded = read_mailbox(mailbox_file)
    else:
        mailbox = None
    if mailbox is not None:
        try:
            seeded = seed_mailboxes(connection, ldap, mailbox)
        except (DirectoryError, OSError) as error:
            print(f"[mailbox] FAILED {type(error).__name__}: {error}", file=sys.stderr)
            seeded = False
        connection, code = reach_directory(
            connect, config, options.remote_directory, clock()
        )
        if connection is None:
            return code if seeded else 1
    failed = []
    try:
        for hook_dir, hook in hooks:
            if paused(hook):
                print(f"[{hook['application_id']}] SKIPPED paused by app-control")
                continue
            try:
                members = hook_members(connection, ldap, hook)
            except (DirectoryError, OSError, ValueError) as error:
                print(
                    f"[{hook['application_id']}] FAILED reading its members: "
                    f"{type(error).__name__}: {error}",
                    file=sys.stderr,
                )
                failed.append(hook["application_id"])
                continue
            now = clock()
            if unchanged_since(hook_dir, hook, members, now, config["refresh_seconds"]):
                print(
                    f"[{hook['application_id']}] SKIPPED inputs unchanged since the last run"
                )
                continue
            try:
                outcome = run_hook(config, hook_dir, hook, members, False, run, now)
            except (subprocess.SubprocessError, OSError) as error:
                print(
                    f"[{hook['application_id']}] FAILED {type(error).__name__}: {error}",
                    file=sys.stderr,
                )
                outcome = "failed"
            if outcome == "failed":
                failed.append(hook["application_id"])
    finally:
        connection.close()
    if failed:
        print(f"FAILED hooks: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0 if seeded else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
