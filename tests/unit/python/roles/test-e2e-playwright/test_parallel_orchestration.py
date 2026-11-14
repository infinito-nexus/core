import base64
import importlib.util
import json
import re
import shlex
import sys
import tempfile
import time
import unittest
from pathlib import Path

import jinja2
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.filter.core import FilterModule
from ansible.plugins.test.core import TestModule
from ansible.template import Templar
from jinja2.nativetypes import NativeEnvironment

from agents.routines.tools.watchdog import SILENCE_SECONDS
from plugins.lookup.role_tests import LookupModule as RoleTestsLookup
from plugins.lookup.timeout import scaled_timeout
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_DEFAULTS_MAIN,
    ROLE_FILE_META_NETWORKS,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT, ROLE, role_task

AFTER_STAGING = (
    "🔏 Seal the job list so the scheduler drains and exits",
    "⏳ Wait for the scheduler to drain the job list",
    "⏹️ Stop the RBAC sync test interval",
    "🧹 Remove any handed-over container the scheduler did not stop",
    "📥 Read each handed-over run's job and result",
    "🧭 Leave the runs whose dependency never ran here to the serial runner",
    "📝 Report and archive each handed-over run",
    "🛑 Fail when the scheduler itself did not finish cleanly",
)
BUDGET_INPUTS = (
    "TEST_E2E_PLAYWRIGHT_ONION_RUN_TIMEOUT",
    "test_e2e_playwright_run_timeout",
    "TEST_E2E_PLAYWRIGHT_ONION_PROBE_RETRIES",
    "TEST_E2E_PLAYWRIGHT_ONION_PROBE_DELAY",
    "TEST_E2E_PLAYWRIGHT_ONION_PROBE_MAX_TIME",
    "test_e2e_playwright_wait_retries",
    "test_e2e_playwright_wait_delay",
)
FIXTURE_INPUTS = dict(zip(BUDGET_INPUTS, (5400, 3600, 40, 15, 120, 30, 5), strict=True))
FIRST_PROBE = "📡 Probe the onion over Tor"
SECOND_PROBE = "📡 Probe the onion over the current circuits"
RECREATE = "🔄 Recreate Tor"
ONION_PROBE_INPUTS = (
    "TEST_E2E_PLAYWRIGHT_ONION_PROBE_RETRIES",
    "TEST_E2E_PLAYWRIGHT_ONION_PROBE_DELAY",
    "TEST_E2E_PLAYWRIGHT_ONION_PROBE_MAX_TIME",
)
ONION_FIXTURE = {
    "role_path": "/role",
    "_playwright_pass_domain": "x.onion",
    "TEST_E2E_PLAYWRIGHT_TOR_LOCK": "/stage/tor.lock",
    **{name: FIXTURE_INPUTS[name] for name in ONION_PROBE_INPUTS},
}
WORDPRESS0_APPS = (
    "web-app-keycloak",
    "web-app-hermes",
    "web-app-matomo",
    "web-app-openclaw",
    "web-app-weblate",
    "web-svc-cdn",
    "web-svc-design",
    "web-svc-logout",
    "web-svc-mirror",
    "web-svc-simpleicons",
    "web-svc-translate",
    "web-app-dashboard",
    "web-app-discourse",
    "web-app-stalwart",
    "web-app-jitsi",
    "web-app-matrix",
    "web-app-prometheus",
    "web-app-wordpress",
)


def budget_expression() -> str:
    """Read ``TEST_E2E_PLAYWRIGHT_PARALLEL_BUDGET`` as the role writes it.

    Returns:
        The Jinja expression.
    """
    return load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})[
        "TEST_E2E_PLAYWRIGHT_PARALLEL_BUDGET"
    ]


