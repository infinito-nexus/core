"""
Args:
  block  the extracted production block, rewritten in place

Env (test.env):
  DOCS_TEST_HLTH_RUNTIME_SEVERITY  the stack host's sys-ctl-hlth-runtime severity, as JSON
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROLE = "sys-ctl-hlth-runtime"
VARS = '--vars "{'
APPLICATIONS = '\\"applications\\":'
DOUBLE_QUOTED = str.maketrans({"\\": "\\\\", '"': '\\"', "$": "\\$", "`": "\\`"})


def entry(severity: dict[str, str]) -> str:
    """
    Args:
        severity: ``{severity: action}`` of the stack host's ``sys-ctl-hlth-runtime``.

    Raises:
        ValueError: ``severity`` holds a single quote.
    """
    override = {
        "applications": {ROLE: {"services": {"runtime": {"severity": severity}}}}
    }
    text = json.dumps(override)[1:-1]
    if "'" in text:
        raise ValueError(f"{text} holds a single quote")
    return text.translate(DOUBLE_QUOTED) + ", "


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("block", type=Path)
    args = parser.parse_args(argv)

    block = args.block.read_text(encoding="utf-8")
    if block.count(VARS) != 1:
        raise SystemExit(
            "the block hands provision no single --vars object, "
            "so the hlth-runtime severity has nothing to attach to"
        )
    if APPLICATIONS in block:
        raise SystemExit(
            f"the block's provision --vars already carry {APPLICATIONS}, "
            "and a second one would replace it"
        )

    severity = json.loads(os.environ["DOCS_TEST_HLTH_RUNTIME_SEVERITY"])
    print(
        f"=== Judging the target's runtime scan by the stack host's {json.dumps(severity)} ==="
    )
    args.block.write_text(block.replace(VARS, VARS + entry(severity)), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
