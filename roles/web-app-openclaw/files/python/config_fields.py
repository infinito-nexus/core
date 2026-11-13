from __future__ import annotations

import json
import sys
from pathlib import Path

MISSING = object()


def held(document, path):
    """
    Args:
        document: the parsed config file.
        path: the keys that lead to the setting.

    Returns:
        The setting, or ``MISSING`` when the file does not hold the path.
    """
    node = document
    for step in path:
        if not isinstance(node, dict) or step not in node:
            return MISSING
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
