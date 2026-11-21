from __future__ import annotations

import json
import os
import sys

from utils.cache import pin
from utils.cache.evict import CacheConfigError, load_settings, status, usages
from utils.cache.eviction.docker import build_cache_usage, run_command


def main() -> int:
    row = pin.status(os.environ)
    print(json.dumps(row, sort_keys=True), file=sys.stderr)
    if row["error"]:
        print(f"[cache-status] {row['error']}", file=sys.stderr)
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
