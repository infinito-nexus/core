from __future__ import annotations

import shlex
from itertools import pairwise
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml

if TYPE_CHECKING:
    from pathlib import Path


def step_options(workflow: Path, job: str) -> list[set[tuple[str, str]]]:
    """
    Args:
        workflow: a GitHub Actions workflow file.
        job: the id of one of its jobs.

    Returns:
        Per step of the job, in order, every shell word of its run script
        paired with the word after it, as an option and its value; line
        continuations are joined first, and a step without a script has none.
    """
    steps = load_yaml(workflow)["jobs"][job]["steps"]
    return [
        set(pairwise(shlex.split(step.get("run", "").replace("\\\n", " "))))
        for step in steps
    ]
