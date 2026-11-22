from __future__ import annotations

import copy
import re
import unittest

from . import role_task
from ._spec_secrets_wiring import (
    HELPER_CALL,
    PARALLEL_SCRUB,
    PATH_FACT,
    PRUNE_ARGV,
    QUEUE_TASKS,
    RUNS_FACT,
    SECRETS_DIR,
    SECRETS_PATH,
    SECRETS_TASKS,
    SERIAL_SCRUB,
    STALE_DIR,
    SWEEP,
    TEMPLATE_EXISTS,
    command_argv,
    env_task,
    holds,
    job_violations,
    layout_violations,
    mount_violations,
    prune_violations,
    render,
    role_tasks,
    run_argv,
)

COLLECT = "04_collect.yml"
SERIAL_ONLY = "not (_playwright_dispatch | bool)"
MOUNT_CONDITION = "if (_playwright_secrets_template_stat.stat.exists | bool) else [])"
STAGED_REPORTS = (
    "(([_playwright_spec_secrets_path, 'reports'] | path_join)"
    " if (_playwright_secrets_template_stat.stat.exists | bool)"
    " else _playwright_pass_reports_dir)"
)
MASKER_TAIL = "(['--'] + TEST_E2E_PLAYWRIGHT_ARGUMENTS)"
OWN_COMMAND = "(['/bin/bash', '-lc', TEST_E2E_PLAYWRIGHT_COMMAND])"
UNCHECKED_ARGV = (
    "{{ ['python3', TEST_E2E_PLAYWRIGHT_TOOLS_DIR ~ '/spec_secrets.py', 'arguments'] }}"
)


def modules(tasks: list[dict]) -> list[str]:
    """Name the module of each task.

    Args:
        tasks: parsed tasks.

    Returns:
        Each task's ``ansible.*`` key.
    """
    return [next(key for key in task if key.startswith("ansible.")) for task in tasks]


def serial_violations(run_pass: list[dict]) -> list[str]:
    """Check the serial pass: run, settle the reports, remove, fail, archive.

    Args:
        run_pass: the parsed ``03_run_pass.yml``.

    Returns:
        One message per broken expectation.
    """
    problems = []
    at = next(i for i, t in enumerate(run_pass) if t["name"].startswith("🏃"))
    serial, later = run_pass[at], run_pass[at + 1 : at + 2]
    first = serial["block"][0]
    if (first.get("ansible.builtin.include_tasks"), first.get("when")) != (
        SECRETS_TASKS,
        TEMPLATE_EXISTS,
    ):
        problems.append("the serial run writes no secrets before its run")
    early = any(
        t.get("ansible.builtin.include_tasks") == COLLECT for t in serial["block"]
    )
    archive = later[0] if later else {}
    if early or (archive.get("ansible.builtin.include_tasks"), archive.get("when")) != (
        COLLECT,
        SERIAL_ONLY,
    ):
        problems.append("the serial run archives its reports before they are masked")
    guards = [task for task in serial.get("always", []) if "block" in task]
    if len(guards) != 1:
        return [*problems, "the serial run removes no secrets in its always section"]
    for exists, facts, expected in (
        (True, {PATH_FACT: SECRETS_DIR}, True),
        (True, {}, False),
        (True, {PATH_FACT: ""}, False),
        (False, {PATH_FACT: STALE_DIR}, False),
    ):
        stat = {"stat": {"exists": exists}}
        if (
            holds(guards[0]["when"], _playwright_secrets_template_stat=stat, **facts)
            != expected
        ):
            problems.append(f"the serial cleanup runs {not expected} for {facts}")
    block = guards[0]["block"]
    if modules(block) != [
        "ansible.builtin.command",
        "ansible.builtin.file",
        "ansible.builtin.fail",
    ]:
        return [*problems, "the serial run does not mask, remove and then fail"]
    scrub, removal, fail = block
    if scrub["ansible.builtin.command"].get("argv") != SERIAL_SCRUB:
        problems.append(
            "the serial scrub does not remove the container and mask the reports"
        )
    if scrub.get("ignore_errors") is not True or "when" in removal:
        problems.append("a failed serial masking skips the removal")
    if removal["ansible.builtin.file"] != {"path": SECRETS_PATH, "state": "absent"}:
        problems.append("the serial run removes another directory")
    registered = str(scrub.get("register"))
    states = [{registered: {"failed": failed}} for failed in (True, False)]
    if [holds(fail.get("when", "false"), **state) for state in states] != [True, False]:
        problems.append("a failed serial masking does not fail the pass")
    return problems


