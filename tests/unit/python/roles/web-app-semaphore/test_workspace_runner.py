from __future__ import annotations

import copy
import json
import re
import unittest
from importlib.util import module_from_spec, spec_from_file_location

from jinja2 import Environment, select_autoescape

from plugins.lookup.compose_restart import LookupModule as ComposeRestart
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.networks.render import render_compose_networks, render_container_networks
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_VARS_MAIN,
)

from .files._semaphore_fake import (
    FakeSemaphore,
    load_project,
    platform_spec,
    workspace_spec,
)

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
COMPOSE = ROLE / "templates" / "workspace" / "compose.yml.j2"
FILTERS = ROLE / "filter_plugins" / "semaphore_workspace.py"
SERVICES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_SERVICES)))
VOLUMES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_VOLUMES)))
ALIAS = "ws-0b6f1c2e-3d4a-4b5c-8d6e-7f8091a2b3c4"
HOME = "/home/runner"
TASK_DIR = "/tmp/semaphore"
TOKEN = "/run/secrets/semaphore-runner-token"
WORKSPACE_DIR = f"/opt/compose/semaphore/workspaces/{ALIAS}"
UID = 64201
EGRESS = "egress:3128"
NETWORK_CONTEXT = {
    "application_id": "web-app-semaphore",
    "deployment_mode": "swarm",
    "registry": {},
    "entity_name": lambda role: role.rsplit("-", 1)[-1],
    "lookup_config": lambda app, path, default: default,
    "lookup_database": lambda app, key: "",
}
LOG_LABEL = "infinito.application"
IMAGE_TAG = f"{ALIAS}-v17.0.0"
APPS = {
    "infinito": {
        "active": True,
        "path": "bash",
        "args": ["/opt/app-control/deploy.sh"],
    },
    "infinito-script": {
        "active": True,
        "path": "bash",
        "args": ["/opt/app-control/script.sh"],
    },
}
RESTART_POLICY = "unless-stopped"


def render_template(path):
    """Args:
    path: a repository-relative template the compose file pulls in.

    Returns:
        The template rendered for the role, the way ``lookup('template')``
        renders it.
    """
    environment = Environment(
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
    )
    environment.filters["to_json"] = json.dumps
    return environment.from_string(read_text(str(PROJECT_ROOT / path))).render(
        application_id=NETWORK_CONTEXT["application_id"], DOCKER_LOG_LABEL=LOG_LABEL
    )


def lookup(name, *terms, **kwargs):
    """Args:
    name: the lookup the template calls.
    terms: its positional terms.
    kwargs: its keyword arguments.

    Returns:
        What the lookup renders: the network blocks through the real
        renderers, the restart line of the real ``compose_restart`` in swarm
        mode, the real logging block, an image line from
        ``meta/services.yml`` or the runner tag.
    """
    if name == "compose_restart":
        variables = {
            "DEPLOYMENT_MODE": NETWORK_CONTEXT["deployment_mode"],
            "DOCKER_RESTART_POLICY": RESTART_POLICY,
        }
        return ComposeRestart().run(list(terms), variables=variables, **kwargs)[0]
    if name == "template":
        return render_template(*terms)
    if name == "container_networks":
        return render_container_networks(**NETWORK_CONTEXT, **kwargs)
    if name == "compose_networks":
        return render_compose_networks(
            **{**NETWORK_CONTEXT, "internal": tuple(kwargs.pop("internal"))}, **kwargs
        )
    _, service = terms
    if "version" in kwargs:
        return f'image: "semaphore-runner:{kwargs["version"]}"'
    return f'image: "{SERVICES[service]["image"]}:{SERVICES[service]["version"]}"'


def load_filters():
    """Returns:
    The module ``filter_plugins/semaphore_workspace.py``.
    """
    spec = spec_from_file_location("semaphore_workspace_filters", str(FILTERS))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def proxy_env(egress):
    """Args:
    egress: ``SEMAPHORE_WORKSPACE_EGRESS``, ``<name>:<port>``.

    Returns:
        ``SEMAPHORE_RUNNER_PROXY_ENV`` of ``vars/main.yml`` rendered for it.
    """
    variables = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
    return {
        name: Environment(autoescape=select_autoescape(default_for_string=False))
        .from_string(value)
        .render(SEMAPHORE_WORKSPACE_EGRESS=egress)
        for name, value in variables["SEMAPHORE_RUNNER_PROXY_ENV"].items()
    }


