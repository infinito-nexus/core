from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.evict import free_bytes
from utils.runner.count import (
    CALIBRATION,
    CountError,
    Host,
    floor,
    growth,
    load_budget,
    override,
    report,
    total_ram,
)


def _cache_rows() -> list[dict]:
    done = subprocess.run(
        [sys.executable, "-m", "cli.meta.cache.status"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise CountError(f"make cache-status failed: {done.stderr.strip()}")
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()]


def _host(rows: list[dict]) -> Host:
    paths = [Path(row["path"]) for row in rows if row["path"]]
    cpus = os.cpu_count()
    if not paths or cpus is None:
        raise CountError("no cache reports a path, or the CPU count is unknown")
    with Path("/proc/meminfo").open(encoding="utf-8") as handle:
        ram = total_ram(handle.read())
    return Host(ram=ram, cpus=cpus, free=free_bytes(paths))


def main() -> int:
    try:
        pinned = override(os.environ)
        floor_bytes = floor(os.environ)
        budget = load_budget(CALIBRATION)
        rows = _cache_rows()
        result = report(_host(rows), budget, growth(rows), floor_bytes, pinned)
    except CountError as exc:
        print(f"[runner-count] {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