def outcome(always: list[dict], at: dict[str, int], failed: set[str]) -> list[str]:
    """Render what the parallel run does when the first of two runs fails.

    Args:
        always: the ``always`` section of the staging block.
        at: the index of each task by its role.
        failed: which of ``scrubs`` and ``removed`` failed for the first run.

    Returns:
        One message per wrong decision.
    """
    one, two = ["/run/1", "/reports/1"], ["/run/2", "/reports/2"]
    results = {
        str(always[at[kind]].get("register")): {
            "results": [
                {
                    "failed": kind in failed and run is one,
                    "playwright_spec_secrets_run": run,
                }
                for run in (one, two)
            ]
        }
        for kind in ("scrubs", "removed")
    }
    noted = always[at["note"]]["ansible.builtin.set_fact"]
    found = {name: render(text, **results) for name, text in noted.items()}
    problems = []
    if holds(always[at["fail"]].get("when", "false"), **found) != bool(failed):
        problems.append(f"a parallel run with {sorted(failed)} failed does not fail")
    for kind, name, path in (
        ("scrubs", "_playwright_unmasked", one[1]),
        ("removed", "_playwright_unremoved", one[0]),
    ):
        if found.get(name) != ([path] if kind in failed else []):
            problems.append(f"a failed {kind} names {found.get(name)}")
    unmasked = "scrubs" in failed
    archived = [
        holds(
            always[at["report"]].get("when", "true"),
            _playwright_run={},
            _playwright_pass_reports_dir=run[1],
            **found,
        )
        for run in (one, two)
    ]
    if archived != [not unmasked, True]:
        problems.append(
            f"a parallel run with {sorted(failed)} failed archives {archived}"
        )
    return problems


def parallel_violations(parallel: list[dict], orchestrate: list[dict]) -> list[str]:
    """Check the parallel run: settle after the containers, remove, note, fail.

    Args:
        parallel: the parsed ``01_setup/parallel.yml``.
        orchestrate: the parsed ``01_setup/orchestrate.yml``.

    Returns:
        One message per broken expectation.
    """
    problems = []
    start = next(t for t in parallel if t["name"].startswith("📝 Start"))
    if start["ansible.builtin.set_fact"].get(RUNS_FACT) != []:
        problems.append("the parallel run does not start with an empty scrub list")
    always = next(t for t in parallel if t["name"].startswith("📦")).get("always", [])
    looped = "{{ " + RUNS_FACT + " }}"
    checks = {
        "reaped": lambda t: t["name"].startswith("🧹 Remove any"),
        "scrubs": lambda t: (
            t.get("ansible.builtin.command", {}).get("argv") == PARALLEL_SCRUB
            and t.get("loop") == looped
        ),
        "removed": lambda t: (
            t.get("ansible.builtin.file") == SWEEP and t.get("loop") == looped
        ),
        "note": lambda t: (
            "_playwright_unmasked" in t.get("ansible.builtin.set_fact", {})
        ),
        "report": lambda t: t.get("ansible.builtin.include_tasks") == COLLECT,
        "fail": lambda t: (
            "ansible.builtin.fail" in t and "_playwright_unmasked" in str(t.get("when"))
        ),
    }
    at = {}
    for role, check in checks.items():
        found = [i for i, task in enumerate(always) if check(task)]
        at[role] = found[0] if len(found) == 1 else -1
    if -1 in (at["reaped"], at["removed"], at["note"], at["fail"]):
        return [*problems, "the parallel run removes no secrets after its containers"]
    if list(at.values()) != sorted(at.values()) or -1 in at.values():
        return [
            *problems,
            "the parallel run does not mask its files after its containers",
        ]
    if always[at["scrubs"]].get("ignore_errors") is not True:
        problems.append("a failed masking skips the parallel run's removal and reports")
    if always[at["removed"]].get("ignore_errors") is not True:
        problems.append("a failed removal skips the parallel run's reports")
    for failed in (set(), {"scrubs"}, {"removed"}):
        problems.extend(outcome(always, at, failed))
    if at["fail"] == len(always) - 1 or not always[at["fail"] + 1]["name"].startswith(
        "🛑"
    ):
        problems.append("the masking failure lands after the scheduler failure")
    return [*problems, *prune_violations(orchestrate)]


def queue_violations(queued: list[dict]) -> list[str]:
    """Check that a job falling back to the serial runner creates no directory.

    Args:
        queued: the parsed ``03_run_pass/queue.yml``.

    Returns:
        One message per probe outcome the include decides wrongly.
    """
    include, job = queued[0], next(t for t in queued if t["name"].startswith("📮"))
    if include.get("ansible.builtin.include_tasks") != SECRETS_TASKS:
        return ["a queued run writes no secrets before its run"]
    stat = {"stat": {"exists": True}}
    problems = []
    for probe, expected in (
        ({"skipped": True}, True),
        ({"rc": 0}, True),
        ({"rc": 1}, False),
    ):
        created = holds(
            include.get("when", "true"),
            _playwright_secrets_template_stat=stat,
            _playwright_probe=probe,
        )
        if created != expected or created != holds(
            job.get("when", "true"), _playwright_probe=probe
        ):
            problems.append(f"a probe of {probe} creates {created} without its job")
    return problems