def render_budget(
    expression, apps, factor, inputs, role_timeout, networks, handover
) -> int:
    """Render the scheduler's async ceiling for one round.

    Args:
        expression: the ceiling expression to render.
        apps: ``TEST_E2E_PLAYWRIGHT_APPS`` of the round.
        factor: the ``TIMEOUT_FACTOR`` the ``timeout`` lookup scales by.
        inputs: the role variables the expression reads, by name.
        role_timeout: an app's ``playwright.timeout``, ``''`` when unset.
        networks: the networks an app's domain has siblings on.
        handover: whether an app is pinned to its own domain.

    Returns:
        The ceiling in seconds.
    """

    def lookup(name, *terms, **kwargs):
        if name == "role_tests":
            return role_timeout(terms[0])
        if name == "timeout":
            return scaled_timeout(terms[0], factor)
        if name == "domain":
            return f"clearnet:{terms[0]}"
        if name == "config":
            return handover(terms[0])
        if name == "network_siblings":
            app = terms[0].split(":", 1)[1]
            return [f"{network}:{app}" for network in networks(app)]
        raise AssertionError(name)

    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False)
    )
    env.globals["lookup"] = lookup
    env.filters["network_of"] = lambda domain: domain.split(":", 1)[0]
    return int(
        env.from_string(expression).render(
            TEST_E2E_PLAYWRIGHT_APPS=list(apps), **inputs
        )
    )


def conditional(expression: str, **variables) -> bool:
    """Evaluate a task condition the way Ansible does.

    Args:
        expression: the ``when`` or ``failed_when`` text.
        **variables: the variables in scope.

    Returns:
        The condition's truth.
    """
    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False)
    )
    env.filters.update(FilterModule().filters())
    env.tests.update(TestModule().tests())
    return (
        env.from_string("{{ (" + expression + ") | bool }}").render(**variables)
        == "True"
    )


def native(expression: str, **variables):
    """Evaluate a task value the way Ansible does, keeping its native type.

    Args:
        expression: the templated value.
        **variables: the variables in scope.

    Returns:
        The rendered value.
    """
    env = NativeEnvironment()
    env.filters.update(FilterModule().filters())
    env.tests.update(TestModule().tests())
    return env.from_string(expression).render(**variables)


def scheduler_module():
    """Load ``run_parallel.py``, which the role ships as a plain file.

    Returns:
        The scheduler module.
    """
    spec = importlib.util.spec_from_file_location(
        "playwright_run_parallel_flow", ROLE / "files" / "run_parallel.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rp = scheduler_module()


def encoded(path: Path) -> str:
    """Return a file the way ``ansible.builtin.slurp`` hands it back.

    Args:
        path: a file the test wrote.

    Returns:
        The base64 content.
    """
    data = path.read_bytes()  # nocheck: cache-read
    return base64.b64encode(data).decode()


def script_argv(task: dict, **variables) -> list[str]:
    """Render the command line of an onion wait task's ``ansible.builtin.script``.

    Args:
        task: the task to render.
        **variables: variables beyond the fixture's Tor, domain and probe settings.

    Returns:
        The script path and its arguments.
    """
    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False)
    )
    env.filters.update(FilterModule().filters())
    env.globals["lookup"] = lambda name, *terms: {
        "tor_socks": "127.0.0.1:9050",
        "container": "/opt/tor",
    }[name]
    return shlex.split(
        env.from_string(task["ansible.builtin.script"]).render(
            {**ONION_FIXTURE, **variables}
        )
    )


