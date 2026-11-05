"""Compare the common site config with the one the Frappe processes run with.

Gunicorn, the queue workers, the scheduler and socketio read
common_site_config.json once at start, so a rotated redis password reaches them
only through a restart. REVISION_FILE holds the revision of the declared config
they were last restarted with.

Runs on the stdin of the bench Python inside the ERPNext backend container, from
the sites directory, and prints one JSON line {"applied": <bool>, "current":
<bool>}: applied when common_site_config.json holds every declared value,
current when REVISION_FILE holds the revision of the declared config.

Environment:
    DECLARED_CONFIG: JSON object of the keys the configurator writes and their
        declared values; a port may arrive as a string or a number.
    RECORD: "true" or "false" in any case; "true" stores the declared revision
        in REVISION_FILE once the config is applied.
"""

import hashlib
import json
import os
from pathlib import Path

CONFIG = Path("common_site_config.json")
REVISION_FILE = Path(".common_site_config.revision")


def revision(declared):
    """Return the revision of a declared config.

    Args:
        declared: the declared keys and values.

    Returns:
        A SHA-256 hex digest that ignores whether a value is a string or a number.
    """
    canonical = json.dumps(
        {key: str(value) for key, value in declared.items()}, sort_keys=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main():
    declared = json.loads(os.environ["DECLARED_CONFIG"])
    record = {"true": True, "false": False}[os.environ["RECORD"].lower()]
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    applied = all(str(config.get(key)) == str(value) for key, value in declared.items())
    wanted = revision(declared)
    current = (
        REVISION_FILE.is_file() and REVISION_FILE.read_text(encoding="utf-8") == wanted
    )
    if record and applied and not current:
        REVISION_FILE.write_text(wanted, encoding="utf-8")
    print(json.dumps({"applied": applied, "current": current}))


if __name__ == "__main__":
    main()