def parallel_mutated(mutation: str) -> list[str]:
    """Break one piece of the parallel cleanup and check it.

    Args:
        mutation: which piece to break.

    Returns:
        The violations found.
    """
    parallel = copy.deepcopy(role_tasks("01_setup/parallel.yml"))
    orchestrate = copy.deepcopy(role_tasks("01_setup/orchestrate.yml"))
    always = next(t for t in parallel if t["name"].startswith("📦"))["always"]
    at = next(i for i, t in enumerate(always) if t["name"].startswith("🫥"))
    if mutation == "drop":
        always.pop(at + 1)
    elif mutation == "late":
        always.insert(at + 2, always.pop(at))
    elif mutation == "strict":
        always[at].pop("ignore_errors")
    elif mutation == "sweep":
        always[at + 1].pop("ignore_errors")
    elif mutation == "silent":
        always[at + 2]["ansible.builtin.set_fact"]["_playwright_unmasked"] = "{{ [] }}"
    elif mutation == "archive":
        report = next(
            t for t in always if t.get("ansible.builtin.include_tasks") == COLLECT
        )
        report["when"] = report["when"][:1]
    elif mutation == "early":
        at = next(i for i, t in enumerate(orchestrate) if command_argv(t) == PRUNE_ARGV)
        orchestrate.insert(0, orchestrate.pop(at))
    elif mutation == "unisolated":
        prune = next(t for t in orchestrate if command_argv(t) == PRUNE_ARGV)
        prune["ansible.builtin.command"]["argv"].remove("-I")
    else:
        orchestrate = [t for t in orchestrate if command_argv(t) != PRUNE_ARGV]
    return parallel_violations(parallel, orchestrate)


class TestSpecSecretsMount(unittest.TestCase):
    def test_only_a_role_with_the_template_gets_the_mount_and_the_switch(self) -> None:
        self.assertEqual(mount_violations(run_argv()), [])
        queued = role_task("03_run_pass.yml", "📬")["vars"]["_playwright_argv"]
        self.assertEqual(queued, run_argv())

    def test_the_role_level_env_file_is_untouched(self) -> None:
        self.assertEqual(env_task()["ansible.builtin.copy"]["mode"], "0644")
        self.assertNotIn("secrets", str(env_task()))

    def test_the_secrets_reach_the_run_directory_and_no_task_prints_one(self) -> None:
        self.assertEqual(layout_violations(role_tasks(SECRETS_TASKS)), [])

    def test_the_serial_pass_settles_removes_fails_and_then_archives(self) -> None:
        self.assertEqual(serial_violations(role_tasks("03_run_pass.yml")), [])

    def test_the_parallel_run_archives_only_masked_reports(self) -> None:
        problems = parallel_violations(
            role_tasks("01_setup/parallel.yml"), role_tasks("01_setup/orchestrate.yml")
        )
        self.assertEqual(problems, [])

    def test_a_job_left_to_the_serial_runner_creates_no_directory(self) -> None:
        self.assertEqual(queue_violations(role_tasks(QUEUE_TASKS)), [])

    def test_a_queued_job_keeps_the_masker_and_its_flags(self) -> None:
        content = role_task(QUEUE_TASKS, "📮")["ansible.builtin.copy"]["content"]
        self.assertEqual(job_violations(content), [])


