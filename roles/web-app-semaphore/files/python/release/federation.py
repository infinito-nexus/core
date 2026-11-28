from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

# nocheck: project-root-import  standalone helper the runner runs with python3 -I from the core tree; no package container to import PROJECT_ROOT from
sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from utils.openbao_client import OpenBaoError, login
from utils.platform_monitoring import (
    AGENT_KEY_PATH,
    CLAIM_PATH,
    DIGEST_FILES_FIELD,
    DIGEST_MOUNT,
    DIGEST_PATH,
    FEDERATION_MOUNT,
    FEDERATION_PATH,
    MARKER_PATH,
    MONITORED_PATH,
    bao_endpoint,
    bao_path,
    canonical_host,
    digest_file_path,
    host_segment,
)

SCRIPT = "release/federation.py"
ERASED = (200, 204, 404)
ABSENT = 404
PRESENT = 200


def marker(workspace, host):
    """Args:
    workspace: the bare workspace id.
    host: the inventory host the release discharges.

    Returns:
        ``(mount, path)`` of the release tombstone ``mark`` writes once the
        host proved its monitoring share gone, before the release drops the
        key. No release erases it; only the workspace destroy does, with the
        workspace's monitoring tree.
    """
    return DIGEST_MOUNT, bao_path(
        MARKER_PATH, workspace=workspace, host=host_segment(host)
    )


def records(workspace, host):
    """Args:
    workspace: the bare workspace id.
    host: the inventory host the release discharges.

    Returns:
        ``(mount, path)`` of the host's federation token, its digest record
        and its agent key mirror, the entries ``monitoring apply`` wrote for
        it, in the order :func:`erase` takes them; with the mirror gone no
        later deploy of the host finds the platform key to install.
    """
    segment = host_segment(host)
    return [
        (mount, bao_path(path, workspace=workspace, host=segment))
        for mount, path in (
            (FEDERATION_MOUNT, FEDERATION_PATH),
            (DIGEST_MOUNT, DIGEST_PATH),
            (DIGEST_MOUNT, AGENT_KEY_PATH),
        )
    ]


def erase(client, workspace, host):
    """Args:
    client: an ``OpenBaoClient`` logged in as the workspace's own role.
    workspace: the bare workspace id.
    host: the inventory host.

    Returns:
        The finding of the first record that could not be erased or still
        answers its metadata afterwards; the records after it stay, so a
        rerun finds the tombstone and the rest and retries. Empty once all
        are gone, also when they never existed.
    """
    for mount, path in records(workspace, host):
        status, _ = client.request("DELETE", endpoint(mount, "metadata", path), None)
        if status not in ERASED:
            return [f"erasing {mount}/{path} answered {status}"]
        status, _ = client.request("GET", endpoint(mount, "metadata", path), None)
        if status != ABSENT:
            return [f"{mount}/{path} still answers {status} after its erase"]
    return []


def endpoint(mount, kind, path):
    """Args:
    mount: a KV v2 mount.
    kind: ``data`` or ``metadata``.
    path: the secret's path below the mount.

    Returns:
        The request path of :func:`utils.platform_monitoring.bao_endpoint`.
    """
    return bao_endpoint(mount, kind, path)


def read(client, mount, path):
    """Args:
    client: an ``OpenBaoClient`` logged in as the workspace's own role.
    mount: a KV v2 mount.
    path: the secret's path below it.

    Returns:
        The secret's fields, None when it does not exist.

    Raises:
        OpenBaoError: when the read answers neither present nor absent.
    """
    status, body = client.request("GET", endpoint(mount, "data", path), None)
    if status not in (PRESENT, ABSENT):
        raise OpenBaoError(f"reading {mount}/{path} answered {status}")
    if status == ABSENT:
        return None
    return ((body or {}).get("data") or {}).get("data") or {}


def marked(client, workspace, host):
    """Args:
    client: an ``OpenBaoClient`` logged in as the workspace's own role.
    workspace: the bare workspace id.
    host: the inventory host.

    Returns:
        Whether the host's release tombstone exists.
    """
    return read(client, *marker(workspace, host)) is not None


def mark(client, workspace, host, proof, now):
    """Args:
    client: an ``OpenBaoClient`` logged in as the workspace's own role.
    workspace: the bare workspace id.
    host: the inventory host.
    proof: the share line ``release/host.py share`` printed once its on-disk
        proof passed.
    now: the UTC time of the proof.

    Writes the tombstone unless it exists; one an earlier run wrote is kept
    unchanged.
    """
    if not marked(client, workspace, host):
        client.write_create_only(
            *marker(workspace, host), {"proof": proof, "at": now.isoformat()}
        )


def claim(client, workspace, host, now):
    """Args:
    client: an ``OpenBaoClient`` logged in as the workspace's own role.
    workspace: the bare workspace id.
    host: the inventory host.
    now: the UTC time of the claim.

    Writes the release claim ``monitoring/ws-<id>/releasing/<host>`` unless
    it exists, before the release reads the platform record. ``monitoring
    apply`` writes that record before it checks for a claim, so of a
    concurrent apply and release either the apply refuses or the release
    reads the record it wrote. Only the workspace destroy erases it.
    """
    path = bao_path(CLAIM_PATH, workspace=workspace, host=host_segment(host))
    if read(client, DIGEST_MOUNT, path) is None:
        client.write_create_only(DIGEST_MOUNT, path, {"at": now.isoformat()})


