from __future__ import annotations

import json
import os
import sys
import time
from functools import partial

from utils.cache.evict import (
    CacheConfigError,
    build_cache_usage,
    evict,
    free_bytes,
    load_settings,
    nexus_from_env,
    run_command,
    status,
    tools_running,
    usages,
)

POLL_SECONDS = 2.0
TASK_TIMEOUT_SECONDS = 3600.0


def main() -> int:
    try:
        settings = load_settings(os.environ)
    except CacheConfigError as exc:
        print(f"[cache-evict] {exc}; run 'make dotenv'", file=sys.stderr)
        return 2
    measured = usages(settings, build_cache_usage(run_command))
    paths = [cache.path for cache in settings.caches if cache.path is not None]
    code = evict(
        settings,
        measured,
        free_bytes(paths),
        time.time(),
        partial(tools_running, run_command),
        partial(nexus_from_env, os.environ, POLL_SECONDS, TASK_TIMEOUT_SECONDS),
        sys.stderr,
    )
    if code == 0:
        for row in status(settings, usages(settings, build_cache_usage(run_command))):
            print(json.dumps(row, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
