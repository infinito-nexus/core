from __future__ import annotations

import json
import sys
import time
from typing import TYPE_CHECKING

from utils.runner.jobs import queue_root, runner_rows
from utils.runner.role import queue_refusal

if TYPE_CHECKING:
    from pathlib import Path
    from typing import TextIO


def run(root: Path, now: float, out: TextIO, err: TextIO) -> int:
    """Args:
        root: the queue directory.
        now: the current time.
        out: where one JSON object per registered runner goes.
        err: where the note on an empty pool goes.

    Returns:
        0 once every runner is listed, 2 while this user cannot use the
        queue, 3 when no runner has registered.
    """
    refusals = queue_refusal(root)
    if refusals:
        print("\n".join(refusals), file=err)
        return 2
    rows = runner_rows(root, now)
    for row in rows:
        print(json.dumps(row, sort_keys=True), file=out)
    if not rows:
        print(
            f"[runner] no pool runner has registered with {root}; "
            "the infra runner deploys the pool with INFINITO_DEPLOY_VIA_POOL=true",
            file=err,
        )
        return 3
    return 0


def main() -> int:
    return run(queue_root(), time.time(), sys.stdout, sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
