"""Create the cache base as the calling user, or refuse with exit status 2.

The workspace workflow runs it before its job container mounts the base, where
no ``make infra-up`` has run yet. It uses the same
:func:`utils.infra.prepare_base` as ``make infra-up`` and imports nothing
outside the standard library, so a bare host interpreter runs it.
"""

from __future__ import annotations

import sys

from utils.env.handlers.infinito.cache.paths import base
from utils.infra import prepare_base


def main() -> int:
    lines = prepare_base(base())
    if lines:
        print("\n".join(lines), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
