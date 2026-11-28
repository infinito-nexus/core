import base64
import importlib.util
import json
import re
import shlex
import sys
import tempfile
import time
import unittest
from operator import itemgetter
from pathlib import Path

import jinja2
from ansible.errors import AnsibleFilterError
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.filter.core import FilterModule
from ansible.plugins.test.core import TestModule
from ansible.template import Templar
from jinja2.nativetypes import NativeEnvironment

from agents.routines.tools.watchdog import SILENCE_SECONDS
from plugins.filter.network_of import network_of
from plugins.lookup.role_tests import LookupModule as RoleTestsLookup
from plugins.lookup.timeout import scaled_timeout
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.domains.primary_domain import get_domain
from utils.roles.mapping import (
    ROLE_FILE_DEFAULTS_MAIN,
    ROLE_FILE_META_NETWORKS,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT, ROLE, role_task

QUEUE_TASKS = "03_run_pass/queue.yml"
AFTER_STAGING = (
    "🔏 Seal the job list so the scheduler drains and exits",
    "⏳ Wait for the scheduler to drain the job list",
    "⏹️ Stop the RBAC sync test interval",
    "🧹 Remove any handed-over container the scheduler did not stop",
    "🫥 Mask the spec secrets in every file of each staged run, also after a kill",
    "🧹 Remove the spec secrets of every staged run",
    "📌 Note the runs whose reports could not be masked or secrets removed",
    "📥 Read each handed-over run's job and result",
    "🧭 Leave the runs whose dependency never ran here to the serial runner",
    "📝 Report and archive each handed-over run",
    "🛑 Fail when a staged run could not be masked or its spec secrets removed",
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
RETRY = "📡 Probe the onion again"
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
RUN_ONE = ROLE / "tasks" / "02_run_one.yml"
DOMAINLESS = "svc-dns-knot"
SERVED = {
    "web-app-docs": ["docs.example.org", "docs.abcdef.onion"],
    "web-app-h": ["h.example.org", "h.abcdef.onion"],
}
HANDED_OVER = ("web-app-h",)
REPORTS = "/reports"
PASS_PLAN = (
    "_playwright_passes",
    "_playwright_pass_domain",
    "_playwright_pass_reports_dir",
)
WAIT_READY = "⏳ Wait until application is ready"
WAIT_ONION = "⏳ Wait until the onion"


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
        networks: the networks an app's domain has siblings on, none for an
            app without a domain.
        handover: whether an app is pinned to its own domain.

    Returns:
        The ceiling in seconds.
    """
    served = {app: [f"clearnet:{app}"] for app in apps if networks(app)}

    def lookup(name, *terms, **kwargs):
        if name == "role_tests":
            return role_timeout(terms[0])
        if name == "timeout":
            return scaled_timeout(terms[0], factor)
        if name == "domains":
            return served
        if name == "domain":
            return get_domain(served, terms[0])
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


def conditional(expression: str | list[str], **variables) -> bool:
    """Evaluate a task condition the way Ansible does.

    Args:
        expression: the ``when`` or ``failed_when`` text, or the list a task holds.
        **variables: the variables in scope.

    Returns:
        The condition's truth.
    """
    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False)
    )
    env.filters.update(FilterModule().filters())
    env.tests.update(TestModule().tests())
    if isinstance(expression, list):
        expression = " and ".join(f"({part})" for part in expression)
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


def pass_lookup(name: str, *terms):
    """Answer the lookups 02_run_one.yml plans a pass with.

    Args:
        name: the lookup plugin.
        *terms: its terms.

    Returns:
        The plugin's answer for the served roles of ``SERVED``; ``domain``
        raises for any other role through the plugin's own resolver.
    """
    if name == "domains":
        return SERVED
    if name == "domain":
        return get_domain(SERVED, terms[0])
    if name == "config":
        return terms[0] in HANDED_OVER
    if name == "network_siblings":
        return next(names for names in SERVED.values() if terms[0] in names)
    raise AssertionError(name)


def pass_env(choose) -> NativeEnvironment:
    """Build the environment 02_run_one.yml renders in.

    Args:
        choose: stands in for the ``random`` filter of the network pick.

    Returns:
        A native environment with Ansible's filters, ``network_of`` and
        ``pass_lookup``.
    """
    env = NativeEnvironment()
    env.filters.update(FilterModule().filters())
    env.filters.update(random=choose, network_of=network_of)
    env.tests.update(TestModule().tests())
    env.globals["lookup"] = pass_lookup
    return env


def holds(env: NativeEnvironment, task: dict, scope: dict) -> bool:
    """Evaluate a task's ``when`` the way Ansible does, item by item.

    Args:
        env: the environment to render in.
        task: the task whose ``when`` decides.
        scope: the variables in scope.

    Returns:
        Whether every condition holds.
    """
    when = task["when"] if isinstance(task["when"], list) else [task["when"]]
    return all(
        env.from_string("{{ (" + condition + ") | bool }}").render(scope)
        for condition in when
    )


def plan_pass(tasks_file: Path, app: str, choose, picks: dict) -> dict:
    """Render what 02_run_one.yml hands 03_run_pass.yml for one role.

    Args:
        tasks_file: the 02_run_one.yml to render.
        app: the role under test.
        choose: stands in for the ``random`` filter of the network pick.
        picks: ``_playwright_network_picks`` before the role runs.

    Returns:
        The picks after the pick task and the pass's ``PASS_PLAN`` values.
    """
    tasks = load_yaml_any(str(tasks_file), default_if_missing=[])
    pick = next(task for task in tasks if task["name"].startswith("🎲"))
    run = next(task for task in tasks if task["name"].startswith("🌈"))
    env = pass_env(choose)
    scope = {
        "application_id": app,
        "_playwright_network_picks": dict(picks),
        "_playwright_reports_dir": f"{REPORTS}/{app}",
    }
    if holds(env, pick, scope):
        scope["_playwright_network_picks"] = env.from_string(
            pick["ansible.builtin.set_fact"]["_playwright_network_picks"]
        ).render(scope)
    for name in PASS_PLAN:
        scope[name] = env.from_string(run["vars"][name]).render(scope)
    return {name: scope[name] for name in ("_playwright_network_picks", *PASS_PLAN)}


def runs_on(task: dict, domain: str) -> bool:
    """Tell whether a 03_run_pass.yml task runs on the pass of ``domain``.

    Args:
        task: the task whose ``when`` decides.
        domain: ``_playwright_pass_domain``, empty for a domainless role.

    Returns:
        The task's ``when`` with the readiness wait enabled and the
        frontend's ``config`` lookup at its default.
    """
    env = NativeEnvironment()
    env.filters.update(FilterModule().filters())
    env.filters["network_of"] = network_of
    env.globals["lookup"] = lambda name, *terms: {"config": terms[-1]}[name]
    scope = {
        "application_id": DOMAINLESS,
        "_playwright_pass_domain": domain,
        "TEST_E2E_PLAYWRIGHT_WAIT_ENABLED": True,
    }
    role_vars = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})
    scope["TEST_E2E_PLAYWRIGHT_IS_ONION"] = env.from_string(
        role_vars["TEST_E2E_PLAYWRIGHT_IS_ONION"]
    ).render(scope)
    return holds(env, task, scope)


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
        leave = role_task(QUEUE_TASKS, "📝 Leave")["ansible.builtin.set_fact"]
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

    def test_the_ceiling_counts_one_clearnet_pass_for_a_domainless_role(self):
        apps = ["web-app-docs", DOMAINLESS]
        networks = {"web-app-docs": ["clearnet", "tor"]}
        onion_wait = 2 * 40 * (120 + 15) + 40 * 15
        guarded = budget_expression()
        unguarded = re.sub(
            r"\[''\] if app not in lookup\('domains'\)\s+else ", "", guarded
        )
        self.assertNotEqual(unguarded, guarded)
        for factor in (1, 2):
            with self.subTest(factor=factor):
                round_inputs = (
                    apps,
                    factor,
                    FIXTURE_INPUTS,
                    lambda app: "",
                    networks.get,
                    lambda app: False,
                )
                self.assertEqual(
                    render_budget(guarded, *round_inputs),
                    (factor * 5400 + onion_wait) + (factor * 3600 + 30 * 5),
                )
                with self.assertRaises(AnsibleFilterError):
                    render_budget(unguarded, *round_inputs)

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
        retry = role_task("03_run_pass.yml", RETRY)
        second = role_task("03_run_pass.yml", SECOND_PROBE)
        release = role_task("03_run_pass.yml", "🚦")
        queue = role_task(QUEUE_TASKS, "📮")
        remember = role_task(QUEUE_TASKS, "📝 Remember")
        leave = role_task(QUEUE_TASKS, "📝 Leave")
        skipped = {"skipped": True, "changed": False}
        self.assertEqual(wait["block"], [first, recreate, retry])
        self.assertNotIn("rescue", wait)
        self.assertEqual(retry["block"], [second])
        self.assertEqual(retry["always"], [release])
        self.assertIs(first["ignore_errors"], True)
        self.assertNotIn("failed_when", first)
        exhausted = {"rc": 1, "failed": True, "attempts": 39}
        for result, recreates in (
            ({"rc": 0}, False),
            (exhausted, True),
            ({"msg": "transfer failed", "failed": True}, True),
        ):
            with self.subTest(first_probe=result):
                self.assertEqual(
                    conditional(recreate["when"], _playwright_probe=result), recreates
                )
        for result, probes_again in (
            (skipped, False),
            ({"rc": 0}, True),
            ({"rc": 75}, True),
            ({"rc": 1, "failed": True}, True),
        ):
            with self.subTest(recreate=result):
                self.assertEqual(
                    conditional(retry["when"], _playwright_tor_recreate=result),
                    probes_again,
                )
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
        return role_task(QUEUE_TASKS, "📮")["vars"]["_playwright_parallel_flags"]

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


class TestNetworkPick(unittest.TestCase):
    def test_a_domainless_role_runs_one_pass_on_no_network(self):
        self.assertEqual(
            plan_pass(RUN_ONE, DOMAINLESS, itemgetter(0), {}),
            {
                "_playwright_network_picks": {},
                "_playwright_passes": [""],
                "_playwright_pass_domain": "",
                "_playwright_pass_reports_dir": f"{REPORTS}/{DOMAINLESS}",
            },
        )

    def test_a_domainless_pass_skips_the_readiness_wait_and_every_onion_step(self):
        ready = role_task("03_run_pass.yml", WAIT_READY)
        onion = role_task("03_run_pass.yml", WAIT_ONION)
        clearnet, tor = SERVED["web-app-docs"]
        for domain, waits, probes in (
            ("", False, False),
            (clearnet, True, False),
            (tor, False, True),
        ):
            with self.subTest(domain=domain):
                self.assertIs(runs_on(ready, domain), waits)
                self.assertIs(runs_on(onion, domain), probes)

    def test_only_its_when_keeps_the_pick_away_from_a_domainless_role(self):
        pick = role_task("02_run_one.yml", "🎲")["ansible.builtin.set_fact"]
        with self.assertRaises(AnsibleFilterError):
            pass_env(itemgetter(0)).from_string(
                pick["_playwright_network_picks"]
            ).render(application_id=DOMAINLESS, _playwright_network_picks={})

    def test_a_served_role_keeps_its_pick_passes_and_reports_dir(self):
        served = SERVED["web-app-docs"]
        for choose, domain, reports in (
            (itemgetter(0), served[0], f"{REPORTS}/web-app-docs"),
            (itemgetter(-1), served[1], f"{REPORTS}/web-app-docs+tor"),
        ):
            with self.subTest(domain=domain):
                self.assertEqual(
                    plan_pass(RUN_ONE, "web-app-docs", choose, {}),
                    {
                        "_playwright_network_picks": {"web-app-docs": domain},
                        "_playwright_passes": served,
                        "_playwright_pass_domain": domain,
                        "_playwright_pass_reports_dir": reports,
                    },
                )

    def test_a_handed_over_role_and_a_retry_keep_their_pick(self):
        handed = plan_pass(RUN_ONE, "web-app-h", itemgetter(-1), {})
        self.assertEqual(handed["_playwright_pass_domain"], SERVED["web-app-h"][0])
        kept = {"web-app-docs": SERVED["web-app-docs"][1]}
        retry = plan_pass(RUN_ONE, "web-app-docs", itemgetter(0), kept)
        self.assertEqual(retry["_playwright_network_picks"], kept)
        self.assertEqual(retry["_playwright_pass_domain"], kept["web-app-docs"])


if __name__ == "__main__":
    unittest.main()
