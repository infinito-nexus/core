"""Lint: a workflow file name declares what starts the workflow.

Scope
=====
Every `.github/workflows/*.yml`.

Rule
====
The file name carries exactly one of three prefixes, derived from the `on:`
block and checked in this order:

* ``cron-``  the workflow has a `schedule` trigger. Its `name:` must also start
  with ⏰, so a run nobody triggered is recognisable in the Actions list.
* ``call-``  no schedule, but a `workflow_call` trigger: a pipeline stage that
  only another workflow starts. An extra `workflow_dispatch` for debugging does
  not change that.
* ``entry-`` neither: a repository event or a human starts it.

Why
===
The first question about any workflow is what starts it, and the directory
otherwise mixes entry points, reusable stages and scheduled jobs into one flat
list sorted by topic.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from ruamel.yaml import YAML

from utils.cache.files import iter_project_files

from . import PROJECT_ROOT

_WORKFLOW_DIR = ".github/workflows/"
_CLOCK = "⏰"
_SCHEDULE = "cron-"
_REUSABLE = "call-"
_ENTRY = "entry-"

_yaml = YAML(typ="safe")
_yaml.allow_duplicate_keys = True


def _load(path: str):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return _yaml.load(handle)
    except Exception:
        return None


def _trigger_names(data) -> set[str]:
    """The keys of the `on:` block, which YAML 1.1 parsers hand back under `True`."""
    if not isinstance(data, dict):
        return set()
    for key in ("on", True):
        if key in data:
            triggers = data[key]
            if isinstance(triggers, dict):
                return {str(name) for name in triggers}
            if isinstance(triggers, list):
                return {str(name) for name in triggers}
            if triggers is not None:
                return {str(triggers)}
    return set()


def expected_prefix(data) -> str:
    triggers = _trigger_names(data)
    if "schedule" in triggers:
        return _SCHEDULE
    if "workflow_call" in triggers:
        return _REUSABLE
    return _ENTRY


def issues(rel: str, data) -> list[str]:
    found: list[str] = []
    wanted = expected_prefix(data)
    name = Path(rel).name
    if not name.startswith(wanted):
        carried = next(
            (p for p in (_SCHEDULE, _REUSABLE, _ENTRY) if name.startswith(p)),
            "no prefix",
        )
        found.append(f"carries {carried!r}, must carry {wanted!r}")
    if wanted == _SCHEDULE:
        title = data.get("name") if isinstance(data, dict) else None
        if not isinstance(title, str) or not title.startswith(_CLOCK):
            found.append(f"name: must start with {_CLOCK}")
    return found


class TestWorkflowTriggerPrefix(unittest.TestCase):
    def test_workflow_names_declare_their_trigger(self) -> None:
        offenders: list[str] = []
        for path_str in iter_project_files(extensions=(".yml", ".yaml")):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith(_WORKFLOW_DIR):
                continue
            found = issues(rel, _load(path_str))
            if found:
                offenders.append(f"{rel}: {'; '.join(found)}")

        if offenders:
            self.fail(
                f"{len(offenders)} workflow(s) break the prefix convention. A "
                f"workflow file MUST start with {_SCHEDULE!r} when it has a "
                f"`schedule` trigger (and then carry a {_CLOCK} name), with "
                f"{_REUSABLE!r} when it is only reachable through `workflow_call`, "
                f"and with {_ENTRY!r} otherwise:\n" + "\n".join(sorted(offenders))
            )


if __name__ == "__main__":
    unittest.main()
