from __future__ import annotations

import json
import sys
from pathlib import Path

VARIABLE = "TOOL_SERVER_CONNECTIONS"


def unquoted(value):
    """
    Args:
        value: the right-hand side of the assignment as the env file holds it.

    Returns:
        The value without the compose-style quoting dotenv_quote adds, or
        the value itself when it is not quoted.
    """
    if len(value) < 2 or not (value.startswith('"') and value.endswith('"')):
        return value
    inner = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return inner.replace("$$", "$")


def connections(env_file):
    """
    Args:
        env_file: the env file of the Open WebUI container.

    Returns:
        Each tool server id the file connects to, mapped to its URL and
        nothing else of the entry; an empty mapping for a file without the
        variable, and None for a missing file or a value that is no JSON
        list.
    """
    if not env_file.is_file():
        return None
    prefix = f"{VARIABLE}="
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        try:
            entries = json.loads(unquoted(stripped[len(prefix) :]))
        except ValueError:
            return None
        if not isinstance(entries, list):
            return None
        return {
            str((entry.get("info") or {}).get("id")): entry.get("url")
            for entry in entries
            if isinstance(entry, dict)
        }
    return {}


def main():
    print(json.dumps(connections(Path(sys.argv[1]))))


if __name__ == "__main__":
    main()
