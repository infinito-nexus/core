"""Token-store wipe helper.

The token store at ``/var/lib/infinito/secrets/tokens.yml`` survives
compose+volumes purges. Matrix-deploy variant transitions wipe an app's
persistent state but the stale token would otherwise be reused on the next
round (for example matomo's API probe in ``sys-front-inj-matomo``, whose
token-empty guard never fires while the prior round's token is still
present). The purge orchestrator invokes this module to drop the matching
``users.<user>.tokens.<app_id>`` entries alongside the entity-level wipe.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.paths import FILE_TOKENS

DEFAULT_TOKENS_FILE = FILE_TOKENS


def _resolve_tokens_file() -> Path:
    env_path = os.environ.get("FILE_TOKENS")
    return Path(env_path) if env_path else DEFAULT_TOKENS_FILE


def wipe_tokens(app_ids: list[str], tokens_file: Path | None = None) -> list[str]:
    """Remove ``users.<user>.tokens.<app_id>`` entries for *app_ids*.

    Returns the list of removed ``<user>.<app_id>`` keys (empty when the
    file is missing or no entries matched). The file is rewritten only
    when at least one entry was removed.
    """
    path = tokens_file or _resolve_tokens_file()
    if not path.exists():
        return []

    data = load_yaml_any(str(path), default_if_missing={}) or {}
    users = data.get("users") or {}

    removed: list[str] = []
    for user_key, user_data in users.items():
        if not isinstance(user_data, dict):
            continue
        tokens = user_data.get("tokens") or {}
        for app_id in app_ids:
            if app_id in tokens:
                del tokens[app_id]
                removed.append(f"{user_key}.{app_id}")

    if removed:
        dump_yaml(path, data)

    return removed


def main(argv: list[str]) -> int:
    if not argv:
        print(
            "usage: python -m utils.cleanup.tokens <APP_ID> [APP_ID ...]",
            file=sys.stderr,
        )
        return 2

    removed = wipe_tokens(argv)
    if removed:
        print(f">>> Wiped token entries: {', '.join(removed)}")
    else:
        print(">>> No token entries to wipe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
