"""Args:
apply --dir <directory> --state <state file> --reload-url <url>: runs on the
    platform's Prometheus host. Writes or deletes the one scrape
    configuration file the state names, readable by the Prometheus
    container only, never another file, deletes the state file, and reloads
    Prometheus through its lifecycle endpoint when that file changed or an
    earlier reload for it failed, which its own marker file
    ``.<file>.reload-pending`` records until a reload succeeds. Prints ``changed``, ``kept``
    and ``reloaded`` as one JSON line; no credential reaches the output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

SCRIPT = "prometheus_instances.py"
FILE_NAME = re.compile(
    r"(?P<workspace>ws-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})__[A-Za-z0-9_.-]+\.yml"
)
RELOAD_MARKER = ".reload-pending"
PROMETHEUS_UID = 65534
FILE_MODE = 0o640
TIMEOUT = 30


class RefusedError(Exception):
    pass


def target(directory, state):
    """Args:
    directory: the directory Prometheus reads ``scrape_config_files`` from.
    state: ``workspace``, ``file`` and ``content``, None to delete the file.

    Returns:
        The path of the one scrape file the state names.

    Raises:
        RefusedError: the file is no file of the state's workspace.
    """
    match = FILE_NAME.fullmatch(state["file"])
    if not match or match["workspace"] != state["workspace"]:
        raise RefusedError(f"{state['file']} is no file of {state['workspace']}")
    return directory / state["file"]


def differs(path, content):
    """Args:
    path: the scrape file.
    content: its wanted text, None for no file.

    Returns:
        Whether :func:`reconcile` changes the file.
    """
    if content is None:
        return path.is_file()
    return not (path.is_file() and path.read_text(encoding="utf-8") == content)


def reconcile(directory, state, chown):
    """Args:
    directory: the directory Prometheus reads ``scrape_config_files`` from.
    state: ``workspace``, ``file`` and ``content``, None to delete the file.
    chown: ``os.chown`` or a stand-in.

    Returns:
        ``changed`` and ``kept``, whether the file stays.
    """
    path = target(directory, state)
    content = state["content"]
    if not differs(path, content):
        return {"changed": False, "kept": content is not None}
    if content is None:
        path.unlink()
        return {"changed": True, "kept": False}
    staged = directory / f".{state['file']}.tmp"
    staged.write_text(content, encoding="utf-8")
    chown(staged, 0, PROMETHEUS_UID)
    staged.chmod(FILE_MODE)
    staged.replace(path)
    return {"changed": True, "kept": True}


# Real I/O by default: __main__ passes none, tests pass stand-ins.
def reload(url, opener=urllib.request.urlopen):
    request = urllib.request.Request(url, data=b"", method="POST")  # noqa: S310 the loopback lifecycle endpoint of the platform deploy
    try:
        with opener(request, timeout=TIMEOUT) as response:
            if response.status != 200:
                raise RefusedError(f"the reload answered {response.status}")
    except OSError as error:
        raise RefusedError(f"the reload failed: {error}") from error


def converge(directory, state, url, chown, opener):
    """Returns:
    The outcome of :func:`reconcile` with ``reloaded``. The run reloads only
    for its own file: the marker ``.<file>.reload-pending`` is set before
    the file changes and cleared after a reload succeeded, so a run that
    dies between the change and the reload, or whose reload failed, leaves
    the marker its next run reloads for, while another host's failure
    never makes this run reload.
    """
    marker = directory / f".{state['file']}{RELOAD_MARKER}"
    if differs(target(directory, state), state["content"]):
        marker.touch()
    outcome = reconcile(directory, state, chown)
    outcome["reloaded"] = marker.exists()
    if outcome["reloaded"]:
        reload(url, opener)
        marker.unlink()
    return outcome


# Real I/O by default: __main__ passes none, tests pass stand-ins.
def main(argv, stdout=sys.stdout, chown=os.chown, opener=urllib.request.urlopen):
    parser = argparse.ArgumentParser(prog=SCRIPT)
    parser.add_argument("command", choices=["apply"])
    parser.add_argument("--dir", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--reload-url", required=True)
    args = parser.parse_args(argv)
    state_file = Path(args.state)
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    finally:
        state_file.unlink(missing_ok=True)
    try:
        outcome = converge(Path(args.dir), state, args.reload_url, chown, opener)
    except RefusedError as error:
        print(f"{SCRIPT}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(outcome, sort_keys=True), file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
