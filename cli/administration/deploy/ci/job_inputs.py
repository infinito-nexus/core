"""Read the ``##[group] Inputs`` block a called workflow prints into its job log."""

from __future__ import annotations

import re

_INPUT_RE = re.compile(r"^\S+\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*): ?(?P<value>.*)$")


def parse_inputs(log: str) -> dict[str, str]:
    """The ``##[group] Inputs`` block of a job log, as name -> value."""
    inputs: dict[str, str] = {}
    inside = False
    for line in log.splitlines():
        if line.endswith("##[group] Inputs"):
            inside = True
            continue
        if inside:
            if line.endswith("##[endgroup]"):
                break
            match = _INPUT_RE.match(line)
            if match:
                inputs[match["name"]] = match["value"].strip()
    return inputs
