"""Lint: every task / job / step / workflow name starts with an emoji (a
non-alphanumeric character) and is at most 80 characters long.

Scope
=====
* Ansible **task** names: every `name:` in a task list inside `roles/*/tasks/**`,
  `roles/*/handlers/**`, `playbooks/**` or top-level `tasks/**` YAML (recursing
  block / rescue / always / handlers / pre_tasks / post_tasks). Module-argument
  `name:` keys are NOT walked.
* GitHub Actions: the workflow `name`, every job `name` (the "runner"), every
  step `name`, and every `workflow_dispatch` input `description` in
  `.github/workflows/*.yml`.

Why
===
* Names must begin with an emoji (NOT `0-9` / `a-z` / `A-Z`) so a human scanning
  `ansible-playbook` output or a CI step list spots each line instantly.
* Names must stay <= 80 chars so they fit one terminal / CI log line without
  wrapping.
* A `workflow_dispatch` input description is read in the dispatch form the same
  way, one line per input, so it carries the same two rules. `workflow_call`
  inputs are wiring between workflows, never rendered for a human, and stay out.

A single lint holds all of this: a second, laxer 120-char rule over the same
files could never fire before this one and only added false-positive surface by
matching `name:` keys that were no task at all.
"""

from __future__ import annotations

import string
import unittest
from pathlib import Path

from ruamel.yaml import YAML

from utils.cache.files import iter_project_files

from . import PROJECT_ROOT

_MAX_LEN = 80
_ALNUM = frozenset(string.ascii_letters + string.digits)
_TASK_LIST_KEYS = (
    "block",
    "rescue",
    "always",
    "tasks",
    "pre_tasks",
    "post_tasks",
    "handlers",
)

_yaml = YAML(typ="safe")
_yaml.allow_duplicate_keys = True


def _load(path: str):
    """The parsed YAML, or ``None`` when it does not parse.

    Files whose Jinja or tags defeat a safe parse are policed by the yaml lint
    elsewhere; skipping them here keeps this lint off unrelated noise.
    """
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return _yaml.load(handle)
    except Exception:
        return None


def _iter_task_names(node):
    """Yield task/play/block names, descending ONLY task-list keys so a
    module-argument `name:` (e.g. `apt: {name: nginx}`) is never collected."""
    if isinstance(node, list):
        for item in node:
            yield from _iter_task_names(item)
    elif isinstance(node, dict):
        if isinstance(node.get("name"), str):
            yield node["name"]
        for key in _TASK_LIST_KEYS:
            if key in node:
                yield from _iter_task_names(node[key])


def _iter_dispatch_descriptions(data):
    """The input descriptions of the workflow's own dispatch form.

    ``on:`` parses as the boolean ``True`` under YAML 1.1, so both spellings
    are looked up rather than only the quoted one.
    """
    triggers = data.get("on") if isinstance(data.get("on"), dict) else data.get(True)
    dispatch = triggers.get("workflow_dispatch") if isinstance(triggers, dict) else None
    inputs = dispatch.get("inputs") if isinstance(dispatch, dict) else None
    for spec in (inputs or {}).values():
        if isinstance(spec, dict) and isinstance(spec.get("description"), str):
            yield spec["description"]


def _iter_gha_names(data):
    if not isinstance(data, dict):
        return
    if isinstance(data.get("name"), str):
        yield data["name"]
    yield from _iter_dispatch_descriptions(data)
    jobs = data.get("jobs")
    if isinstance(jobs, dict):
        for job in jobs.values():
            if not isinstance(job, dict):
                continue
            if isinstance(job.get("name"), str):
                yield job["name"]
            steps = job.get("steps")
            if isinstance(steps, list):
                for step in steps:
                    if isinstance(step, dict) and isinstance(step.get("name"), str):
                        yield step["name"]


def _issues(name: str) -> list[str]:
    found: list[str] = []
    if len(name) > _MAX_LEN:
        found.append(f"{len(name)}>{_MAX_LEN} chars")
    if not name or name[0] in _ALNUM:
        found.append("no emoji prefix")
    return found


def _in_scope(rel: str):
    if rel.startswith(".github/workflows/"):
        return _iter_gha_names
    if rel.startswith(("tasks/", "playbooks/")) or (
        rel.startswith("roles/") and ("/tasks/" in rel or "/handlers/" in rel)
    ):
        return _iter_task_names
    return None


class TestNameEmojiAndLength(unittest.TestCase):
    def test_names_start_with_emoji_and_fit_one_line(self) -> None:
        offenders: list[str] = []
        for path_str in iter_project_files(extensions=(".yml", ".yaml")):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            extractor = _in_scope(rel)
            if extractor is None:
                continue
            for name in extractor(_load(path_str)):
                issues = _issues(name)
                if issues:
                    offenders.append(f"{rel}: [{', '.join(issues)}] {name[:60]!r}")

        if offenders:
            shown = sorted(offenders)
            more = f"\n... and {len(shown) - 60} more" if len(shown) > 60 else ""
            self.fail(
                f"{len(offenders)} task / handler / step / job / workflow name(s) "
                "or dispatch input description(s) break the convention. Each MUST "
                "start with an emoji (not 0-9/a-z/A-Z) and be <= 80 chars. Fix: "
                "shorten the wording and pick a fitting emoji prefix (e.g. "
                "'🔧 Configure ...', '🧹 Clean ...', '✅ Assert ...'); move a long "
                "rationale into the role README or the workflow README:\n"
                + "\n".join(shown[:60])
                + more
            )


if __name__ == "__main__":
    unittest.main()
