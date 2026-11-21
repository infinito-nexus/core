"""CLI entry: `python -m cli.meta.cache` (run by `make dotenv`)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from utils.cache import pin
from utils.cache.render import render_artifacts
from utils.env.handlers.infinito.cache.conf import KEY, RELATIVE

from . import PROJECT_ROOT as REPO_ROOT


def _conf_path() -> Path:
    configured = os.environ.get(KEY, "").strip()
    if configured:
        return Path(configured)
    return REPO_ROOT / RELATIVE


def main() -> int:
    written = render_artifacts(REPO_ROOT, _conf_path(), pin.served_hosts(os.environ))
    print(
        f"Rendered {len(written)} cache file(s) from the cache: declarations",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