class TestParallelOrchestration(unittest.TestCase):
    def test_a_dropped_identity_provider_sends_its_dependents_to_a_serial_first_pass(
        self,
    ):
        head = "web-app-keycloak"
        apps = [head, "web-app-a", "web-app-b", "web-app-c"]
        with tempfile.TemporaryDirectory() as tmp:
            jobs, trace = Path(tmp) / "jobs", Path(tmp) / "trace"
            jobs.mkdir()
            names = []
            for index, app in enumerate(apps[1:], start=1):
                names.append(f"{index}-{app}.job.json")
                spec = {
                    "id": app,
                    "argv": [sys.executable, "-c", f"open({str(trace)!r}, 'a')"],
                    "env": {},
                    "timeout": 30,
                    "after": [head],
                    "tor": False,
                    "workers": 1,
                    "memory_mb": 1,
                    "stop": ["true"],
                    "meta": {"reports_dir": tmp},
                }
                (jobs / names[-1]).write_text(json.dumps(spec))
            (jobs / "sealed").touch()
            gate = rp.HostGate(36.0, 0.5, 0.0, jobs / "-", jobs / "-", time.monotonic)
            tor = rp.TorReaders(Path(tmp) / "tor.lock", 3)
            self.assertEqual(rp.run(jobs, 3, 0.05, gate, tor), 0)
            self.assertFalse(trace.exists())
            reads = [
                {"playwright_read": name, "content": encoded(jobs / name)}
                for app, job in zip(apps[1:], names, strict=True)
                for name in (job, f"{app}.result.json")
            ]
        leave = role_task("03_run_pass.yml", "📝 Leave")["ansible.builtin.set_fact"]
        serial = native(
            leave["_playwright_serial_roles"],
            _playwright_serial_roles=[],
            application_id=head,
        )
        defer = role_task("01_setup/parallel.yml", "🧭")["ansible.builtin.set_fact"]
        serial = native(
            defer["_playwright_serial_roles"],
            _playwright_serial_roles=serial,
            _playwright_reads={"results": reads},
        )
        report = role_task("01_setup/parallel.yml", "📝 Report")
        for read in reads[1::2]:
            run = json.loads(base64.b64decode(read["content"]))
            self.assertFalse(conditional(report["when"], _playwright_run=run))
        first_pass = role_task("01_setup/orchestrate.yml", "▶️ Run the roles left")
        self.assertEqual(
            native(
                first_pass["loop"],
                TEST_E2E_PLAYWRIGHT_APPS=apps,
                _playwright_serial_roles=serial,
            ),
            apps,
        )
        self.assertEqual(native(first_pass["loop"], TEST_E2E_PLAYWRIGHT_APPS=apps), [])
        self.assertFalse(first_pass["vars"]["_playwright_dispatch"])
        orchestrate = [
            task["name"]
            for task in load_yaml_any(
                str(ROLE / "tasks" / "01_setup" / "orchestrate.yml"),
                default_if_missing=[],
            )
        ]
        parallel_at = next(i for i, n in enumerate(orchestrate) if n.startswith("🔀"))
        self.assertEqual(orchestrate[parallel_at + 1], first_pass["name"])
        self.assertEqual(
            [n.split()[1] for n in orchestrate[parallel_at + 2 : parallel_at + 4]],
            ["Stash", "Retry"],
        )

    def test_a_failed_staging_still_waits_reaps_and_reports_the_handed_over_runs(self):
        staging = role_task("01_setup/parallel.yml", "📦")
        self.assertEqual([t["name"] for t in staging["always"]], list(AFTER_STAGING))
        include = role_task("01_setup/orchestrate.yml", "🔀")
        self.assertEqual(
            include["ansible.builtin.include_tasks"], "01_setup/parallel.yml"
        )
        self.assertEqual(include["when"], "TEST_E2E_PLAYWRIGHT_PARALLEL | int > 1")

    def test_the_ceiling_counts_probe_passes_only_where_an_onion_can_be_picked(self):
        timeouts = {"web-app-docs": 9000}
        networks = {
            "web-app-docs": ["clearnet", "tor"],
            "web-app-x": ["clearnet"],
            "web-app-h": ["clearnet", "tor"],
        }
        onion_wait = 2 * 40 * (120 + 15) + 40 * 15
        for factor in (1, 2):
            with self.subTest(factor=factor):
                self.assertEqual(
                    render_budget(
                        budget_expression(),
                        ["web-app-docs", "web-app-x", "web-app-h"],
                        factor,
                        FIXTURE_INPUTS,
                        lambda app: timeouts.get(app, ""),
                        networks.get,
                        lambda app: app == "web-app-h",
                    ),
                    (factor * 9000 + onion_wait) + 2 * (factor * 3600 + 30 * 5),
                )

    def test_the_real_wordpress0_ceiling_never_undercuts_the_ci_step_timeout(self):
        role_vars = {
            **load_yaml_any(str(ROLE / ROLE_FILE_DEFAULTS_MAIN), default_if_missing={}),
            **load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={}),
        }
        variables = {"playbook_dir": str(PROJECT_ROOT)}
        role_tests = RoleTestsLookup(
            loader=DataLoader(),
            templar=Templar(loader=DataLoader(), variables=variables),
        )
        factor = load_yaml_any(
            str(PROJECT_ROOT / "group_vars" / "all" / "17_resource.yml"),
            default_if_missing={},
        )["TIMEOUT_FACTOR"]
        ceiling = render_budget(
            budget_expression(),
            WORDPRESS0_APPS,
            factor,
            {name: role_vars[name] for name in BUDGET_INPUTS},
            lambda app: role_tests.run(
                [app, "playwright.timeout"], variables=variables, default=""
            )[0],
            lambda app: ["clearnet", "tor"],
            lambda app: bool(
                (
                    load_yaml_any(
                        str(PROJECT_ROOT / "roles" / app / ROLE_FILE_META_NETWORKS),
                        default_if_missing={},
                    )
                    or {}
                )
                .get("reachability", {})
                .get("handover", False)
            ),
        )
        self.assertEqual(ceiling, 18 * (5400 + 2 * 40 * (120 + 15) + 40 * 15))
        workflow = load_yaml_any(
            str(PROJECT_ROOT / ".github" / "workflows" / "call-test-deploy.yml"),
            default_if_missing={},
        )
        drill = next(
            step
            for job in workflow["jobs"].values()
            for step in job.get("steps", [])
            if str(step.get("name", "")).startswith("🚀 Drill")
        )
        self.assertGreater(ceiling, int(drill["timeout-minutes"]) * 60)

    def test_each_parallel_run_keeps_output_result_and_retry_count_with_its_reports(
        self,
    ):
        line = role_task("04_collect.yml", "⏱️")
        for signal in ("retries", "flaky", "crashes", "crash_kinds"):
            self.assertIn(
                f"_playwright_run.{signal}", line["ansible.builtin.debug"]["msg"]
            )
        keep = role_task("04_collect.yml", "📋")
        self.assertEqual(keep["loop"], ["result.json", "stdout", "stderr"])
        self.assertTrue(keep["ansible.builtin.copy"]["dest"].endswith("/run-parallel/"))
        tasks = load_yaml_any(
            str(ROLE / "tasks" / "04_collect.yml"), default_if_missing=[]
        )
        holder = next(
            i for i, t in enumerate(tasks) if keep in [t, *t.get("block", [])]
        )
        archive = next(i for i, t in enumerate(tasks) if t["name"].startswith("🗄️"))
        self.assertLess(holder, archive)
        script = read_text(str(ROLE / "files" / "archive_playwright_reports.sh"))
        self.assertIn(
            "for item in playwright-junit.xml playwright-report test-results run-parallel; do",
            script,
        )

    def test_only_the_parallel_run_hands_the_recreate_its_tor_lock(self):
        wait = role_task("03_run_pass.yml", "⏳ Wait until the onion")
        self.assertEqual(wait["when"], "TEST_E2E_PLAYWRIGHT_IS_ONION | bool")
        for prefix in FIRST_PROBE, SECOND_PROBE:
            with self.subTest(probe=prefix):
                self.assertEqual(
                    script_argv(role_task("03_run_pass.yml", prefix)),
                    ["/role/files/probe_onion.sh", "127.0.0.1:9050", "x.onion", "120"],
                )
        recreate = role_task("03_run_pass.yml", RECREATE)
        for dispatch, lock in ((False, ""), (True, "/stage/tor.lock")):
            with self.subTest(dispatch=dispatch):
                self.assertEqual(
                    script_argv(recreate, _playwright_dispatch=dispatch)[1:],
                    ["/opt/tor", lock, str(40 * 15)],
                )

    def test_an_unreachable_onion_fails_the_serial_run_but_only_its_own_app_in_parallel(
        self,
    ):
        wait = role_task("03_run_pass.yml", "⏳ Wait until the onion")
        first = role_task("03_run_pass.yml", FIRST_PROBE)
        recreate = role_task("03_run_pass.yml", RECREATE)
        second = role_task("03_run_pass.yml", SECOND_PROBE)
        release = role_task("03_run_pass.yml", "🚦")
        queue = role_task("03_run_pass.yml", "📮")
        remember = role_task("03_run_pass.yml", "📝 Remember")
        leave = role_task("03_run_pass.yml", "📝 Leave")
        skipped = {"skipped": True, "changed": False}
        self.assertEqual(wait["block"], [first])
        self.assertEqual(wait["rescue"][0], recreate)
        self.assertEqual(wait["rescue"][1]["block"], [second])
        self.assertEqual(wait["rescue"][1]["always"], [release])
        self.assertNotIn("ignore_errors", first)
        self.assertNotIn("failed_when", first)
        for probe in first, second:
            for result, answered in (({"rc": 0}, True), ({"rc": 1}, False)):
                with self.subTest(probe=probe["name"], result=result):
                    self.assertEqual(
                        conditional(probe["until"], _playwright_probe=result), answered
                    )
        for rc, failed, changed in (
            (0, False, True),
            (75, False, False),
            (1, True, False),
        ):
            with self.subTest(recreate_rc=rc):
                result = {"_playwright_tor_recreate": {"rc": rc}}
                self.assertEqual(conditional(recreate["failed_when"], **result), failed)
                self.assertEqual(
                    conditional(recreate["changed_when"], **result), changed
                )
        for dispatch in False, True:
            with self.subTest(dispatch=dispatch):
                for task in recreate, second:
                    self.assertIs(
                        native(task["ignore_errors"], _playwright_dispatch=dispatch),
                        dispatch,
                    )
                self.assertEqual(
                    conditional(release["when"], _playwright_dispatch=dispatch),
                    dispatch,
                )
        self.assertEqual(
            native(
                release["ansible.builtin.file"]["path"],
                TEST_E2E_PLAYWRIGHT_TOR_LOCK="/stage/tor.lock",
            ),
            str(rp.TorReaders(Path("/stage/tor.lock"), 1).pending),
        )
        self.assertEqual(release["ansible.builtin.file"]["state"], "absent")
        for result, queued in (
            (skipped, True),
            ({"rc": 0}, True),
            ({"rc": 1}, False),
            ({"msg": "transfer failed"}, False),
        ):
            with self.subTest(result=result):
                self.assertEqual(
                    conditional(queue["when"], _playwright_probe=result), queued
                )
                written = {"dest": "/jobs/3-x.job.json"} if queued else skipped
                self.assertEqual(
                    conditional(remember["when"], _playwright_job_written=written),
                    queued,
                )
                self.assertEqual(
                    conditional(leave["when"], _playwright_job_written=written),
                    not queued,
                )
        self.assertIn("_playwright_serial_roles", leave["ansible.builtin.set_fact"])

    def test_the_seal_keeps_its_times_and_the_async_states_why_it_is_safe(self):
        seal = role_task("01_setup/parallel.yml", "🔏")["ansible.builtin.file"]
        self.assertEqual(
            (seal["modification_time"], seal["access_time"]), ("preserve", "preserve")
        )
        self.assertRegex(
            read_text(str(ROLE / "tasks" / "01_setup" / "parallel.yml")),
            r"#\s*rationale:\s*async;\s*\S",
        )


