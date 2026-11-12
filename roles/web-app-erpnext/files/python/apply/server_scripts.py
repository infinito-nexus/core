"""Align server_script_enabled in common_site_config.json with the declared switch.

Frappe reads the key only from common_site_config.json and tests it with bool(),
so it is written as the integer 1 or 0: the string "0" that a plain
`bench set-config -g` stores would leave server scripts enabled.

Runs on the stdin of the bench Python inside the ERPNext backend container, from
the sites directory, and prints one JSON line {"changed": <bool>}.

Environment:
    SERVER_SCRIPTS_ENABLED: "true" or "false" in any case, the declared switch.
"""

import json
import os
from pathlib import Path

KEY = "server_script_enabled"
CONFIG = Path("common_site_config.json")


def main():
    enabled = {"true": 1, "false": 0}[os.environ["SERVER_SCRIPTS_ENABLED"].lower()]
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    changed = config.get(KEY) != enabled
    if changed:
        config[KEY] = enabled
        staged = CONFIG.with_name(CONFIG.name + ".tmp")
        staged.write_text(
            json.dumps(config, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        staged.replace(CONFIG)
    print(json.dumps({"changed": changed}))


if __name__ == "__main__":
    main()