class TestSpecSecretsMountNegativeControls(unittest.TestCase):
    def test_a_mount_without_the_template_condition_or_as_a_volume_is_caught(
        self,
    ) -> None:
        for old, new in (
            (MOUNT_CONDITION, "if true else [])"),
            (STAGED_REPORTS, "_playwright_pass_reports_dir"),
            (
                (
                    "'--mount', 'type=bind,src=' ~ _playwright_spec_secrets_path ~ "
                    "',dst=/run/spec-secrets,readonly'"
                ),
                "'-v', _playwright_spec_secrets_path ~ ':/run/spec-secrets:ro'",
            ),
            ("'--log-driver=none', ", ""),
        ):
            with self.subTest(old=old):
                self.assertEqual(run_argv().count(old), 1)
                self.assertNotEqual(mount_violations(run_argv().replace(old, new)), [])

    def test_a_secrets_run_that_renders_its_own_command_is_caught(self) -> None:
        self.assertEqual(run_argv().count(MASKER_TAIL), 1)
        rendered = run_argv().replace(MASKER_TAIL, OWN_COMMAND)
        self.assertIn(
            "a run with the template renders a command, not the masker",
            mount_violations(rendered),
        )

    def test_a_dropped_reset_salt_diff_temp_or_scrub_entry_is_caught(self) -> None:
        for mutation in (
            "reset",
            "keep",
            "salt",
            "diff",
            "remote_tmp",
            "no_log",
            "stdin",
            "runs",
            "serial",
            "check",
            "login",
            "ship",
        ):
            with self.subTest(mutation=mutation):
                tasks = copy.deepcopy(role_tasks(SECRETS_TASKS))
                hand = tasks[8]["ansible.builtin.copy"]
                if mutation == "reset":
                    tasks[0]["ansible.builtin.set_fact"] = {"unrelated": ""}
                elif mutation == "keep":
                    tasks[7]["ansible.builtin.assert"]["that"] = ["true"]
                elif mutation == "salt":
                    hand["content"] = hand["content"].split("\n", 1)[1]
                elif mutation == "diff":
                    tasks[8].pop("diff")
                elif mutation == "remote_tmp":
                    tasks[8]["vars"].pop("ansible_remote_tmp")
                elif mutation == "no_log":
                    tasks[9]["no_log"] = True
                elif mutation == "stdin":
                    tasks[9]["ansible.builtin.command"]["stdin"] = hand.pop("content")
                elif mutation == "runs":
                    tasks[6]["ansible.builtin.set_fact"][RUNS_FACT] = "{{ [] }}"
                elif mutation == "serial":
                    tasks[6].pop("when")
                elif mutation == "check":
                    tasks[3]["ansible.builtin.command"]["argv"] = UNCHECKED_ARGV
                elif mutation == "login":
                    tasks[4].pop("become")
                else:
                    tasks[2]["ansible.builtin.copy"]["src"] = HELPER_CALL
                self.assertNotEqual(layout_violations(tasks), [])

    def test_a_serial_cleanup_that_skips_hides_or_archives_too_early_is_caught(
        self,
    ) -> None:
        for mutation, message in (
            ("drop", "the serial run removes no secrets in its always section"),
            ("reverse", "the serial run does not mask, remove and then fail"),
            ("strict", "a failed serial masking skips the removal"),
            ("silent", "a failed serial masking does not fail the pass"),
            ("early", "the serial run archives its reports before they are masked"),
            (
                "stage",
                "the serial scrub does not remove the container and mask the reports",
            ),
        ):
            with self.subTest(mutation=mutation):
                run_pass = copy.deepcopy(role_tasks("03_run_pass.yml"))
                at = next(
                    i for i, t in enumerate(run_pass) if t["name"].startswith("🏃")
                )
                serial = run_pass[at]
                block = serial["always"][0]["block"]
                if mutation == "drop":
                    serial.pop("always")
                elif mutation == "reverse":
                    block.reverse()
                elif mutation == "strict":
                    block[0].pop("ignore_errors")
                elif mutation == "silent":
                    block[2]["when"] = "false"
                elif mutation == "early":
                    serial["block"].append(run_pass.pop(at + 1))
                else:
                    block[0]["ansible.builtin.command"]["argv"].insert(
                        4, "{{ _playwright_stage_dir }}"
                    )
                self.assertIn(message, serial_violations(run_pass))

    def test_a_parallel_cleanup_that_skips_hides_or_ships_a_failure_is_caught(
        self,
    ) -> None:
        for mutation, message in (
            ("drop", "the parallel run removes no secrets after its containers"),
            ("late", "the parallel run does not mask its files after its containers"),
            ("strict", "a failed masking skips the parallel run's removal and reports"),
            ("sweep", "a failed removal skips the parallel run's reports"),
            ("silent", "a parallel run with ['scrubs'] failed does not fail"),
            ("archive", "a parallel run with ['scrubs'] failed archives [True, True]"),
            ("prune", "a run does not start by removing a killed run's secrets"),
            ("early", "a run does not start by removing a killed run's secrets"),
            ("unisolated", "a run does not start by removing a killed run's secrets"),
        ):
            with self.subTest(mutation=mutation):
                self.assertIn(message, parallel_mutated(mutation))

    def test_a_job_that_creates_a_directory_for_a_serial_fallback_is_caught(
        self,
    ) -> None:
        queued = copy.deepcopy(role_tasks(QUEUE_TASKS))
        queued[0]["when"] = TEMPLATE_EXISTS
        self.assertEqual(
            queue_violations(queued),
            ["a probe of {'rc': 1} creates True without its job"],
        )

    def test_a_job_that_puts_its_flags_into_the_masker_is_caught(self) -> None:
        content = role_task(QUEUE_TASKS, "📮")["ansible.builtin.copy"]["content"]
        broken = re.sub(
            r"_playwright_argv\[:\(.*?\) \+ 1\]", "_playwright_argv[:2]", content
        )
        self.assertNotEqual(broken, content)
        self.assertEqual(
            job_violations(broken), ["the job argv is wrong with template=True"]
        )


if __name__ == "__main__":
    unittest.main()
