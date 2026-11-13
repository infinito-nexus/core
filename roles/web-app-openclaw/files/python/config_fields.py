from __future__ import annotations

import json
import sys
from pathlib import Path

MISSING = object()
EACH = "*"


def held(document, path):
    """
    Args:
        document: the parsed config file.
        path: the keys that lead to the setting; a ``*`` key stands for every
            key of the mapping it reaches.

    Returns:
        The setting, or ``MISSING`` when the file does not hold the path; at a
        ``*`` key, each key of the mapping mapped to what the rest of the path
        holds below it, so only that part of each entry leaves the file, and
        no entry at all when the file does not reach the ``*`` key.
    """
    node = document
    for index, step in enumerate(path):
        if not isinstance(node, dict) or (step != EACH and step not in node):
            return {} if EACH in path[index:] else MISSING
        if step == EACH:
            below = {key: held(child, path[index + 1 :]) for key, child in node.items()}
            return {key: value for key, value in below.items() if value is not MISSING}
        node = node[step]
    return node


def fields(config, paths):
    """
    Args:
        config: the config file on the host.
        paths: each managed field mapped to its key path in the file.

    Returns:
        Each field whose path the file holds, mapped to its value; nothing for
        a missing file or one that is no JSON document.
    """
    if not config.is_file():
        return {}
    try:
        document = json.loads(config.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    found = {field: held(document, path) for field, path in paths.items()}
    return {field: value for field, value in found.items() if value is not MISSING}


def main():
    print(json.dumps(fields(Path(sys.argv[1]), json.load(sys.stdin))))


if __name__ == "__main__":
    main()
