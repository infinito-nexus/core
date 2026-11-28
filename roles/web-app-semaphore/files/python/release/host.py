# nocheck: file-size  host.sh hands this file alone to ansible.builtin.script, which runs it on the customer host, where no sibling module is importable
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = "release/host.py"
ROOT = "root"
SUDOERS_DIR = "/etc/sudoers.d"
KEYS_FILE = (".ssh", "authorized_keys")
KEY_TYPE = re.compile(r"^(ssh-|ecdsa-sha2-|sk-|rsa-sha2-)[A-Za-z0-9@.-]+$")
NEWLINE = "\n"
SHARE_COUNTS = ("federation_token", "monitoring_agent")
MONITORING_COUNTS = (*SHARE_COUNTS, "monitoring_key")
BASE_COUNTS = (
    "agent_keys",
    "app_control_keys",
    "app_control_sudoers",
    "backup_keys",
    "backup_sudoers",
)
COUNTS = (*BASE_COUNTS, *MONITORING_COUNTS)
UNMONITORED_SHARE = (
    "the host holds {} of the platform monitoring share; release it while the "
    "platform runs Checkmk or Prometheus"
)
NO_SHELL = frozenset({"command", "restrict"})
ENCODING = {"encoding": "utf-8", "errors": "surrogateescape"}
AGENT_SCRIPT = "/usr/bin/check_mk_agent"
AGENT_MARKER = "/etc/infinito.nexus/platform-monitoring-agent"
DIGEST_LOCK = ".lock"
MONITORING_KEY_LINE = re.compile(
    '^command="(?:echo '
    "'<<<infinito_workspace>>>'; echo "
    "ws-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}; exec )?"
    'check_mk_agent",restrict,.* infinito-platform-monitoring$'
)


class RefusedError(Exception):
    pass


def skip_options(text):
    """Args:
    text: an ``authorized_keys`` line that starts with its options.

    Returns:
        The rest of the line after the options, skipped as
        ``sshkey_advance_past_options`` of OpenSSH does: a backslash escapes
        a double quote, a space or tab outside quotes ends them; None for an
        unterminated quote.
    """
    quoted = False
    index = 0
    while index < len(text) and (quoted or text[index] not in " \t"):
        if text[index] == "\\" and text[index + 1 : index + 2] == '"':
            index += 1
        elif text[index] == '"':
            quoted = not quoted
        index += 1
    return None if quoted else text[index:]


def key_blob(line):
    """Args:
    line: one ``authorized_keys`` or ``ssh-add -L`` line.

    Returns:
        The ``(type, base64 blob)`` of the key the line holds, None for a
        blank line, a comment or a line holding no key.
    """
    text = line.strip(" \t\r\n")
    if not text or text.startswith("#"):
        return None
    tokens = text.split(None, 2)
    if not KEY_TYPE.match(tokens[0]):
        rest = skip_options(text)
        tokens = rest.split(None, 2) if rest is not None else []
    if len(tokens) < 2 or not KEY_TYPE.match(tokens[0]):
        return None
    return tokens[0], tokens[1]


def option_names(line):
    """Args:
    line: one ``authorized_keys`` line that holds a key.

    Returns:
        The lowercased names of its options, split at the commas outside
        double quotes as sshd splits them; ``command="a,b"`` is the one name
        ``command``.
    """
    text = line.strip(" \t\r\n")
    if KEY_TYPE.match(text.split(None, 1)[0]):
        return set()
    rest = skip_options(text) or ""
    names = set()
    quoted = False
    start = 0
    options = text[: len(text) - len(rest)].rstrip(" \t")
    for index, char in enumerate(options + ","):
        if char == '"' and options[index - 1 : index] != "\\":
            quoted = not quoted
        elif char == "," and not quoted:
            names.add(options[start:index].split("=", 1)[0].lower())
            start = index + 1
    return names


