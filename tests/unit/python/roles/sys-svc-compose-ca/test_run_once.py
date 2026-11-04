"""sys-svc-compose-ca decides once per host and records that decision."""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, ClassVar

from jinja2 import Environment, StrictUndefined

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.invocations import NESTED_KEYS
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_VARS_MAIN

if TYPE_CHECKING:
    from collections.abc import Iterator

ROLE = PROJECT_ROOT / "roles" / "sys-svc-compose-ca"
FLAG = "utils/once/flag.yml"
CORE = "00_core.yml"


def _ansible_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"y", "yes", "true", "on", "1"}
    return bool(value)


def _environment() -> Environment:
    env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - renders ansible expressions, not markup
    env.filters["bool"] = _ansible_bool
    return env


def _applicable(current: str, play: list[str], injected: set[str]) -> bool:
    """Render the role's applicability for one stack of a play.

    Args:
        current: the application whose compose stack includes the role.
        play: the applications of ``CURRENT_PLAY_APPLICATIONS``, in play order.
        injected: the applications ``lookup('ca_injected', ...)`` answers true for.
    """
    env = _environment()

    def lookup(name: str, application_id: str) -> bool:
        if name != "ca_injected":
            raise AssertionError(f"unexpected lookup {name!r}")
        return application_id in injected

    env.globals["lookup"] = lookup
    expression = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))["_compose_ca_applicable"]
    rendered = env.from_string(expression).render(
        application_id=current,
        CURRENT_PLAY_APPLICATIONS={app: {} for app in play},
    )
    return _ansible_bool(rendered)


def _holds(condition: str, facts: dict) -> bool:
    return _ansible_bool(
        _environment().from_string("{{ (" + condition + ") | bool }}").render(**facts)
    )


def _conditions(task: dict) -> list[str]:
    when = task.get("when", [])
    return when if isinstance(when, list) else [when]


def _leaves(tasks: list[dict]) -> Iterator[dict]:
    for task in tasks:
        nested = [key for key in NESTED_KEYS if key in task]
        if not nested:
            yield task
        for key in nested:
            yield from _leaves(task[key])


def _run(tasks: list[dict], facts: dict, gates: list[str]) -> Iterator[dict]:
    for task in tasks:
        conditions = gates + _conditions(task)
        nested = [key for key in NESTED_KEYS if key in task]
        if nested:
            for key in nested:
                yield from _run(task[key], facts, conditions)
            continue
        if not all(_holds(c, facts) for c in conditions):
            continue
        yield task
        if task.get("include_tasks") == CORE:
            yield from _leaves(
                load_yaml_any(str(ROLE / "tasks" / CORE), default_if_missing=[])
            )


def _trace(*, applicable: bool, flagged: bool = False) -> list[dict]:
    """Walk tasks/main.yml the way Ansible runs it for one include.

    Args:
        applicable: the value ``_compose_ca_applicable`` resolves to.
        flagged: whether ``run_once_sys_svc_compose_ca`` is already set.
    """
    facts: dict = {"_compose_ca_applicable": applicable}
    if flagged:
        facts["run_once_sys_svc_compose_ca"] = True
    main = load_yaml_any(str(ROLE / ROLE_FILE_TASKS_MAIN), default_if_missing=[])
    return list(_run(main, facts, []))


def _flag_sets(trace: list[dict]) -> int:
    return sum(1 for task in trace if task.get("include_tasks") == FLAG)


def _runs_core(trace: list[dict]) -> bool:
    return any(task.get("include_tasks") == CORE for task in trace)


class TestTheDecisionCoversThePlay(unittest.TestCase):
    PLAY: ClassVar[list[str]] = ["svc-registry-cache", "svc-db-qdrant", "web-app-gitea"]

    def test_a_stack_served_over_the_self_signed_ca_needs_the_assets(self) -> None:
        self.assertTrue(_applicable("web-app-gitea", self.PLAY, {"web-app-gitea"}))

    def test_a_service_ahead_of_a_self_signed_app_installs_the_assets_for_it(
        self,
    ) -> None:
        self.assertTrue(_applicable("svc-registry-cache", self.PLAY, {"web-app-gitea"}))

    def test_a_play_without_a_self_signed_app_needs_no_assets(self) -> None:
        self.assertFalse(_applicable("svc-registry-cache", self.PLAY, set()))

    def test_a_stack_outside_the_play_list_still_counts(self) -> None:
        self.assertTrue(_applicable("web-app-matrix", [], {"web-app-matrix"}))


class TestBothPathsSetTheRunOnceFlag(unittest.TestCase):
    def test_the_not_applicable_path_sets_the_flag(self) -> None:
        self.assertEqual(_flag_sets(_trace(applicable=False)), 1)

    def test_the_not_applicable_path_installs_nothing(self) -> None:
        self.assertFalse(_runs_core(_trace(applicable=False)))

    def test_the_applicable_path_installs_the_assets(self) -> None:
        self.assertTrue(_runs_core(_trace(applicable=True)))

    def test_the_applicable_path_sets_the_flag_once(self) -> None:
        self.assertEqual(_flag_sets(_trace(applicable=True)), 1)

    def test_a_flagged_host_runs_nothing_more(self) -> None:
        for applicable in (True, False):
            with self.subTest(applicable=applicable):
                self.assertEqual(_trace(applicable=applicable, flagged=True), [])


if __name__ == "__main__":
    unittest.main()