class TestHeartbeat(unittest.TestCase):
    def setUp(self):
        self.role_vars = load_yaml_any(
            str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={}
        )

    def test_every_onion_probe_attempt_logs_a_retry_line_within_the_watchdog_silence(
        self,
    ):
        retries, delay, max_time = (self.role_vars[n] for n in ONION_PROBE_INPUTS)
        for prefix in FIRST_PROBE, SECOND_PROBE:
            with self.subTest(probe=prefix):
                probe = role_task("03_run_pass.yml", prefix)
                self.assertTrue(probe["name"].endswith("{{ _playwright_pass_domain }}"))
                self.assertEqual(
                    native(probe["retries"], **self.role_vars), retries - 1
                )
                self.assertEqual(native(probe["delay"], **self.role_vars), delay)
        self.assertLess(max_time + delay, SILENCE_SECONDS)

    def test_the_tor_recreate_waits_for_its_lock_within_the_watchdog_silence(self):
        recreate = role_task("03_run_pass.yml", RECREATE)
        argv = script_argv(
            recreate,
            _playwright_dispatch=True,
            **{name: self.role_vars[name] for name in ONION_PROBE_INPUTS},
        )
        self.assertLess(int(argv[3]), SILENCE_SECONDS)

    def test_the_serial_playwright_run_is_polled_within_the_watchdog_silence(self):
        run = role_task("03_run_pass.yml", "▶️ Run Playwright container")
        wait = role_task("03_run_pass.yml", "⏳ Wait for the Playwright run")
        delay = self.role_vars["TEST_E2E_PLAYWRIGHT_RUN_POLL_DELAY"]
        self.assertNotIn("timeout", run)
        self.assertEqual(run["poll"], 0)
        self.assertEqual(
            native(run["async"], TEST_E2E_PLAYWRIGHT_RUN_BUDGET="5400"), 5400
        )
        self.assertEqual(
            wait["ansible.builtin.async_status"]["jid"],
            "{{ " + run["register"] + ".ansible_job_id }}",
        )
        self.assertEqual(wait["register"], "_playwright_run")
        for finished in 0, 1:
            with self.subTest(finished=finished):
                self.assertEqual(
                    conditional(wait["until"], _playwright_run={"finished": finished}),
                    bool(finished),
                )
        self.assertEqual(native(wait["delay"], **self.role_vars), delay)
        self.assertLess(delay, SILENCE_SECONDS)
        for budget in 1, 5400, 5401:
            with self.subTest(budget=budget):
                retries = native(
                    wait["retries"],
                    TEST_E2E_PLAYWRIGHT_RUN_BUDGET=str(budget),
                    TEST_E2E_PLAYWRIGHT_RUN_POLL_DELAY=delay,
                )
                self.assertGreaterEqual(retries * delay, budget + 2 * delay)

    def test_the_wait_fails_only_a_run_that_ended_without_an_exit_status(self):
        wait = role_task("03_run_pass.yml", "⏳ Wait for the Playwright run")
        polled = {"started": True, "stdout": "", "stderr": ""}
        for result, failed in (
            ({**polled, "finished": False}, False),
            ({**polled, "finished": True, "rc": 0}, False),
            ({**polled, "finished": True, "rc": 1, "failed": True}, False),
            (
                {**polled, "finished": True, "failed": True, "msg": "Timeout exceeded"},
                True,
            ),
            (
                {
                    **polled,
                    "finished": True,
                    "failed": True,
                    "msg": "could not find job",
                },
                True,
            ),
        ):
            with self.subTest(result=result):
                self.assertEqual(
                    conditional(wait["failed_when"], _playwright_run=result), failed
                )

    def test_the_parallel_scheduler_is_polled_within_the_watchdog_silence(self):
        wait = role_task("01_setup/parallel.yml", "⏳ Wait for the scheduler")
        self.assertLess(native(wait["delay"], **self.role_vars), SILENCE_SECONDS)


