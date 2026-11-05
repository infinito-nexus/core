from __future__ import annotations

import json
import os
import sys

from utils.cache.evict import (
    CacheConfigError,
    build_cache_usage,
    load_settings,
    run_command,
    status,
    usages,
)


def main() -> int:
    try:
        settings = load_settings(os.environ)
    except CacheConfigError as exc:
        print(f"[cache-status] {exc}; run 'make dotenv'", file=sys.stderr)
        return 2
    for row in status(settings, usages(settings, build_cache_usage(run_command))):
        print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
