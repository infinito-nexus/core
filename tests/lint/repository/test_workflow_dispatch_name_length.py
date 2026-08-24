"""Lint: a manually startable workflow carries a name short enough for the menu.

Scope
=====
Every `.github/workflows/*.yml` whose `on:` block declares `workflow_dispatch`.

Rule
====
Its `name:` is at most 25 characters.

Why
===
The dispatch menu ("Run workflow" in the Actions sidebar) lists every such
workflow in one narrow column. A longer name is cut off there, so the list
stops being scannable exactly where a human picks what to start. The `run-name:`
carries no such limit: it is read on the run itself, one per line, and MAY be
as long and explanatory as the run deserves.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from ruamel.yaml import YAML

from utils.cache.files import iter_project_files

from . import PROJECT_ROOT
from .test_workflow_trigger_prefix import trigger_names

_WORKFLOW_DIR = ".github/workflows/"
_DISPATCH = "workflow_dispatch"
_MAX_LEN = 25

_yaml = YAML(typ="safe")
_yaml.allow_duplicate_keys = True


def _load(path: str):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return _yaml.load(handle)
    except Exception:
        return None


def too_long(data) -> str | None:
    """The offending name, or ``None`` when the workflow keeps to the limit."""
    if not isinstance(data, dict) or _DISPATCH not in trigger_names(data):
        return None
    name = data.get("name")
    if isinstance(name, str) and len(name) > _MAX_LEN:
        return name
    return None


class TestWorkflowDispatchNameLength(unittest.TestCase):
    def test_dispatchable_workflow_names_fit_the_menu(self) -> None:
        offenders: list[str] = []
        for path_str in iter_project_files(extensions=(".yml", ".yaml")):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith(_WORKFLOW_DIR):
                continue
            name = too_long(_load(path_str))
            if name:
                offenders.append(f"{rel}: {name!r} is {len(name)} characters")

        if offenders:
            self.fail(
                f"{len(offenders)} workflow(s) with a `{_DISPATCH}` trigger carry "
                f"a `name:` longer than {_MAX_LEN} characters. The dispatch menu "
                f"lists them in one narrow column, so a longer name is truncated "
                f"there and the menu becomes unreadable exactly where a human "
                f"picks what to start. Shorten `name:`; the longer, explanatory "
                f"wording belongs in `run-name:`, which is read on the run itself "
                f"and MAY be as long as it needs to be:\n"
                + "\n".join(sorted(offenders))
            )


if __name__ == "__main__":
    unittest.main()
