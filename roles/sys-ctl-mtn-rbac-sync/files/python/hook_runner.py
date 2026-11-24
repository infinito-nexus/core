import contextlib
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ALL_ROLES = "*"
LAST_RUN_FILE = "last_run.json"
MEMBERS_FILE_VARIABLE = "RBAC_SYNC_MEMBERS_FILE"


def reads_members_file(hook):
    """Args:
        hook: the parsed hook.

    Returns:
        Whether the hook is a host hook that reads its members from
        ``$RBAC_SYNC_MEMBERS_FILE``.
    """
    return hook["kind"] == "host" and "attributes" in hook


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


def invocation(config, hook_dir, hook, cid, forwarded, members_file):
    """Return ``(argv, stdin, extra environment)`` of one hook run.

    Args:
        config: the parsed ``config.json``.
        hook_dir: the directory of the hook.
        hook: the parsed hook.
        cid: the container id.
        forwarded: the hook's environment and member variables.
        members_file: path of the file that holds the members of a host hook.
    """
    if hook["kind"] == "host":
        handover = (
            {MEMBERS_FILE_VARIABLE: members_file}
            if reads_members_file(hook)
            else {"RBAC_SYNC_LDAP": json.dumps(config["ldap"])}
        )
        extra = {
            "RBAC_SYNC_CID": cid,
            "RBAC_SYNC_CONTAINER_BIN": config["container_bin"],
            **handover,
        }
        return [sys.executable, str(hook_dir / hook["script"])], b"", extra
    stdin = (hook_dir / hook["script"]).read_bytes() if hook["script"] else b""
    return exec_argv(config["container_bin"], hook, cid, forwarded), stdin, {}


@contextlib.contextmanager
def handed_members(hook, members):
    """Yield the path of a private file that holds a host hook's members, removed afterwards.

    Args:
        hook: the parsed hook; a hook that does not read a members file gets none
            and an empty path.
        members: ``{role: [members]}`` of the hook's application.
    """
    if not reads_members_file(hook):
        yield ""
        return
    descriptor, path = tempfile.mkstemp(prefix="rbac-sync-", suffix=".json")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(members, handle)
        yield path
    finally:
        Path(path).unlink(missing_ok=True)


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
    forwarded = {
        name: value if isinstance(value, str) else json.dumps(value)
        for name, value in {**hook["env"], **members_env(hook, members)}.items()
    }
    with handed_members(hook, members) as members_file:
        argv, stdin, extra = invocation(
            config, hook_dir, hook, cid, forwarded, members_file
        )
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