def unmarked(client, workspace, host):
    """Args:
    client: an ``OpenBaoClient`` logged in as the workspace's own role.
    workspace: the bare workspace id.
    host: the inventory host, which refused the platform key.

    Returns:
        Empty when the tombstone proves an earlier run removed the share
        before it dropped the key, else the finding a refused login fails
        with, whatever records are left.
    """
    if marked(client, workspace, host):
        return []
    return [
        (
            f"{host} refuses the platform key and no release marker proves an "
            "earlier run removed its monitoring share; restore access or remove "
            "the agent binary, the monitoring key line and the federation digest "
            "file manually"
        )
    ]


def monitored(workspace, host):
    """Args:
    workspace: the bare workspace id.
    host: the inventory host.

    Returns:
        ``(mount, path)`` of the platform record ``monitoring apply`` writes
        for every host it monitors, naming every digest file it ever named.
        The workspace reads it but can neither write nor delete it;
        ``monitoring remove`` keeps it and only the workspace destroy erases
        it.
    """
    return FEDERATION_MOUNT, bao_path(
        MONITORED_PATH, workspace=workspace, host=host_segment(host)
    )


def digest_files(client, workspace, host):
    """Args:
    client: an ``OpenBaoClient`` logged in as the workspace's own role.
    workspace: the bare workspace id.
    host: the inventory host.

    Returns:
        Every digest file the platform record of a once monitored host
        names, empty when there is none: the host was never monitored. Only
        that record decides, which no workspace task writes or deletes;
        neither the digest record nor the tombstone, which the workspace
        writes, is read.

    Raises:
        OpenBaoError: the record names no digest file, or one that is none.
    """
    record = monitored(workspace, host)
    held = read(client, *record)
    if held is None:
        return []
    named = held.get(DIGEST_FILES_FIELD)
    if not isinstance(named, list) or not named:
        raise OpenBaoError(f"{record[0]}/{record[1]} names no digest file")
    for each in named:
        if not digest_file_path(each):
            raise OpenBaoError(
                f"{record[0]}/{record[1]} names {each!r}, no digest file"
            )
    return named


def with_current(named, current):
    """Args:
    named: the digest files of the platform record, empty for a never
        monitored host.
    current: the digest file the workspace's present core deploys
        (``platform_monitoring.py digest-file``), which no monitoring apply
        may have recorded yet.

    Returns:
        ``named`` with ``current`` after it for a once monitored host, so
        the release also removes the file a deploy on the present core
        wrote.

    Raises:
        OpenBaoError: ``current`` is no digest file.
    """
    if not named or current in named:
        return named
    if not digest_file_path(current):
        raise OpenBaoError(f"the present core names {current!r}, no digest file")
    return [*named, current]


def parser():
    """Returns:
    The command line: ``claim OUT CURRENT``, which claims the host and
    writes the digest files the release removes and checks to ``OUT``,
    space separated on one line, empty for a never monitored host, the
    present core's ``CURRENT`` included; ``digest-files OUT CURRENT``,
    the same without the claim, which decides the arguments of the
    host-side check before any write; ``mark SHARE`` with the file
    ``proof_of_release.py share`` wrote; ``marked``; ``erase``.
    """
    command = argparse.ArgumentParser(prog=SCRIPT)
    actions = command.add_subparsers(dest="action", required=True)
    actions.add_parser("mark").add_argument("share")
    actions.add_parser("marked")
    actions.add_parser("erase")
    for action in ("digest-files", "claim"):
        named = actions.add_parser(action)
        named.add_argument("out")
        named.add_argument("current")
    return command


def main(argv, env, stdout, client=None, now=None):
    """Args:
    argv: the command line without the program name.
    env: the task environment: ``WORKSPACE`` (the bare id), ``HOST``, which
        every path names by its ``canonical_host`` form as ``monitoring
        apply`` does (``utils/platform_monitoring.py`` ``host_segment``), and
        the OpenBao login of ``utils.openbao_client.login``.
    stdout: where a failure line goes.
    client: a stand-in for the login, else :func:`login` of ``env``.
    now: the time ``claim`` and ``mark`` record, else the current UTC time.

    Returns:
        0 once the action holds: the tombstone exists, the host's records
        are gone, or the host is claimed and its digest files written; 1
        with ``{"host", "released": false, "failed"}`` as the last line, the
        shape ``proof_of_release.py`` reports, otherwise, also for a HOST
        ``canonical_host`` refuses, before any request.
    """
    arguments = parser().parse_args(argv)
    host = env.get("HOST", "")
    workspace = env.get("WORKSPACE", "")
    found = []
    try:
        canonical_host(host)
        bao = client or login(env)
        when = now or datetime.datetime.now(datetime.UTC)
        if arguments.action == "mark":
            proof = json.loads(Path(arguments.share).read_text(encoding="utf-8"))
            mark(bao, workspace, host, proof, when)
        elif arguments.action == "marked":
            found = unmarked(bao, workspace, host)
        elif arguments.action == "erase":
            found = erase(bao, workspace, host)
        else:
            if arguments.action == "claim":
                claim(bao, workspace, host, when)
            chosen = with_current(digest_files(bao, workspace, host), arguments.current)
            if not chosen:
                print(
                    f"{SCRIPT}: {host} was never monitored, no digest file to remove",
                    file=sys.stderr,
                )
            Path(arguments.out).write_text(f"{' '.join(chosen)}\n", encoding="utf-8")
    except (OpenBaoError, OSError, ValueError) as error:
        found = [str(error)]
    if found:
        reason = "; ".join(found)
        print(f"{SCRIPT}: {reason}", file=sys.stderr)
        line = {"host": host, "released": False, "failed": reason}
        print(json.dumps(line, sort_keys=True), file=stdout)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ, sys.stdout))
