"""Run every registered RBAC hook against the current members of its role groups.

Once the deploy applied the mailbox layout and wrote ``mailbox.json``, a run
without ``--only`` first gives every account without a primary address its
mailbox address.

Args:
    --directory: the directory that holds ``config.json``, ``hooks/`` and,
        under the applied mailbox layout, ``mailbox.json``.
    --only: run only the hook of this application.
    --members-file: JSON ``{role: [{username, email, name}]}`` used instead of
        a directory lookup; requires ``--only``, and a missing container is
        then an error rather than a skip.

Output:
    Every line a hook prints, prefixed with its application id, and every
    mailbox address set, prefixed with ``[mailbox]``; exit code 1 when any
    hook or address failed.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from backup_maintenance import active
from ldap_client import (
    SCOPE_ONE_LEVEL,
    SUCCESS,
    TYPE_OR_VALUE_EXISTS,
    Connection,
    DirectoryError,
    SocketMissingError,
    equality,
    present,
)
from ldap_mailbox import mailbox_address, sole_login

ALL_ROLES = "*"
DIRECTORY_APPLICATION = "svc-db-openldap"
USERS_ROLE = "@users"
HOOK_FILE = "hook.json"
LAST_RUN_FILE = "last_run.json"
MAILBOX_FILE = "mailbox.json"
OBJECT_CLASS = "objectClass"


def first(values):
    """Return the first value of an attribute, or an empty string.

    Args:
        values: the attribute values, possibly missing.
    """
    return str(values[0]) if values else ""


def directory_members(connection, ldap, application_id, role):
    """Return the accounts of one role, shaped like ``rbac_ldap_members``.

    Args:
        connection: an open ``ldap_client.Connection``.
        ldap: the ``ldap`` block of ``config.json``.
        application_id: the application the role belongs to.
        role: the role name; ``@users`` stands for every account of the users OU.
    """
    attributes = ldap["attributes"]
    if role == USERS_ROLE:
        search_filter = present(attributes["id"])
    else:
        search_filter = equality(
            attributes["member_of"], f"cn={application_id}-{role},{ldap['roles_dn']}"
        )
    entries = connection.search(
        ldap["users_dn"],
        SCOPE_ONE_LEVEL,
        search_filter,
        [attributes["id"], attributes["mail"], attributes["name"]],
    )
    members = [
        {
            "username": first(values.get(attributes["id"].lower())),
            "email": first(values.get(attributes["mail"].lower())),
            "name": first(values.get(attributes["name"].lower())),
        }
        for _, values in entries
    ]
    return sorted(
        (member for member in members if member["username"]),
        key=lambda member: member["username"],
    )


def mailbox_additions(dn, values, ldap, mailbox):
    """Return the values that seed an entry's mailbox, empty for an entry that holds a primary address.

    Args:
        dn: the DN of the entry.
        values: ``{lowercased attribute: [values]}`` of the entry.
        ldap: the ``ldap`` block of ``config.json``.
        mailbox: the content of ``mailbox.json``.

    Raises:
        ValueError: the entry holds no or several logins.
    """
    attributes = ldap["attributes"]
    if values.get(attributes["mail"].lower()):
        return {}
    login = sole_login(dn, values.get(attributes["id"].lower(), []), attributes["id"])
    additions = {}
    classes = {value.lower() for value in values.get(OBJECT_CLASS.lower(), [])}
    if mailbox["object_class"].lower() not in classes:
        additions[OBJECT_CLASS] = [mailbox["object_class"]]
    additions[attributes["mail"]] = [mailbox_address(login, mailbox["domain"])]
    return additions


def seed_mailboxes(connection, ldap, mailbox):
    """Give every account without a primary address its mailbox address; return whether all succeeded.

    Args:
        connection: an open ``ldap_client.Connection``, closed afterwards.
        ldap: the ``ldap`` block of ``config.json``.
        mailbox: the content of ``mailbox.json``.
    """
    attributes = ldap["attributes"]
    try:
        code = connection.bind(mailbox["bind_dn"], mailbox["bind_password"])
        if code != SUCCESS:
            print(f"[mailbox] FAILED bind answered result code {code}", file=sys.stderr)
            return False
        entries = connection.search(
            ldap["users_dn"],
            SCOPE_ONE_LEVEL,
            present(attributes["id"]),
            [attributes["id"], attributes["mail"], OBJECT_CLASS],
        )
        succeeded = True
        for dn, values in entries:
            try:
                additions = mailbox_additions(dn, values, ldap, mailbox)
            except ValueError as error:
                print(f"[mailbox] FAILED {error}", file=sys.stderr)
                succeeded = False
                continue
            if not additions:
                continue
            code = connection.add_values(dn, additions)
            address = additions[attributes["mail"]][0]
            if code == SUCCESS:
                print(f"[mailbox] CHANGED {dn} {attributes['mail']}={address}")
            elif code == TYPE_OR_VALUE_EXISTS:
                print(f"[mailbox] SKIPPED {dn} was seeded concurrently")
            else:
                print(
                    f"[mailbox] FAILED {dn} modify answered result code {code}",
                    file=sys.stderr,
                )
                succeeded = False
        return succeeded
    finally:
        connection.close()


def members_env(hook, members):
    """Return the environment variables that carry the members into the hook.

    Args:
        hook: the parsed hook.
        members: ``{role: [members]}`` of the hook's application.
    """
    env = {}
    for entry in hook["members_env"]:
        if entry["role"] == ALL_ROLES:
            value = {role: members[role] for role in hook["roles"]}
        elif entry["field"]:
            value = [member[entry["field"]] for member in members[entry["role"]]]
        else:
            value = members[entry["role"]]
        env[entry["name"]] = json.dumps(value)
    return env


def local_container(container_bin, hook, run, any_slot):
    """Return the id of the hook's running container on this node, or an empty string.

    Args:
        container_bin: path of the ``container`` wrapper.
        hook: the parsed hook.
        run: ``subprocess.run`` or a stand-in.
        any_slot: whether a swarm container of any task slot qualifies; false restricts it to task slot 1.
    """
    target = hook["container"]
    if "swarm_service" in target:
        selector = f"label=com.docker.swarm.service.name={target['swarm_service']}"
    else:
        selector = f"name=^/{target['name']}$"
    found = run(
        [
            container_bin,
            "ps",
            "--filter",
            selector,
            "--filter",
            "status=running",
            "--format",
            '{{.ID}} {{.Label "com.docker.swarm.task.name"}}',
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in found.stdout.splitlines():
        cid, _, task = line.strip().partition(" ")
        if not cid:
            continue
        if "swarm_service" not in target or any_slot:
            return cid
        if task.split(".")[1:2] == ["1"]:
            return cid
    return ""


def exec_argv(container_bin, hook, cid, env_names):
    """Return the ``container exec`` argv.

    Args:
        container_bin: path of the ``container`` wrapper.
        hook: the parsed hook.
        cid: the container id.
        env_names: names of the variables forwarded into the container, passed as ``-e NAME`` without values.
    """
    argv = [container_bin, "exec", "-i"]
    if hook["user"]:
        argv += ["--user", hook["user"]]
    for name in sorted(env_names):
        argv += ["-e", name]
    return [*argv, cid, *hook["argv"]]


def invocation(config, hook_dir, hook, cid, forwarded):
    """Return ``(argv, stdin, extra environment)`` of one hook run.

    Args:
        config: the parsed ``config.json``.
        hook_dir: the directory of the hook.
        hook: the parsed hook.
        cid: the container id.
        forwarded: the hook's environment and member variables.
    """
    if hook["kind"] == "host":
        extra = {
            "RBAC_SYNC_CID": cid,
            "RBAC_SYNC_CONTAINER_BIN": config["container_bin"],
            "RBAC_SYNC_LDAP": json.dumps(config["ldap"]),
        }
        return [sys.executable, str(hook_dir / hook["script"])], b"", extra
    stdin = (hook_dir / hook["script"]).read_bytes() if hook["script"] else b""
    return exec_argv(config["container_bin"], hook, cid, forwarded), stdin, {}


def digest(hook, members):
    """Return the digest of everything a hook run depends on.

    Args:
        hook: the parsed hook.
        members: ``{role: [members]}`` of the hook's application.
    """
    payload = json.dumps({"hook": hook, "members": members}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def unchanged_since(hook_dir, hook, members, now, refresh_seconds):
    """Return whether the last successful run saw the same inputs recently enough to skip.

    Args:
        hook_dir: the directory of the hook.
        hook: the parsed hook.
        members: ``{role: [members]}`` of the hook's application.
        now: the current time in seconds.
        refresh_seconds: age after which a hook runs even with unchanged inputs.
    """
    state = hook_dir / LAST_RUN_FILE
    if not hook["skip_unchanged"] or not state.exists():
        return False
    last = json.loads(state.read_text(encoding="utf-8"))
    return (
        last["digest"] == digest(hook, members) and now - last["at"] < refresh_seconds
    )


def run_hook(config, hook_dir, hook, members, required, run, now):
    """Run one hook and return ``ran``, ``skipped`` or ``failed``.

    Args:
        config: the parsed ``config.json``.
        hook_dir: the directory of the hook.
        hook: the parsed hook.
        members: ``{role: [members]}`` of the hook's application.
        required: whether a missing container is a failure.
        run: ``subprocess.run`` or a stand-in.
        now: the current time in seconds, recorded after a successful run.
    """
    application_id = hook["application_id"]
    cid = local_container(config["container_bin"], hook, run, required)
    if not cid:
        if required:
            print(
                f"[{application_id}] no running container on this node", file=sys.stderr
            )
            return "failed"
        print(f"[{application_id}] SKIPPED no running container on this node")
        return "skipped"
    forwarded = {**hook["env"], **members_env(hook, members)}
    argv, stdin, extra = invocation(config, hook_dir, hook, cid, forwarded)
    result = run(
        argv,
        input=stdin,
        capture_output=True,
        cwd=str(hook_dir),
        env={**os.environ, **forwarded, **extra},
        timeout=config["timeout_seconds"],
        check=False,
    )
    for line in result.stdout.decode("utf-8", "replace").splitlines():
        print(f"[{application_id}] {line}")
    if result.returncode != 0:
        for line in result.stderr.decode("utf-8", "replace").splitlines():
            print(f"[{application_id}] {line}", file=sys.stderr)
        print(
            f"[{application_id}] FAILED exit code {result.returncode}", file=sys.stderr
        )
        return "failed"
    (hook_dir / LAST_RUN_FILE).write_text(
        json.dumps({"digest": digest(hook, members), "at": now}), encoding="utf-8"
    )
    return "ran"


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


def missing_socket_reason(config, now):
    """Return why a missing socket is no failure here, or an empty string when it is one.

    Args:
        config: the parsed ``config.json``.
        now: the current time in seconds.
    """
    if not config["directory_host"]:
        return "OpenLDAP runs on another node"
    if stopped_for_backup(config, now):
        return f"the backup stopped {DIRECTORY_APPLICATION}"
    return ""


def reach_directory(connect, config, now):
    """Return ``(connection, None)``, or ``(None, exit code)`` after one line saying why not.

    Args:
        connect: ``ldap_client.Connection`` or a stand-in.
        config: the parsed ``config.json``.
        now: the current time in seconds.

    Returns:
        Exit code 0 where OpenLDAP does not run on this node or is stopped for the
        backup, 1 for every other directory that does not answer.
    """
    uri = config["ldap"]["uri"]
    try:
        return connect(uri), None
    except SocketMissingError as error:
        reason = missing_socket_reason(config, now)
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


def read_mailbox(path):
    """Return ``(mailbox, True)``, or ``(None, False)`` after one line saying why it is unreadable.

    Args:
        path: the ``mailbox.json`` the deploy wrote.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8")), True
    except (OSError, ValueError) as error:
        print(f"[mailbox] FAILED {type(error).__name__}: {error}", file=sys.stderr)
        return None, False


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
    connection, code = reach_directory(connect, config, clock())
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
        connection, code = reach_directory(connect, config, clock())
        if connection is None:
            return code if seeded else 1
    failed = []
    try:
        for hook_dir, hook in hooks:
            if paused(hook):
                print(f"[{hook['application_id']}] SKIPPED paused by app-control")
                continue
            members = {
                role: directory_members(connection, ldap, hook["application_id"], role)
                for role in hook["roles"]
            }
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