def shell_line(line, accepts):
    """Args:
    line: one ``authorized_keys`` line.
    accepts: the check of ``keygen_accepts``.

    Returns:
        Whether the line lets its key open a shell: ``accepts`` reads a key
        from it and it carries neither ``command=`` nor ``restrict``, either
        of which can leave the customer without a shell; ``from=`` and the
        other options do not count against it.
    """
    return (
        key_blob(line) is not None
        and not (option_names(line) & NO_SHELL)
        and accepts(line)
    )


def agent_line(line, blobs):
    """Args:
    line: one ``authorized_keys`` line.
    blobs: the base64 blobs of the task agent's keys.

    Returns:
        Whether the line authorizes one of them. The blob alone decides,
        since it encodes the key type itself and sshd also reads an RSA key
        written as ``rsa-sha2-256`` or ``rsa-sha2-512``.
    """
    key = key_blob(line)
    return key is not None and key[1] in blobs


def keygen_accepts(line):
    """Args:
    line: one ``authorized_keys`` line.

    Returns:
        Whether ``ssh-keygen -l -f`` reads a key from it.
    """
    listed = subprocess.run(
        ["ssh-keygen", "-l", "-f", "-"],
        input=line if line.endswith("\n") else f"{line}\n",
        capture_output=True,
        text=True,
        check=False,
        **ENCODING,
    )
    return listed.returncode == 0


def account_home(user):
    """Args:
    user: an account name.

    Returns:
        Its home directory, None when the host has no such account.
    """
    try:
        return pwd.getpwnam(user).pw_dir
    except KeyError:
        return None


def keys_path(user, home):
    """Args:
    user: an account name.
    home: the resolver of ``account_home``.

    Returns:
        The ``authorized_keys`` path of the account, None without the account.
    """
    directory = home(user)
    return None if directory is None else Path(directory).joinpath(*KEYS_FILE)


def read_lines(path):
    """Args:
    path: an ``authorized_keys`` or sudoers path, None for none.

    Returns:
        Its lines with their ends, split at a line feed only, as sshd reads
        them, so a carriage return stays inside its line; None when it is
        missing.

    Raises:
        RefusedError: the path is a symbolic link or no regular file.
    """
    if path is None:
        return None
    try:
        handle = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise RefusedError(
            f"{path} is no file the release reads: {error.strerror}"
        ) from None
    with os.fdopen(handle, newline="", **ENCODING) as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise RefusedError(f"{path} is no regular file")
        text = stream.read()
    lines = [f"{part}{NEWLINE}" for part in text.split(NEWLINE)]
    lines[-1] = lines[-1][: -len(NEWLINE)]
    return [line for line in lines if line]


def count_keys(lines):
    """Args:
    lines: ``authorized_keys`` lines.

    Returns:
        How many of them hold a key.
    """
    return sum(1 for line in lines if key_blob(line) is not None)