class TestParallelContainerFlags(unittest.TestCase):
    """The flags only the parallel run adds must not shift the image argument."""

    def _container_module(self):
        path = (
            PROJECT_ROOT
            / "roles"
            / "sys-svc-container"
            / "files"
            / "python"
            / "container.py"
        )
        spec = importlib.util.spec_from_file_location("container_wrapper", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _flags(self):
        return role_task("03_run_pass.yml", "📮")["vars"]["_playwright_parallel_flags"]

    def test_every_parallel_flag_carries_its_value_in_one_token(self):
        flags = self._flags()
        self.assertEqual(len(flags), 2)
        for flag in flags:
            self.assertRegex(re.sub(r"\{\{.*?\}\}", "X", flag), r"^--[a-z-]+=\S+$")

    def test_no_job_gets_a_memory_cap_that_could_kill_it_running_alone(self):
        self.assertFalse(
            any(flag.startswith(("--memory", "-m")) for flag in self._flags())
        )
        self.assertTrue(
            any(flag.startswith("--oom-score-adj=") for flag in self._flags())
        )

    def test_the_wrapper_still_finds_the_image(self):
        container = self._container_module()
        argv = [
            "--rm",
            "--name=infinito-playwright-x",
            "--oom-score-adj=1000",
            "image:tag",
            "/bin/bash",
        ]
        _, image_and_args = container.split_docker_run_argv(argv)
        self.assertEqual(image_and_args[0], "image:tag")


if __name__ == "__main__":
    unittest.main()
