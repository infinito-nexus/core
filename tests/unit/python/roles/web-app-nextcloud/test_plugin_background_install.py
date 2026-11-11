from __future__ import annotations

import importlib.util
import json
import sys
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2 import Environment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

ROLE = PROJECT_ROOT / "roles/web-app-nextcloud"
MANAGER_OPS = ROLE / "tasks/02_manager_ops.yml"
PLUGIN = ROLE / "tasks/02_manager_ops/06_plugin.yml"
BACKGROUND = ROLE / "tasks/02_manager_ops/06_plugin/01_background.yml"
PROBE = ROLE / "files/php/utils/migration_state.php"


def _load_filters():
    path = ROLE / "filter_plugins/nextcloud_install.py"
    spec = importlib.util.spec_from_file_location("nextcloud_install_wiring", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["nextcloud_install_wiring"] = module
    spec.loader.exec_module(module)
    return module.FilterModule().filters()


FILTERS = _load_filters()


def _flat(tasks: list[dict]) -> list[dict]:
    """Return the tasks in run order, block sections expanded in place.

    Args:
      tasks: parsed task list of one task file.
    """
    flat: list[dict] = []
    for task in tasks:
        if "block" in task:
            flat.extend(_flat(task["block"]) + _flat(task.get("always", [])))
        else:
            flat.append(task)
    return flat


def _tasks(path) -> list[dict]:
    return _flat(load_yaml_any(str(path), default_if_missing=[]))


def _index(tasks: list[dict], fragment: str) -> int:
    return next(i for i, task in enumerate(tasks) if fragment in task.get("name", ""))


def _task(path, fragment: str) -> dict:
    tasks = _tasks(path)
    return tasks[_index(tasks, fragment)]


def _install_block() -> dict:
    return next(
        task
        for task in load_yaml_any(str(PLUGIN), default_if_missing=[])
        if "block" in task
    )


def _eval(expression: str, **variables) -> bool:
    env = Environment(autoescape=True)
    env.filters.update(FILTERS)
    return bool(env.compile_expression(expression)(**variables))


def _ansible_eval(expression: str, **variables) -> bool:
    templar = Templar(loader=DataLoader(), variables=variables)
    return bool(
        templar.template(_trust_as_template("{{ (" + expression + ") | bool }}"))
    )


class TestOrder(unittest.TestCase):
    def setUp(self):
        self.tasks = _tasks(PLUGIN)

    def test_the_background_job_starts_after_the_last_ddl_before_the_loop(self):
        self.assertLess(
            _index(self.tasks, "Disable the plugins that end up disabled"),
            _index(self.tasks, "Start the installs that run beside the install loop"),
        )
        self.assertLess(
            _index(self.tasks, "Start the installs that run beside the install loop"),
            _index(self.tasks, "Install and enable the plugins Nextcloud lacks"),
        )

    def test_the_join_sits_between_the_install_loop_and_the_plugins_own_stage(self):
        order = [
            _index(self.tasks, "Install and enable the plugins Nextcloud lacks"),
            _index(self.tasks, "Join the background installs"),
            _index(
                self.tasks,
                "Enable and configure the plugins installed in the background",
            ),
            _index(self.tasks, "Enable the installed plugins Nextcloud keeps disabled"),
            _index(self.tasks, "Configure every queued plugin in one batch"),
        ]
        self.assertEqual(order, sorted(order))

    def test_both_background_steps_loop_over_the_background_plan(self):
        for fragment in (
            "Start the installs that run beside the install loop",
            "Enable and configure the plugins installed in the background",
        ):
            with self.subTest(fragment=fragment):
                task = _task(PLUGIN, fragment)
                self.assertIn("nextcloud_plugin_plan.background", task["loop"])
        self.assertIn(
            "nextcloud_plugin_plan.install",
            _task(PLUGIN, "Install and enable the plugins Nextcloud lacks")["loop"],
        )

    def test_the_background_job_follows_the_occ_delegation_of_the_plugin_stage(self):
        include = _task(MANAGER_OPS, "Setup Nextcloud Plugins")
        self.assertEqual(
            include["include_tasks"]["apply"]["delegate_to"],
            "{{ NEXTCLOUD_HOST_NODE }}",
        )
        join = _task(PLUGIN, "Join the background installs")
        for task in [*_tasks(BACKGROUND), join]:
            with self.subTest(task=task["name"]):
                self.assertNotIn("delegate_to", task)

    def test_a_failing_install_loop_still_joins_the_background_jobs(self):
        block = _install_block()
        self.assertEqual(
            [task["name"] for task in block["block"]],
            [
                "🛫 Start the installs that run beside the install loop",
                "📦 Install and enable the plugins Nextcloud lacks",
            ],
        )
        self.assertEqual(
            [task["name"] for task in block["always"]],
            ["⏳ Join the background installs"],
        )

    def test_the_includes_hand_over_the_plugin(self):
        start = _task(PLUGIN, "Start the installs that run beside the install loop")
        self.assertEqual(start["vars"]["plugin_key"], "{{ plugin_item.key }}")
        stage = _task(
            PLUGIN, "Enable and configure the plugins installed in the background"
        )
        self.assertEqual(stage["vars"]["plugin_key"], "{{ plugin_item.key }}")
        self.assertEqual(stage["vars"]["plugin_value"], "{{ plugin_item.value }}")


class TestBackgroundJob(unittest.TestCase):
    def setUp(self):
        self.tasks = _tasks(BACKGROUND)
        self.job = self.tasks[_index(self.tasks, "in the background")]

    def test_the_job_starts_then_queues_then_the_gate_polls(self):
        order = [
            _index(self.tasks, "in the background"),
            _index(self.tasks, "Queue"),
            _index(self.tasks, "Hold the other installs"),
        ]
        self.assertEqual(order, sorted(order))
        self.assertEqual(len(order), len(self.tasks))

    def test_the_job_is_fire_and_forget_in_every_mode(self):
        self.assertEqual(
            self.job["async"], "{{ NEXTCLOUD_PLUGIN_BACKGROUND_ASYNC_TIME }}"
        )
        self.assertEqual(self.job["poll"], 0)
        self.assertNotIn(
            "ASYNC_ENABLED", str(self.job["async"]) + str(self.job["poll"])
        )

    def test_the_gate_reads_the_job_file_first_then_the_schema_state(self):
        script = self.job["ansible.builtin.shell"]
        self.assertIn("app:install {{ plugin_key | quote }}", script)
        gate = _task(BACKGROUND, "Hold the other installs")["ansible.builtin.shell"]
        lines = gate["cmd"].strip().splitlines()
        self.assertEqual(
            lines[0], "cat {{ nextcloud_plugin_background_job.results_file | quote }}"
        )
        self.assertEqual(lines[1], "echo")
        self.assertEqual(
            lines[2],
            "{{ NEXTCLOUD_DOCKER_EXEC_INTERACTIVE }} php -- "
            "{{ NEXTCLOUD_DOCKER_WORK_DIRECTORY | quote }} {{ plugin_key | quote }}",
        )
        self.assertEqual(len(lines), 3)
        self.assertEqual(
            gate["stdin"], "{{ lookup('file', 'php/utils/migration_state.php') }}"
        )

    def test_the_gate_does_not_rely_on_debug_only_occ_commands(self):
        gate = _task(BACKGROUND, "Hold the other installs")["ansible.builtin.shell"]
        self.assertNotIn("migrations:", gate["cmd"])

    def test_the_probe_reads_what_the_installer_writes(self):
        probe = read_text(str(PROBE))
        self.assertIn("new \\OC\\DB\\MigrationService($appId", probe)
        self.assertIn("\\OCP\\Server::get(\\OC\\DB\\Connection::class)", probe)
        self.assertIn('"migrated" => $migrations->getMigratedVersions()', probe)
        self.assertIn('"available" => $migrations->getAvailableVersions()', probe)
        self.assertIn('echo "MIGRATION_STATE "', probe)
        self.assertIn("[, $serverRoot, $appId] = $argv;", probe)

    def test_the_job_never_forces_an_install(self):
        self.assertNotIn("--force", self.job["ansible.builtin.shell"])

    def test_the_job_is_queued_for_the_join(self):
        queue = _task(BACKGROUND, "Queue")["ansible.builtin.set_fact"]
        jobs = queue["nextcloud_plugin_background_jobs"]
        self.assertIn("nextcloud_plugin_background_job.ansible_job_id", jobs)


RUNNING = json.dumps({"started": True, "finished": False, "ansible_job_id": "j1.2"})


def _gate_result(job: str, probe: str, rc: int) -> dict:
    return {
        "nextcloud_plugin_background_gate": {
            "rc": rc,
            "stdout": job + "\n" + probe,
            "attempts": 1,
        }
    }


def _state(migrated: int, available: int) -> str:
    versions = [f"{n:09d}Date20260129094821" for n in range(1, available + 1)]
    state = {"migrated": versions[:migrated], "available": versions}
    return "MIGRATION_STATE " + json.dumps(state)


SETTLED = _state(migrated=8, available=8)
MARKING = _state(migrated=3, available=8)


class TestGate(unittest.TestCase):
    def setUp(self):
        self.gate = _task(BACKGROUND, "Hold the other installs")

    def _decide(self, result: dict) -> tuple[bool, bool]:
        return _eval(self.gate["until"], **result), _eval(
            self.gate["failed_when"], **result
        )

    def test_an_applied_schema_releases_the_loop(self):
        self.assertEqual(
            self._decide(_gate_result(RUNNING, SETTLED, rc=0)), (True, False)
        )

    def test_a_schema_in_progress_keeps_polling(self):
        until, _ = self._decide(_gate_result(RUNNING, MARKING, rc=0))
        self.assertFalse(until)

    def test_a_gate_that_never_opens_fails_the_deploy(self):
        _, failed = self._decide(_gate_result(RUNNING, MARKING, rc=0))
        self.assertTrue(failed)

    def test_the_download_phase_keeps_polling(self):
        self.assertEqual(self._decide(_gate_result(RUNNING, "", rc=0)), (False, True))

    def test_an_ended_job_releases_the_loop(self):
        ended = json.dumps({"rc": 1, "stdout": "recognize already installed"})
        self.assertEqual(self._decide(_gate_result(ended, "", rc=0)), (True, False))

    def test_a_killed_job_stops_polling_and_fails(self):
        for job in (
            {"rc": 124},
            {"rc": -9},
            {"msg": "Timeout exceeded", "failed": True},
        ):
            with self.subTest(job=job):
                self.assertEqual(
                    self._decide(_gate_result(json.dumps(job), MARKING, rc=0)),
                    (True, True),
                )

    def test_the_gate_outlasts_the_job(self):
        self.assertEqual(self.gate["delay"], 2)
        self.assertIn("NEXTCLOUD_PLUGIN_BACKGROUND_ASYNC_TIME", self.gate["retries"])
        self.assertIn("/ 2", self.gate["retries"])

    def test_a_hung_probe_is_cut_off_by_the_exec_wrapper(self):
        self.assertEqual(
            self.gate["environment"]["CONTAINER_EXEC_TIMEOUT"],
            "{{ lookup('timeout', 60) | int }}",
        )


class TestJoin(unittest.TestCase):
    def setUp(self):
        self.join = _task(PLUGIN, "Join the background installs")

    def _result(self, **result) -> dict:
        return {"nextcloud_plugin_background_result": result}

    def test_the_join_outlasts_the_job(self):
        self.assertEqual(self.join["delay"], 5)
        self.assertIn("NEXTCLOUD_PLUGIN_BACKGROUND_ASYNC_TIME", self.join["retries"])
        self.assertIn("/ 5", self.join["retries"])

    def test_a_running_job_is_polled(self):
        self.assertFalse(
            _ansible_eval(
                self.join["until"], **self._result(started=True, finished=False)
            )
        )

    def test_a_finished_job_ends_the_poll(self):
        self.assertTrue(
            _ansible_eval(self.join["until"], **self._result(finished=True, rc=1))
        )

    def test_an_occ_failure_is_left_to_the_install_stage(self):
        for rc in (0, 1):
            with self.subTest(rc=rc):
                self.assertFalse(
                    _eval(
                        self.join["failed_when"], **self._result(finished=True, rc=rc)
                    )
                )

    def test_a_job_without_an_occ_exit_code_fails_the_deploy(self):
        for result in (
            {"finished": False, "started": True},
            {"finished": True, "msg": "Timeout exceeded", "failed": True},
            {"finished": True, "rc": 124},
            {"finished": True, "rc": -9},
        ):
            with self.subTest(result=result):
                self.assertTrue(
                    _eval(self.join["failed_when"], **self._result(**result))
                )

    def test_only_a_fresh_install_reports_a_change(self):
        changed = self.join["changed_when"]
        self.assertTrue(
            _eval(changed, **self._result(rc=0, stdout="recognize 12.0.2 installed"))
        )
        self.assertFalse(
            _eval(changed, **self._result(rc=1, stdout="recognize already installed"))
        )
        self.assertFalse(_eval(changed, **self._result(finished=False)))


if __name__ == "__main__":
    unittest.main()
