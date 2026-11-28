from __future__ import annotations

import copy
import importlib.util
import unittest

import jinja2

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
CHECK = ROLE / "tasks" / "utils" / "provision" / "sandbox.yml"
RESOLVER = PROJECT_ROOT / "roles" / "sys-svc-compose" / "tasks" / "utils" / "swarm"
RESOLVER_FILE = "resolve_host_cid.yml"
VARIABLES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
PROVISION = next(
    runner["service"]
    for runner in VARIABLES["SEMAPHORE_PLATFORM_RUNNERS"]
    if runner["key"] == "provision"
)
JINJA = jinja2.Environment(
    autoescape=jinja2.select_autoescape(default_for_string=False),
    undefined=jinja2.StrictUndefined,
)
COMPOSE = {
    "IS_SWARM_MODE": False,
    "inventory_hostname": "stack",
    "STACK_HOST": "stack",
    "placement": {"semaphore": "stack", PROVISION: "stack"},
}
SWARM = {
    "IS_SWARM_MODE": True,
    "inventory_hostname": "manager-1",
    "STACK_HOST": "manager-1",
    "placement": {"semaphore": "manager-1", PROVISION: "worker-2"},
}
READS = (
    "token",
    "marker",
    "environ 41",
    "mem 41",
    "fd 41",
    "cwd 41",
    "task /run/provision/63801/task",
    "closed /tmp/semaphore",
    "closed /tmp/provision-locks",
    "writes /var/tmp",
)


def load_filter():
    """Returns:
    ``semaphore_sandbox_findings`` of the role's filter plugin.
    """
    path = ROLE / "filter_plugins" / "semaphore_sandbox.py"
    spec = importlib.util.spec_from_file_location("semaphore_sandbox_filter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.semaphore_sandbox_findings


def held():
    """Returns:
    A check report whose sandboxed probes found nothing and whose
    unsandboxed probes found the token, the other marker and a living child.
    """
    sandboxed = {"reads": [], "exit": 0, "child_alive": False, "ipc_left": False}
    unsandboxed = {
        "reads": ["token", "marker"],
        "exit": 0,
        "child_alive": True,
        "child_mem": True,
        "ipc_seen": True,
    }
    return {
        "inside": [dict(sandboxed), dict(sandboxed)],
        "outside": [copy.deepcopy(unsandboxed), copy.deepcopy(unsandboxed)],
    }


def rendered(template, context):
    return JINJA.from_string(str(template)).render(context)


def probe_node_findings(tasks, deploy):
    """Args:
        tasks: the parsed ``sandbox.yml``.
        deploy: ``IS_SWARM_MODE``, ``inventory_hostname``, ``STACK_HOST`` and
            ``placement``, the node each service runs on.

    Returns:
        A finding when the probe task runs on another node than the
        provision runner, after the ``_HOST_NODE`` fact of
        ``resolve_host_cid.yml`` that ``sandbox.yml`` includes.
    """
    service = rendered(
        VARIABLES["SEMAPHORE_PROVISION_RUNNER_SERVICE"],
        {"SEMAPHORE_PLATFORM_RUNNERS": VARIABLES["SEMAPHORE_PLATFORM_RUNNERS"]},
    )
    facts = {**deploy, "SEMAPHORE_PROVISION_RUNNER_SERVICE": service}
    for task in tasks:
        if RESOLVER_FILE in str(task.get("ansible.builtin.include_tasks", "")):
            facts |= resolved_facts(task["vars"], facts)
    (probe,) = [task for task in tasks if "SEMAPHORE_SANDBOX_PROBE" in str(task)]
    target = rendered(probe.get("delegate_to", "{{ inventory_hostname }}"), facts)
    runner = deploy["placement"][service]
    if target == runner:
        return []
    return [f"the probe runs on {target}, the provision runner on {runner}"]


def resolved_facts(parameters, facts):
    """Args:
        parameters: the ``vars`` of the include of ``resolve_host_cid.yml``.
        facts: the facts of the deploy.

    Returns:
        The ``<prefix>_HOST_NODE`` fact its ``set_fact`` sets, ``container
        service ps`` answering with the node of the resolved service.
    """
    key = rendered(parameters["resolve_service_key"], facts)
    context = facts | {"_resolve_node": {"stdout": facts["placement"][key]}}
    context["resolve_output_prefix"] = parameters["resolve_output_prefix"]
    resolver = load_yaml_str(read_text(str(RESOLVER / RESOLVER_FILE)))
    found = {}
    for task in resolver:
        for name, value in task.get("ansible.builtin.set_fact", {}).items():
            if name.endswith("_HOST_NODE"):
                found[rendered(name, context)] = rendered(value, context)
    return found


class TestProbeNode(unittest.TestCase):
    def setUp(self):
        self.tasks = load_yaml_str(read_text(str(CHECK)))

    def test_the_probe_runs_on_the_node_of_the_provision_runner(self):
        for mode, deploy in (("compose", COMPOSE), ("swarm", SWARM)):
            with self.subTest(mode=mode):
                self.assertEqual(probe_node_findings(self.tasks, deploy), [])

    def test_negative_control_the_stack_host_is_reported_while_the_runner_is_elsewhere(
        self,
    ):
        (probe,) = [
            task for task in self.tasks if "SEMAPHORE_SANDBOX_PROBE" in str(task)
        ]
        planted = {key: value for key, value in probe.items() if key != "delegate_to"}
        for delegate in ({"delegate_to": "{{ STACK_HOST }}"}, {}):
            with self.subTest(delegate=delegate):
                tasks = [
                    planted | delegate if task is probe else task for task in self.tasks
                ]
                self.assertEqual(
                    probe_node_findings(tasks, SWARM),
                    ["the probe runs on manager-1, the provision runner on worker-2"],
                )
                self.assertEqual(probe_node_findings(tasks, COMPOSE), [])


class TestSandboxCheck(unittest.TestCase):
    def setUp(self):
        self.findings = load_filter()

    def test_the_sandbox_check_fails_on_every_read_a_probe_reports(self):
        self.assertEqual(self.findings(held()), [])
        for read in READS:
            with self.subTest(read=read):
                report = held()
                report["inside"][1]["reads"] = [read]
                self.assertEqual(
                    self.findings(report), [f"the sandbox of probe 2 allowed {read}"]
                )
        broken = {
            "a child that outlived its sandbox": ("child_alive", True),
            "a probe that ended non-zero": ("exit", 1),
            "an IPC object that outlived its sandbox": ("ipc_left", True),
        }
        for what, (key, value) in broken.items():
            with self.subTest(what=what):
                report = held()
                report["inside"][0][key] = value
                self.assertEqual(len(self.findings(report)), 1, what)
        report = held()
        del report["inside"][1]
        self.assertTrue(self.findings(report), "one sandboxed probe passed")

    def test_negative_control_a_blind_probe_fails_the_check(self):
        blind = {
            "the token": ("reads", ["marker"]),
            "the other marker": ("reads", ["token"]),
            "the surviving child": ("child_alive", False),
            "the memory of its child": ("child_mem", False),
            "its IPC object": ("ipc_seen", False),
        }
        for what, (key, value) in blind.items():
            with self.subTest(missed=what):
                report = held()
                report["outside"][0][key] = value
                findings = self.findings(report)
                self.assertEqual(len(findings), 1, findings)
                self.assertIn("the check is blind", findings[0])
        report = held()
        report["outside"] = []
        self.assertTrue(self.findings(report), "a check without a blind probe passed")


if __name__ == "__main__":
    unittest.main()
