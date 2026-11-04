#!/usr/bin/env python3
"""Speak one MCP initialize handshake to a stdio server and report its name.

The Blender add-on does not have to be running: a server that cannot reach
Blender still has to complete the protocol handshake, and only the handshake
proves the command on PATH is an MCP server rather than something that merely
starts. Tool calls are deliberately not attempted, because they need a live
Blender and would turn a contract test into a GUI test.

Args:
    argv[1]: the server command to spawn.

Exit:
    0 with the advertised server name on stdout, 1 with the reason on stderr.
"""

from __future__ import annotations

import json
import subprocess
import sys

REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "infinito-cli-test", "version": "1"},
    },
}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: initialize.py <server-command>", file=sys.stderr)
        return 1

    payload = json.dumps(REQUEST) + "\n"
    try:
        proc = subprocess.run(
            [sys.argv[1]],
            input=payload,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except OSError as exc:
        print(f"cannot spawn {sys.argv[1]}: {exc}", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print(f"{sys.argv[1]} did not answer initialize within 60s", file=sys.stderr)
        return 1

    for line in proc.stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") != 1:
            continue
        if "error" in message:
            print(f"server refused initialize: {message['error']}", file=sys.stderr)
            return 1
        name = message.get("result", {}).get("serverInfo", {}).get("name", "")
        if not name:
            print(f"initialize carried no serverInfo.name: {message}", file=sys.stderr)
            return 1
        print(name)
        return 0

    print(
        f"no initialize response on stdout; stderr was: {proc.stderr.strip()[:400]}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