def render():
    """Returns:
    The compose project of one workspace runner, parsed.
    """
    environment = Environment(
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["combine"] = lambda base, extra: {**base, **extra}
    environment.filters["to_json"] = json.dumps
    environment.globals["lookup"] = lookup
    text = environment.from_string(read_text(str(COMPOSE))).render(
        application_id="web-app-semaphore",
        semaphore_workspace_alias=ALIAS,
        semaphore_workspace_dir=WORKSPACE_DIR,
        semaphore_workspace_runner_image_tag=IMAGE_TAG,
        semaphore_workspace_runner_base="infinito:v17.0.0",
        semaphore_workspace_runner_uid=UID,
        SEMAPHORE_RUNNER_SERVICE="task-runner",
        SEMAPHORE_RUNNER_BUILD_DIR="/opt/compose/semaphore/runner",
        SEMAPHORE_RUNNER_INPUTS={
            "SEMAPHORE_RUNNER_UID": 64101,
            "SEMAPHORE_RUNNER_TMP": TASK_DIR,
        },
        SEMAPHORE_RUNNER_BASE_ARG="SEMAPHORE_RUNNER_BASE_IMAGE",
        SEMAPHORE_WORKSPACE_USER="runner",
        SEMAPHORE_WORKSPACE_HOME=HOME,
        SEMAPHORE_RUNNER_TMP=TASK_DIR,
        SEMAPHORE_WEB_ROOT="https://semaphore.example.org",
        SEMAPHORE_RUNNER_TOKEN_FILE=TOKEN,
        SEMAPHORE_WORKSPACE_EGRESS=EGRESS,
        SEMAPHORE_RUNNER_PROXY_ENV=proxy_env(EGRESS),
        SEMAPHORE_EGRESS_SERVICE="egress",
        SEMAPHORE_EGRESS_CONF_FILE=VOLUMES["semaphore_egress_squid_conf"]["mounts"][0][
            "target"
        ],
        SEMAPHORE_EGRESS_HOSTS_FILE=VOLUMES["semaphore_egress_hosts"]["mounts"][0][
            "target"
        ],
        SEMAPHORE_WORKSPACE_NETWORK="workspace",
        SEMAPHORE_APPS_JSON=json.dumps(APPS),
    )
    return load_yaml_str(text)


def lockdown_findings(project):
    """Args:
    project: :func:`render`, possibly planted.

    Returns:
        Every property of the runner service that widens its reach.
    """
    runner = project["services"]["runner"]
    mounts = {entry.split(":")[0] for entry in runner.get("tmpfs", [])}
    findings = []
    if runner.get("read_only") is not True:
        findings.append("the root filesystem is writable")
    if not {HOME, TASK_DIR, "/tmp"} <= mounts:
        findings.append(f"the tmpfs mounts are {sorted(mounts)}")
    if runner.get("cap_drop") != ["ALL"] or runner.get("cap_add"):
        findings.append("capabilities are kept")
    if "no-new-privileges:true" not in runner.get("security_opt", []):
        findings.append("no-new-privileges is off")
    if runner.get("extra_hosts"):
        findings.append("the runner has extra hosts")
    if runner.get("privileged"):
        findings.append("the runner is privileged")
    if runner.get("volumes") != [f"{WORKSPACE_DIR}/runner.token:{TOKEN}:ro"]:
        findings.append(f"the runner mounts {runner.get('volumes')}")
    if sorted(runner.get("networks") or {}) != ["workspace"]:
        findings.append(f"the runner joins {runner.get('networks')}")
    if project["networks"]["workspace"].get("internal") is not True:
        findings.append("the workspace network has a route out")
    return findings


def egress_findings(project):
    """Args:
    project: :func:`render`, possibly planted.

    Returns:
        Why the egress proxy is not the one member of the workspace network
        with a route out, or not the pinned Squid of ``meta/services.yml``.
    """
    egress = project["services"]["egress"]
    findings = []
    if sorted(egress.get("networks") or {}) != ["default", "workspace"]:
        findings.append(f"the egress proxy joins {egress.get('networks')}")
    if sorted(project["networks"]) != ["workspace"]:
        findings.append(f"the project defines {sorted(project['networks'])}")
    pinned = f"{SERVICES['egress']['image']}:{SERVICES['egress']['version']}"
    if egress.get("image") != pinned:
        findings.append(f"the egress proxy runs {egress.get('image')}")
    if egress.get("cap_add") != ["SETUID", "SETGID"] or egress.get("cap_drop") != [
        "ALL"
    ]:
        findings.append("the egress proxy keeps capabilities beyond SETUID and SETGID")
    if egress.get("read_only") is not True:
        findings.append("the egress proxy writes its root filesystem")
    return findings


RUNNER_UP_TASKS = ROLE / "tasks" / "utils" / "workspace" / "runner" / "up.yml"
UNCHANGED_UP = (
    "#1 [runner internal] load build definition from Dockerfile\n"
    "#5 CACHED\n"
    " Service runner  Building\n"
    " Service runner  Built\n"
    " Container semaphore-ws-1-egress-1  Running\n"
    " Container semaphore-ws-1-runner-1  Running\n"
)
CHANGED_UPS = {
    "first start": " Network semaphore-ws-1_workspace  Created\n"
    " Container semaphore-ws-1-runner-1  Started\n",
    "new image": " Service runner  Built\n Container semaphore-ws-1-runner-1  Recreated\n",
    "stopped container": " Container semaphore-ws-1-egress-1  Started\n",
    "orphan": " Container semaphore-ws-1-old-1  Removed\n",
}


def bring_up_changed(task, stderr):
    """Args:
    task: the bring-up task of ``tasks/utils/workspace/runner/up.yml``.
    stderr: what ``compose up -d --build`` printed.

    Returns:
        Whether the task's ``changed_when`` reports a change.
    """
    environment = Environment(autoescape=select_autoescape(default_for_string=False))
    environment.tests["search"] = lambda value, pattern: (
        re.search(pattern, value) is not None
    )
    expression = environment.compile_expression(task["changed_when"])
    return bool(expression(semaphore_workspace_up={"stderr": stderr}))


def bring_up():
    """Returns:
    The task that runs ``compose up`` for the workspace runner.
    """
    tasks = load_yaml_str(read_text(str(RUNNER_UP_TASKS)))
    return next(t for t in tasks if t.get("register") == "semaphore_workspace_up")


class TestBringUpChange(unittest.TestCase):
    def test_a_second_apply_with_a_cached_build_reports_no_change(self):
        self.assertIn("--build", bring_up()["ansible.builtin.command"]["argv"])
        self.assertFalse(bring_up_changed(bring_up(), UNCHANGED_UP))

    def test_each_real_image_or_container_change_is_reported(self):
        for name, stderr in CHANGED_UPS.items():
            with self.subTest(name):
                self.assertTrue(bring_up_changed(bring_up(), UNCHANGED_UP + stderr))

    def test_negative_control_counting_a_cached_build_reports_every_run(self):
        planted = {
            **bring_up(),
            "changed_when": "semaphore_workspace_up.stderr is search('(Created|Recreated|Started|Built)')",
        }
        self.assertTrue(bring_up_changed(planted, UNCHANGED_UP))


class TestWorkspaceRunner(unittest.TestCase):
    def setUp(self):
        self.project = render()

    def test_the_workspace_runner_compose_is_locked_down(self):
        self.assertEqual(lockdown_findings(self.project), [])
        self.assertEqual(self.project["name"], f"semaphore-{ALIAS}")

    def test_negative_control_each_widened_property_is_reported(self):
        plants = {
            "writable root": lambda r, p: r.update(read_only=False),
            "home on disk": lambda r, p: r.update(
                tmpfs=[e for e in r["tmpfs"] if not e.startswith(HOME)]
            ),
            "task dir on disk": lambda r, p: r.update(
                tmpfs=[e for e in r["tmpfs"] if not e.startswith(TASK_DIR)]
            ),
            "kept capabilities": lambda r, p: r.pop("cap_drop"),
            "added capability": lambda r, p: r.update(cap_add=["NET_ADMIN"]),
            "new privileges": lambda r, p: r.update(security_opt=[]),
            "extra host": lambda r, p: r.update(
                extra_hosts=["host.docker.internal:host-gateway"]
            ),
            "privileged": lambda r, p: r.update(privileged=True),
            "docker socket": lambda r, p: r["volumes"].append(
                "/var/run/docker.sock:/var/run/docker.sock"
            ),
            "second network": lambda r, p: r["networks"].update(default={}),
            "routed network": lambda r, p: p["networks"]["workspace"].pop("internal"),
        }
        for name, plant in plants.items():
            with self.subTest(name):
                project = copy.deepcopy(self.project)
                plant(project["services"]["runner"], project)
                self.assertEqual(
                    len(lockdown_findings(project)), 1, lockdown_findings(project)
                )

    def test_the_egress_proxy_alone_has_a_route_out(self):
        self.assertEqual(egress_findings(self.project), [])

    def test_negative_control_each_widened_egress_property_is_reported(self):
        plants = {
            "egress off the workspace": lambda e, p: e["networks"].pop("workspace"),
            "second outside network": lambda e, p: e["networks"].update(outside={}),
            "project network": lambda e, p: p["networks"].update(outside={}),
            "unpinned image": lambda e, p: e.update(image="ubuntu/squid:latest"),
            "added capability": lambda e, p: e["cap_add"].append("NET_ADMIN"),
            "writable root": lambda e, p: e.update(read_only=False),
        }
        for name, plant in plants.items():
            with self.subTest(name):
                project = copy.deepcopy(self.project)
                plant(project["services"]["egress"], project)
                self.assertEqual(
                    len(egress_findings(project)), 1, egress_findings(project)
                )

    def test_the_workspace_runner_takes_one_task_at_a_time(self):
        env = self.project["services"]["runner"]["environment"]
        self.assertEqual(env["SEMAPHORE_RUNNER_ONE_OFF"], "true")
        self.assertEqual(env["SEMAPHORE_RUNNER_MAX_PARALLEL_TASKS"], "1")
        self.assertEqual(env["SEMAPHORE_RUNNER_TAGS"], ALIAS)
        self.assertEqual(self.project["services"]["runner"]["restart"], RESTART_POLICY)

    def test_every_service_restarts_and_tags_its_logs_in_swarm_mode(self):
        for name in ("runner", "egress"):
            with self.subTest(name):
                service = self.project["services"][name]
                self.assertEqual(service.get("restart"), RESTART_POLICY)
                self.assertEqual(service["logging"]["driver"], "journald")
                self.assertEqual(
                    service["logging"]["options"]["tag"], "web-app-semaphore"
                )
                self.assertEqual(service["labels"][LOG_LABEL], "web-app-semaphore")

    def test_the_runner_builds_on_the_selected_version_under_its_own_uid(self):
        runner = self.project["services"]["runner"]
        args = runner["build"]["args"]
        self.assertEqual(args["SEMAPHORE_RUNNER_BASE_IMAGE"], "infinito:v17.0.0")
        self.assertEqual(args["SEMAPHORE_RUNNER_UID"], str(UID))
        self.assertEqual(args["SEMAPHORE_RUNNER_GID"], str(UID))
        self.assertEqual(runner["user"], f"{UID}:{UID}")

    def test_a_new_workspace_gets_a_uid_no_runner_holds(self):
        filters = load_filters()
        self.assertEqual(filters.semaphore_workspace_uid([], 64200), 64200)
        self.assertEqual(
            filters.semaphore_workspace_uid(["64200", "64201", "64203"], 64200), 64202
        )

    def test_the_runner_uid_is_held_by_no_other_container(self):
        filters = load_filters()
        lines = [
            "runner-a semaphore-ws-a runner",
            "egress-a semaphore-ws-a egress",
            "runner-b semaphore-ws-b runner",
            "nextcloud nextcloud application",
            "loose",
        ]
        neighbours = filters.semaphore_workspace_neighbours(lines, "semaphore-ws-a")
        self.assertEqual(neighbours, ["egress-a", "runner-b", "nextcloud", "loose"])

        def top(name, rc, *uids):
            return {
                "semaphore_workspace_container": name,
                "rc": rc,
                "stdout_lines": ["UID", *uids],
            }

        clean = [top("egress-a", 0, "13"), top("runner-b", 0, str(UID + 1))]
        self.assertEqual(filters.semaphore_workspace_uid_findings(clean, UID), [])
        gone = [top("runner-b", 1, str(UID))]
        self.assertEqual(filters.semaphore_workspace_uid_findings(gone, UID), [])

    def test_negative_control_a_second_container_on_the_runner_uid_is_caught(self):
        filters = load_filters()
        clash = [
            {
                "semaphore_workspace_container": "runner-b",
                "rc": 0,
                "stdout_lines": ["UID", "0", f" {UID}"],
            }
        ]
        self.assertEqual(
            filters.semaphore_workspace_uid_findings(clash, UID),
            [f"runner-b runs a process as UID {UID}"],
        )

    def test_the_apply_asserts_the_uid_check_after_the_bring_up(self):
        tasks = load_yaml_str(read_text(str(RUNNER_UP_TASKS)))
        names = [task["name"] for task in tasks]
        bring_up = next(i for i, n in enumerate(names) if n.startswith("🚀 Bring up"))
        assert_at = next(
            i for i, n in enumerate(names) if n.startswith("🛡️ Assert no other")
        )
        self.assertLess(bring_up, assert_at)
        self.assertIn(
            "semaphore_workspace_uid_findings",
            tasks[assert_at]["vars"]["semaphore_workspace_uid_clashes"],
        )

    def test_each_read_key_candidate_is_a_fresh_ed25519_pair(self):
        filters = load_filters()
        first, second = (
            filters.semaphore_ssh_keypair(ALIAS),
            filters.semaphore_ssh_keypair(ALIAS),
        )
        self.assertTrue(
            first["private"].startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
        )
        self.assertEqual(first["public"].split()[0], "ssh-ed25519")
        self.assertEqual(first["public"].split()[2], ALIAS)
        self.assertNotEqual(first["public"], second["public"])

    def test_the_workspace_runner_runs_the_apps_of_the_platform_runners(self):
        runner = self.project["services"]["runner"]
        self.assertEqual(json.loads(runner["environment"]["SEMAPHORE_APPS"]), APPS)
        self.assertEqual(runner["image"], f"semaphore-runner:{IMAGE_TAG}")


SPELLED = "ws-{{ WORKSPACE }}"
OWNER = "inventory_hostname == STACK_HOST"
STACK_HOST_HELD = "STACK_HOST in groups[application_id]"


def tag_findings(text, tasks, project, applied):
    """Args:
        text: the raw role vars.
        tasks: ``{file: parsed tasks}`` of ``workspace.yml`` and ``workspace_stop.yml``.
        project: :func:`render`, possibly planted.
        applied: the entries of the workspace project in ``templates`` of a
            workspace apply's result.

    Returns:
        Every place the runner tag or the name of a workspace comes from another
        source than ``SEMAPHORE_WORKSPACE_ALIAS``.
    """
    findings = []
    if text.count(SPELLED) != 1:
        findings.append(f"the role vars spell {SPELLED} {text.count(SPELLED)} times")
    image_tag = load_yaml_str(text)["SEMAPHORE_WORKSPACE_RUNNER_IMAGE_TAG"]
    if not image_tag.startswith("{{ SEMAPHORE_WORKSPACE_ALIAS }}-v"):
        findings.append(f"the runner image tag is {image_tag}")
    aliases = [
        value
        for steps in tasks.values()
        for task in walk(steps)
        for value in [
            *(task.get("ansible.builtin.set_fact") or {}).items(),
            *(task.get("vars") or {}).items(),
        ]
        if value[0] == "semaphore_workspace_alias"
    ]
    if [value for _, value in aliases] != ["{{ SEMAPHORE_WORKSPACE_ALIAS }}"] * 2:
        findings.append(f"the alias is set as {aliases}")
    tag = project["services"]["runner"]["environment"]["SEMAPHORE_RUNNER_TAGS"]
    if tag != ALIAS:
        findings.append(f"the runner registers with the tag {tag}")
    findings += [
        f"the template {name} runs on {entry['runner_tag']}"
        for name, entry in sorted(applied.items())
        if entry["runner_tag"] != ALIAS
    ]
    return findings


def walk(tasks):
    for task in tasks or []:
        yield task
        yield from walk(task.get("block"))


def owner_findings(tasks):
    """Args:
        tasks: ``{file: parsed tasks}`` of ``workspace.yml`` and ``workspace_stop.yml``.

    Returns:
        Every step that reaches the projects, the runner row or the runner of
        the workspace on another host than the stack host, and every file
        that does not refuse a stack host without the role.
    """
    findings = []
    for name, steps in sorted(tasks.items()):
        for task in steps:
            if "ansible.builtin.assert" in task or "ansible.builtin.set_fact" in task:
                continue
            when = task.get("when") or []
            if OWNER not in ([when] if isinstance(when, str) else when):
                findings.append(f"{name}: {task['name']} runs on every host")
    assertion = tasks["workspace.yml"][0]["ansible.builtin.assert"]["that"]
    if STACK_HOST_HELD not in assertion:
        findings.append("workspace.yml runs without the role on the stack host")
    return findings


class TestOneWorkspaceOwner(unittest.TestCase):
    def setUp(self):
        self.text = read_text(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.tasks = {
            name: load_yaml_str(read_text(str(ROLE / "tasks" / name)))
            for name in ("workspace.yml", "workspace_stop.yml")
        }
        self.project = render()
        mod = load_project()
        api = FakeSemaphore(mod.ApiError)
        mod.converge(api, platform_spec(), lambda seconds: None)
        templates = mod.run_workspace(api, workspace_spec(), lambda seconds: None)[1][
            "result"
        ]["templates"]
        self.applied = {
            name: entry
            for name, entry in templates.items()
            if entry["project_id"] == api.project_id(ALIAS)
        }

    def test_one_alias_names_the_workspace_tags_its_runner_and_its_image(self):
        self.assertEqual(
            tag_findings(self.text, self.tasks, self.project, self.applied), []
        )
        self.assertIn("deploy", self.applied)

    def test_negative_control_a_second_spelling_and_the_image_tag_as_runner_tag_fail(
        self,
    ):
        text = self.text.replace(
            'SEMAPHORE_WORKSPACE_RUNNER_IMAGE_TAG: "{{ SEMAPHORE_WORKSPACE_ALIAS }}',
            f'SEMAPHORE_WORKSPACE_RUNNER_IMAGE_TAG: "{SPELLED}',
        )
        project = copy.deepcopy(self.project)
        project["services"]["runner"]["environment"]["SEMAPHORE_RUNNER_TAGS"] = (
            IMAGE_TAG
        )
        self.assertEqual(
            tag_findings(text, self.tasks, project, self.applied),
            [
                f"the role vars spell {SPELLED} 2 times",
                f"the runner image tag is {SPELLED}-v{{{{ WORKSPACE_CORE_VERSION }}}}",
                f"the runner registers with the tag {IMAGE_TAG}",
            ],
        )

    def test_the_stack_host_alone_owns_the_projects_row_and_runner(self):
        self.assertEqual(owner_findings(self.tasks), [])

    def test_negative_control_a_step_on_every_host_fails(self):
        planted = copy.deepcopy(self.tasks)
        planted["workspace.yml"][2].pop("when")
        planted["workspace_stop.yml"][2].pop("when")
        planted["workspace.yml"][0]["ansible.builtin.assert"]["that"].remove(
            STACK_HOST_HELD
        )
        self.assertEqual(
            owner_findings(planted),
            [
                f"workspace.yml: {planted['workspace.yml'][2]['name']} runs on every host",
                f"workspace_stop.yml: {planted['workspace_stop.yml'][2]['name']} runs on every host",
                "workspace.yml runs without the role on the stack host",
            ],
        )


if __name__ == "__main__":
    unittest.main()
