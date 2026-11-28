from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = "release_host.py"
ROOT = "root"
SUDOERS_DIR = "/etc/sudoers.d"
KEYS_FILE = (".ssh", "authorized_keys")
KEY_TYPE = re.compile(r"^(ssh-|ecdsa-sha2-|sk-|rsa-sha2-)[A-Za-z0-9@.-]+$")
NEWLINE = "\n"
COUNTS = (
    "agent_keys",
    "app_control_keys",
    "app_control_sudoers",
    "backup_keys",
    "backup_sudoers",
)
NO_SHELL = frozenset({"command", "restrict"})
ENCODING = {"encoding": "utf-8", "errors": "surrogateescape"}


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
        if len(keep) != len(lines):
            writes.append((path, keep))
            removed["agent_keys"] += len(lines) - len(keep)
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


def release(arguments, stdout, home, sudoers_dir, accepts):
    """Args:
    arguments: the parsed ``apply`` command line.
    stdout: where the result line goes.
    home: the resolver of ``account_home``.
    sudoers_dir: the sudoers drop-in directory.
    accepts: the check of ``keygen_accepts``.

    Returns:
        0 once every write is done, 2 on a refusal, which writes nothing.
    """
    agent = {tuple(pair) for pair in arguments.agent_key}
    platform = (arguments.app_control_user, arguments.backup_user)
    try:
        writes, removed, kept = plan(
            arguments.login, agent, platform, home, sudoers_dir, accepts
        )
    except RefusedError as error:
        print(f"{SCRIPT}: {error}", file=sys.stderr)
        print(json.dumps({"refused": str(error)}), file=stdout)
        return 2
    apply(writes)
    print(json.dumps({"kept": kept, "removed": removed}, sort_keys=True), file=stdout)
    return 0


def parser():
    """Returns:
    The command line of ``apply``, run on the host as root;
    ``proof_of_release.py`` judges its result in the task.
    """
    command = argparse.ArgumentParser(prog=SCRIPT)
    actions = command.add_subparsers(dest="action", required=True)
    host = actions.add_parser("apply")
    host.add_argument("--login", required=True)
    host.add_argument("--app-control-user", required=True)
    host.add_argument("--backup-user", required=True)
    host.add_argument(
        "--agent-key", nargs=2, action="append", required=True, metavar=("TYPE", "BLOB")
    )
    return command


def main(argv, stdout):
    """Args:
    argv: the command line without the program name.
    stdout: where the result line goes.

    Returns:
        The exit code: 0 done, 2 refused.
    """
    arguments = parser().parse_args(argv)
    return release(arguments, stdout, account_home, SUDOERS_DIR, keygen_accepts)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdout))