def plan(login, agent, platform, home, sudoers_dir, accepts):
    """Args:
    login: the account the task logs in as, ``ansible_user``.
    agent: the ``(type, base64 blob)`` of every key of the task agent.
    platform: ``(app-control account, backup account)``.
    home: the resolver of ``account_home``.
    sudoers_dir: the sudoers drop-in directory.
    accepts: the check of ``keygen_accepts``.

    Returns:
        ``(writes, removed, kept)``: the ``(path, lines)`` writes in their
        order, None as lines for a removal, the removed counts by
        ``COUNTS`` and the customer keys ``login`` keeps. The agent keys of
        ``login`` go last, so a release stopped earlier still logs in again.

    Raises:
        RefusedError: ``login`` is a platform account or no account, a path
            is no regular file, or ``login`` would keep no ``shell_line``.
    """
    control_user, backup_user = platform
    if login in platform:
        raise RefusedError(f"the login user {login} is a platform account")
    login_path = keys_path(login, home)
    if login_path is None:
        raise RefusedError(f"the host has no account {login}")
    writes = []
    removed = dict.fromkeys(COUNTS, 0)
    control_path = keys_path(control_user, home)
    control = read_lines(control_path)
    if control is not None:
        writes.append((control_path, None))
        removed["app_control_keys"] = count_keys(control)
    for user, count in (
        (control_user, "app_control_sudoers"),
        (backup_user, "backup_sudoers"),
    ):
        sudoers = Path(sudoers_dir) / user
        if read_lines(sudoers) is not None:
            writes.append((sudoers, None))
            removed[count] = 1
    backup_path = keys_path(backup_user, home)
    backup = read_lines(backup_path)
    if backup:
        writes.append((backup_path, []))
        removed["backup_keys"] = count_keys(backup)
    kept = 0
    root_path = keys_path(ROOT, home)
    blobs = {data for _, data in agent}
    for path in dict.fromkeys(p for p in (root_path, login_path) if p):
        lines = read_lines(path) or []
        keep = [line for line in lines if not agent_line(line, blobs)]
        removed["agent_keys"] += len(lines) - len(keep)
        unmonitored = [line for line in keep if not monitoring_key_line(line)]
        removed["monitoring_key"] += len(keep) - len(unmonitored)
        keep = unmonitored
        if len(keep) != len(lines):
            writes.append((path, keep))
        if path == login_path:
            kept = sum(1 for line in keep if shell_line(line, accepts))
    if not kept:
        raise RefusedError(
            f"{login} would keep no customer key ssh-keygen accepts "
            "without command= or restrict"
        )
    return writes, removed, kept


