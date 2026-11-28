from __future__ import annotations

import json
import os
import sys
import time
from functools import partial

from utils.cache import pin
from utils.cache.artefacts import artefacts
from utils.cache.evict import (
    CacheConfigError,
    evict,
    free_bytes,
    load_settings,
    status,
    usages,
)
from utils.cache.eviction.docker import build_cache_usage, run_command, tools_running
from utils.cache.eviction.nexus import nexus_from_env

POLL_SECONDS = 2.0
TASK_TIMEOUT_SECONDS = 3600.0


def declared_digests() -> frozenset[str] | None:
    """Return the store entries no eviction may remove.

    The artefacts this checkout declares and those the pinned commit declares,
    so neither an older branch nor a newer one evicts what the other deploys.
    None while the pin cannot be read.
    """
    pinned = pin.pinned_digests(os.environ)
    if pinned is None:
        return None
    return pinned | {item.sha256 for item in artefacts()}


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
        declared_digests,
    )
    if code == 0:
        for row in status(settings, usages(settings, build_cache_usage(run_command))):
            print(json.dumps(row, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
