#!/usr/bin/env python3
"""Fail when a hadolint SARIF report contains warnings or errors."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    sarif_path = Path(sys.argv[1] if len(sys.argv) > 1 else "hadolint-results.sarif")

    with sarif_path.open("r", encoding="utf-8") as handle:
        sarif = json.load(handle)

    results = sarif.get("runs", [{}])[0].get("results", [])
    levels = [result.get("level", "") for result in results]
    warnings = sum(1 for level in levels if level == "warning")
    errors = sum(1 for level in levels if level == "error")

    print(f"SARIF results: total={len(results)} warnings={warnings} errors={errors}")

    return 1 if warnings + errors > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