def replace(path, lines):
    """Args:
    path: an existing regular file.
    lines: its new lines with their ends; owner and mode stay.
    """
    info = path.lstat()
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=".release-")
    temporary = Path(name)
    try:
        with os.fdopen(handle, "w", newline="", **ENCODING) as stream:
            stream.writelines(lines)
            stream.flush()
            os.fchown(stream.fileno(), info.st_uid, info.st_gid)
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
            os.fsync(stream.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def apply(writes):
    """Args:
    writes: the ``(path, lines)`` writes of ``plan``.
    """
    for path, lines in writes:
        if lines is None:
            path.unlink(missing_ok=True)
        else:
            replace(path, lines)


def monitoring_key_line(line):
    """Args:
    line: one ``authorized_keys`` line.

    Returns:
        Whether it is the platform monitoring key line ``agent_key_line`` of
        ``utils/platform_monitoring.py`` writes; this script runs alone on
        the host, so ``MONITORING_KEY_LINE`` is a copy a test compares.
    """
    return MONITORING_KEY_LINE.match(line.strip(" \t\r\n")) is not None


SHARE_FINDINGS = {
    "monitoring_agent": "the agent {} is still installed",
    "federation_token": "the digest file {} still exists",
}


def sha256_of(path):
    """Args:
    path: a file, which may be missing.

    Returns:
        The SHA-256 hex digest of its bytes, None when it is no regular
        file.
    """
    if path.is_symlink() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextlib.contextmanager
def digest_lock(path):
    """Args:
    path: a digest file whose directory exists.

    Holds the exclusive ``flock`` on ``<path>`` + ``DIGEST_LOCK`` that
    ``digest_line.py`` of ``svc-net-platform-monitoring`` takes for every
    deploy edit, so a release and a deploy never edit the file at once.
    """
    handle = os.open(
        f"{path}{DIGEST_LOCK}", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        os.close(handle)


class Monitoring:
    """Args:
    root: the directory the host paths resolve under, ``/`` on the host.
    digests: every federation digest file ``federate.conf.j2`` ever read
        on the host, the ones the platform record names, empty for a host
        the platform never monitored and for a worker, which holds none.
    """

    def __init__(self, root, digests):
        self.root = Path(root)
        self.digests = list(digests)
        marker = self.path(AGENT_MARKER)
        self.installed = marker.exists() or marker.is_symlink()
        self.recorded = (
            marker.read_text(encoding="utf-8").strip() if marker.is_file() else None
        )

    def path(self, absolute):
        return self.root / str(absolute).lstrip("/")

    def ours(self):
        script = sha256_of(self.path(AGENT_SCRIPT))
        return script is not None and script == self.recorded

    def foreign(self):
        """Returns:
        The agent script a marker names whose content another install
        changed, None when there is none.
        """
        script = self.path(AGENT_SCRIPT)
        held = script.exists() or script.is_symlink()
        return AGENT_SCRIPT if self.installed and held and not self.ours() else None

    def held(self):
        agent = [(AGENT_SCRIPT, "monitoring_agent")] if self.ours() else []
        return agent + [
            (digest, "federation_token")
            for digest in self.digests
            if self.path(digest).exists() or self.path(digest).is_symlink()
        ]

    def remove(self):
        """Returns:
        The removed counts ``monitoring_agent`` and ``federation_token``, 1
        when the agent or any digest file went; a second run counts zeros.
        The stack host's release takes every line of a digest file, the
        workers' too, so ``/federate`` admits no bearer once it ran. No HTTP
        round trip is needed, so a stopped or suspended instance releases
        too.
        """
        removed = {"monitoring_agent": 0, "federation_token": 0}
        left = self.foreign()
        if left:
            print(
                f"{SCRIPT}: {left} no longer holds the agent the platform "
                "installed; it stays and only the marker goes",
                file=sys.stderr,
            )
        for absolute, count in self.held():
            target = self.path(absolute)
            if count == "monitoring_agent":
                target.unlink()
            else:
                with digest_lock(target):
                    target.unlink(missing_ok=True)
            removed[count] = 1
        self.path(AGENT_MARKER).unlink(missing_ok=True)
        return removed

    def artefacts(self):
        """Returns:
        The monitoring share a release without ``--monitoring`` finds on
        the host: the agent marker and every digest file, named.
        """
        marker = [f"the agent marker {AGENT_MARKER}"] if self.installed else []
        return marker + [
            f"the digest file {absolute}"
            for absolute, count in self.held()
            if count == "federation_token"
        ]

    def proof(self):
        """Returns:
        One finding per share the host still serves: the agent script the
        platform's key would run, or a digest file ``/federate`` would admit
        a bearer against, each checked on disk as this run sees it.
        """
        return [
            SHARE_FINDINGS[count].format(absolute) for absolute, count in self.held()
        ]


def key_leftovers(paths):
    """Args:
    paths: the ``authorized_keys`` files the release rewrote.

    Returns:
        One finding per file that still holds a ``monitoring_key_line``.
    """
    return [
        f"{path} still lets the platform monitoring key in"
        for path in paths
        if any(monitoring_key_line(line) for line in read_lines(path) or [])
    ]


def fail(stdout, failures):
    """Args:
    stdout: where the result line goes.
    failures: the findings that end the release.

    Returns:
        1, after the ``{"failed": ...}`` line ``proof_of_release.py`` reports.
    """
    print(f"{SCRIPT}: {'; '.join(failures)}", file=sys.stderr)
    print(json.dumps({"failed": "; ".join(failures)}), file=stdout)
    return 1


def refuse(stdout, reason):
    """Args:
    stdout: where the result line goes.
    reason: why the release writes nothing.

    Returns:
        2, after the ``{"refused": ...}`` line ``proof_of_release.py`` reports.
    """
    print(f"{SCRIPT}: {reason}", file=sys.stderr)
    print(json.dumps({"refused": reason}), file=stdout)
    return 2


def release(arguments, stdout, home, sudoers_dir, accepts, monitoring):
    """Args:
    arguments: the parsed ``check``, ``share`` or ``apply`` command line.
    stdout: where the result line goes.
    home: the resolver of ``account_home``.
    sudoers_dir: the sudoers drop-in directory.
    accepts: the check of ``keygen_accepts``.
    monitoring: the ``Monitoring`` of the host.

    Returns:
        0 once every write is done and proven, 2 on a refusal, which writes
        nothing, 1 when the agent or the digest outlives its removal, which
        keeps every key so the release can run again, or when a rewritten
        ``authorized_keys`` still holds the monitoring key. ``share`` stops
        after the proven removal of the share with ``{"removed"}`` of
        ``SHARE_COUNTS`` and keeps every key, so the task can record the
        proof in OpenBao before ``apply`` drops them. ``apply`` without
        ``--monitoring`` is the release of a platform without monitoring or
        of a host it never monitored: it counts ``BASE_COUNTS`` alone and
        refuses a host on which any of the share is left, the agent marker,
        the monitoring key line or a digest file of ``--federation-digest``,
        which it only reads.
    """
    agent = {tuple(pair) for pair in arguments.agent_key}
    platform = (arguments.app_control_user, arguments.backup_user)
    try:
        writes, removed, kept = plan(
            arguments.login, agent, platform, home, sudoers_dir, accepts
        )
    except RefusedError as error:
        return refuse(stdout, str(error))
    left = ["the monitoring key line"] if removed["monitoring_key"] else []
    left += monitoring.artefacts()
    if not arguments.monitoring and left:
        return refuse(stdout, UNMONITORED_SHARE.format(", ".join(left)))
    if arguments.action == "check":
        print(json.dumps({"checked": True}), file=stdout)
        return 0
    if arguments.monitoring:
        try:
            shared = monitoring.remove()
            failures = monitoring.proof()
        except (OSError, RefusedError) as error:
            failures = [f"the monitoring share could not be removed: {error}"]
        if failures:
            return fail(stdout, failures)
        if arguments.action == "share":
            print(json.dumps({"removed": shared}, sort_keys=True), file=stdout)
            return 0
        removed.update(shared)
    else:
        removed = {name: removed[name] for name in BASE_COUNTS}
    apply(writes)
    leftovers = key_leftovers(
        dict.fromkeys(
            p for p in (keys_path(ROOT, home), keys_path(arguments.login, home)) if p
        )
    )
    if leftovers:
        return fail(stdout, leftovers)
    print(json.dumps({"kept": kept, "removed": removed}, sort_keys=True), file=stdout)
    return 0


def parser():
    """Returns:
    The command line of ``check``, ``share`` and ``apply``, run on the
    host as root; ``check`` runs every refusal of ``release`` with the
    arguments ``apply`` gets, ``--monitoring`` and ``--federation-digest``
    included, and writes nothing, so the task claims a host only for a
    release that goes on;
    ``proof_of_release.py`` judges their results in the task.
    ``--federation-digest`` takes every file ``release/federation.py
    claim`` names, or the present core's alone without ``--monitoring``,
    which only checks it; ``host.sh`` leaves it out for a worker, whose
    stack host holds the stack's digest file. ``--monitoring`` makes
    ``apply`` count and remove the monitoring share; ``share`` always does.
    """
    command = argparse.ArgumentParser(prog=SCRIPT)
    actions = command.add_subparsers(dest="action", required=True)
    for action in ("check", "share", "apply"):
        host = actions.add_parser(action)
        host.add_argument("--login", required=True)
        host.add_argument("--app-control-user", required=True)
        host.add_argument("--backup-user", required=True)
        host.add_argument(
            "--agent-key",
            nargs=2,
            action="append",
            required=True,
            metavar=("TYPE", "BLOB"),
        )
        host.add_argument("--federation-digest", nargs="+", default=[])
        host.add_argument(
            "--monitoring",
            action="store_true",
            default=action == "share",
        )
    return command


def main(argv, stdout):
    """Args:
    argv: the command line without the program name.
    stdout: where the result line goes.

    Returns:
        The exit code: 0 done, 1 failed, 2 refused.
    """
    arguments = parser().parse_args(argv)
    return release(
        arguments,
        stdout,
        account_home,
        SUDOERS_DIR,
        keygen_accepts,
        Monitoring("/", arguments.federation_digest),
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdout))
