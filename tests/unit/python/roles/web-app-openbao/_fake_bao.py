from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

FAKE_CONTAINER = """#!/bin/sh
[ "$1" = exec ] || exit 99
shift
[ "$1" = -i ] && shift
shift
exec "$@"
"""

FAKE_BAO = """
import json
import os
import sys

STATE = os.environ["FAKE_BAO_STATE"]


def load():
    with open(STATE, encoding="utf-8") as handle:
        return json.load(handle)


def save(state):
    with open(STATE, "w", encoding="utf-8") as handle:
        json.dump(state, handle)


def option(args, name):
    for arg in args:
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return None


def positional(args):
    return [arg for arg in args if not arg.startswith("-")]


def missing(path):
    sys.stderr.write("No value found at " + path + "\\n")
    sys.exit(2)


def denied(path):
    sys.stderr.write("Error listing " + path + ": Code: 403. Errors: * permission denied\\n")
    sys.exit(2)


def kv(args):
    state = load()
    verb = args[0]
    mount = option(args, "-mount")
    if verb == "list":
        prefix = positional(args[1:])[0]
        if os.environ.get("FAKE_BAO_DENY") == "1":
            denied(mount + "/metadata/" + prefix)
        children = set()
        for key in state["kv"].get(mount, {}):
            if key.startswith(prefix):
                rest = key[len(prefix):]
                head, slash, _ = rest.partition("/")
                children.add(head + slash)
        if not children:
            missing(mount + "/metadata/" + prefix)
        print("Keys")
        print("----")
        for child in sorted(children):
            print(child)
        return
    if verb == "metadata" and args[1] == "delete":
        path = positional(args[2:])[0]
        state["kv"].setdefault(mount, {}).pop(path, None)
        state["deleted"].append(mount + "/" + path)
        save(state)
        return
    sys.exit(98)


def raft(args):
    mode = os.environ.get("FAKE_BAO_SNAPSHOT", "ok")
    if mode == "fail":
        sys.stderr.write("Error taking the snapshot: Code: 500\\n")
        sys.exit(2)
    with open(args[-1], "wb") as handle:
        if mode == "ok":
            handle.write(b"raft-snapshot-bytes")


def main(args):
    if args[0] == "kv":
        kv(args[1:])
    elif args[:3] == ["operator", "raft", "snapshot"]:
        raft(args[3:])
    else:
        sys.exit(97)


main(sys.argv[1:])
"""


def install(scratch: Path) -> dict[str, str]:
    """
    Args:
        scratch: an empty directory the fake ``container`` and ``bao`` and their state live in.

    Returns:
        The environment a command runs with to reach the fakes.
    """
    container = scratch / "container"
    container.write_text(FAKE_CONTAINER, encoding="utf-8")
    container.chmod(0o755)
    bao = scratch / "bao"
    bao.write_text(f"#!{sys.executable}\n{FAKE_BAO}", encoding="utf-8")
    bao.chmod(0o755)
    state = scratch / "state.json"
    if not state.exists():
        write_state(scratch, {})
    return {
        **os.environ,
        "PATH": f"{scratch}{os.pathsep}{os.environ['PATH']}",
        "FAKE_BAO_STATE": str(state),
    }


def write_state(scratch: Path, kv: dict[str, dict[str, list[str]]]) -> None:
    """
    Args:
        scratch: the directory ``install`` placed the fakes in.
        kv: per mount, the secret paths and their versions.
    """
    (scratch / "state.json").write_text(
        json.dumps({"kv": kv, "deleted": []}), encoding="utf-8"
    )


def read_state(scratch: Path) -> dict:
    return json.loads(
        (scratch / "state.json").read_text(encoding="utf-8")  # nocheck: cache-read
    )


def run(
    command: list[str], env: dict[str, str], stdin: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=stdin,
        capture_output=True,
        check=False,
        env=env,
        text=True,
        timeout=60,
    )
