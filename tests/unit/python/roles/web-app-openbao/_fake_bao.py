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


def config(verb, args):
    state = load()
    path = positional(args)[0]
    stored = state.setdefault("config", {}).setdefault(path, {"max_versions": "0"})
    if verb == "read":
        print(stored[option(args, "-field")])
        return
    if os.environ.get("FAKE_BAO_WRITE_FAIL") == "1":
        sys.stderr.write("Error writing data to " + path + ": Code: 403\\n")
        sys.exit(2)
    for pair in positional(args)[1:]:
        key, _, value = pair.partition("=")
        stored[key] = value
    state.setdefault("writes", []).append(path)
    save(state)


def rendered(value):
    if isinstance(value, dict):
        return "map[" + " ".join(key + ":" + rendered(value[key]) for key in sorted(value)) + "]"
    if isinstance(value, list):
        return "[" + " ".join(rendered(item) for item in value) + "]"
    return str(value)


def auth(verb, args):
    state = load()
    held = state.setdefault("roles", {})
    path = positional(args)[0]
    if verb == "list":
        if os.environ.get("FAKE_BAO_DENY") == "1":
            denied(path)
        prefix = path + "/"
        names = sorted(name[len(prefix):] for name in held if name.startswith(prefix))
        if not names:
            missing(path)
        print("Keys")
        print("----")
        for name in names:
            print(name)
        return
    if path not in held:
        missing(path)
    if verb == "read":
        print(rendered(held[path][option(args, "-field")]))
        return
    if verb == "delete":
        del held[path]
        state.setdefault("removed", []).append(path)
        save(state)
        return
    sys.exit(95)


def policy(args):
    state = load()
    held = state.setdefault("policies", [])
    verb = args[0]
    if verb == "list":
        for name in sorted(held):
            print(name)
        return
    name = positional(args[1:])[0]
    if os.environ.get("FAKE_BAO_POLICY_DENY") == "1":
        denied("sys/policies/acl/" + name)
    if name not in held:
        sys.stderr.write("No policy named: " + name + "\\n")
        sys.exit(2)
    if verb == "read":
        print("path \\"" + name + "\\" {}")
        return
    if verb == "delete":
        held.remove(name)
        state.setdefault("removed", []).append("policy/" + name)
        save(state)
        return
    sys.exit(96)


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
    elif args[0] == "policy":
        policy(args[1:])
    elif args[0] in ("list", "read", "delete") and args[-1].startswith("auth/"):
        auth(args[0], args[1:])
    elif args[0] in ("read", "write"):
        config(args[0], args[1:])
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


def write_access(
    scratch: Path, roles: dict[str, dict[str, object]], policies: list[str]
) -> None:
    """
    Args:
        scratch: the directory ``install`` placed the fakes in.
        roles: per role path from ``auth/`` on, the fields ``bao read -field``
            prints the way the Go CLI does: a list as ``[a b]``, a map as
            ``map[key:value]``.
        policies: the names ``bao policy list`` prints.
    """
    state = read_state(scratch)
    state["roles"] = roles
    state["policies"] = policies
    (scratch / "state.json").write_text(json.dumps(state), encoding="utf-8")


def read_state(scratch: Path) -> dict:
    return json.loads(
        (scratch / "state.json").read_text(encoding="utf-8")  # nocheck: cache-read
    )


def run(
    command: list[str], env: dict[str, str], stdin: str = "", cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=stdin,
        capture_output=True,
        check=False,
        cwd=cwd,
        env=env,
        text=True,
        timeout=60,
    )
