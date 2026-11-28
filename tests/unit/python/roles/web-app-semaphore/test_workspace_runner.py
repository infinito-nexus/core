from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import tempfile
import tomllib
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

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
DOCKERFILE = ROLE / "files" / "runner" / "Dockerfile"
SPEC = ROLE / "files" / "playwright" / "test-workspace-runners.js"
REMOVE = ROLE / "tasks" / "utils" / "workspace" / "runner" / "remove.yml"
REMOVE_MATCH = re.compile(r"grep -F '([^']+)'")
BASE_ARG = "SEMAPHORE_RUNNER_BASE_IMAGE"
BASE_LABEL = "nexus.infinito.semaphore.runner.base"
FINAL_FROM = f"FROM ${{{BASE_ARG}}}\n\n"
CORE_VERSION_FILE = "/usr/local/share/semaphore-runner/core-version"
RECORD_PROGRAM = re.compile(r"awk -F '\"' '([^']+)'")
SECTION_GUARD = 'section == "[project]" && '
TOOL_FIRST = (
    '[tool.other]\nversion = "0.0.1"\n\n[project]\nname = "infinito"\nversion = "{}"\n'
)
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
        ``meta/services.yml`` or one naming the application, service and tag
        it was asked for.
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
    application, service = terms
    if "version" in kwargs:
        return f'image: "{application}/{service}:{kwargs["version"]}"'
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


def final_stage_labels(dockerfile, args):
    """Args:
    dockerfile: the text of a multi-stage Dockerfile.
    args: the build arguments the compose build passes.

    Returns:
        The labels of the last stage as Docker renders them: an ``ARG`` above
        the first ``FROM`` does not reach into a stage, so ``${NAME}`` holds
        the passed value only where that stage redeclares ``ARG NAME``.
    """
    declared, labels = set(), {}
    for instruction in dockerfile.replace("\\\n", " ").splitlines():
        keyword, _, rest = instruction.strip().partition(" ")
        if keyword == "FROM":
            declared, labels = set(), {}
        elif keyword == "ARG":
            declared.add(rest.strip())
        elif keyword == "LABEL":
            for key, value in re.findall(r'([\w.-]+)="([^"]*)"', rest):
                labels[key] = re.sub(
                    r"\$\{(\w+)\}",
                    lambda match, declared=declared: (
                        str(args[match.group(1)])
                        if match.group(1) in declared and match.group(1) in args
                        else ""
                    ),
                    value,
                )
    return labels


def recorded_version(dockerfile, pyproject):
    """Args:
    dockerfile: the text of the runner Dockerfile.
    pyproject: the ``pyproject.toml`` text of a base image's core tree.

    Returns:
        What the build writes to ``CORE_VERSION_FILE`` for that tree.
    """
    program = RECORD_PROGRAM.search(dockerfile).group(1)
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "pyproject.toml"
        path.write_text(pyproject)
        return subprocess.run(
            ["awk", "-F", '"', program, str(path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.strip()


def workspace_runner_image(variables, version, base):
    """Args:
    variables: the role vars, possibly planted.
    version: ``WORKSPACE_CORE_VERSION``.
    base: ``WORKSPACE_CORE_BASE``, empty for a release.

    Returns:
        ``(SEMAPHORE_WORKSPACE_RUNNER_BASE, SEMAPHORE_WORKSPACE_RUNNER_IMAGE_TAG)``
        for them.
    """
    environment = Environment(autoescape=select_autoescape(default_for_string=False))
    environment.filters["regex_replace"] = lambda text, find, by: re.sub(find, by, text)
    context = {
        "SOFTWARE_IMAGE": "infinito",
        "SEMAPHORE_WORKSPACE_ALIAS": ALIAS,
        "WORKSPACE_CORE_BASE": base,
        "WORKSPACE_CORE_VERSION": version,
    }
    base_template = variables["SEMAPHORE_WORKSPACE_RUNNER_BASE"]
    tag_template = variables["SEMAPHORE_WORKSPACE_RUNNER_IMAGE_TAG"]
    image = environment.from_string(base_template).render(context)
    tag = environment.from_string(tag_template).render(
        {
            **context,
            "SEMAPHORE_WORKSPACE_RUNNER_BASE": image,
            "SEMAPHORE_WORKSPACE_RUNNER_TAG_PREFIX": runner_tag_prefix(variables),
        }
    )
    return image, tag


def runner_tag_prefix(variables):
    """Args:
    variables: the role vars, possibly planted.

    Returns:
        ``SEMAPHORE_WORKSPACE_RUNNER_TAG_PREFIX`` for the workspace ``ALIAS``.
    """
    return (
        Environment(autoescape=select_autoescape(default_for_string=False))
        .from_string(variables["SEMAPHORE_WORKSPACE_RUNNER_TAG_PREFIX"])
        .render(SEMAPHORE_WORKSPACE_ALIAS=ALIAS)
    )


def destroyed_images(shell, variables, listed, failing=""):
    """Args:
    shell: the script of the image step of ``runner/remove.yml``, possibly
        planted.
    variables: the role vars.
    listed: the images ``container image ls`` lists on the stack host.
    failing: ``ls``, ``rm`` or ``grep`` for the command that fails, empty for
        none.

    Returns:
        ``(status, removed)``: the exit status of the step under ``bash`` and
        the listed images a ``destroy`` of the workspace ``ALIAS`` removes.
    """
    environment = Environment(autoescape=select_autoescape(default_for_string=False))
    script = environment.from_string(shell).render(
        SEMAPHORE_RUNNER_LIST_FORMAT=environment.from_string(
            variables["SEMAPHORE_RUNNER_LIST_FORMAT"]
        ).render(),
        SEMAPHORE_WORKSPACE_RUNNER_TAG_PREFIX=runner_tag_prefix(variables),
        semaphore_workspace_alias=ALIAS,
    )
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        stubs = root / "bin"
        stubs.mkdir()
        (stubs / "container").write_text(CONTAINER_STUB)
        (stubs / "container").chmod(0o755)
        if failing == "grep":
            (stubs / "grep").write_text(FAILING_GREP)
            (stubs / "grep").chmod(0o755)
        (root / "listed").write_text("".join(f"{image}\n" for image in listed))
        status = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
            env={
                "PATH": f"{stubs}:{os.environ['PATH']}",
                "LISTED": str(root / "listed"),
                "REMOVED": str(root / "removed"),
                "FAILING": failing,
            },
        ).returncode
        removed = root / "removed"
        return status, (read_text(str(removed)).split() if removed.exists() else [])


def workspace_runner_base(version):
    """Args:
    version: ``WORKSPACE_CORE_VERSION`` of a release.

    Returns:
        ``SEMAPHORE_WORKSPACE_RUNNER_BASE`` of ``vars/main.yml`` for it.
    """
    variables = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
    return workspace_runner_image(variables, version, "")[0]


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


CORE_CHECK = "semaphore_workspace_core_version"
CORE_BUILD = "semaphore_workspace_build"
CORE_UP = "semaphore_workspace_up"
CORE_READ_ARGV = [
    "container",
    "run",
    "--rm",
    "--pull",
    "never",
    "--network",
    "none",
    "--entrypoint",
    "cat",
]
CORE_READ_ENVIRONMENT = {"CA_CONTAINER_ENABLED": "0"}
SPEC_STEP = "`Assert ${result.alias} runs core ${declares}`"
SELECTED = "17.0.0"
OTHER = "16.2.3"
CORE_CHECK_CONTEXT = {
    "application_id": "web-app-semaphore",
    "semaphore_workspace_alias": ALIAS,
    "SEMAPHORE_RUNNER_SERVICE": "task-runner",
    "SEMAPHORE_RUNNER_IMAGE": "semaphore-runner:v17.1.0",
    "SEMAPHORE_WORKSPACE_RUNNER_IMAGE_TAG": IMAGE_TAG,
    "WORKSPACE_CORE_VERSION": SELECTED,
}


def image_lookup(name, *terms, **kwargs):
    """Args:
    name: the lookup a task calls, ``image``.
    terms: its positional terms.
    kwargs: its keyword arguments.

    Returns:
        The reference :func:`lookup` writes into the compose ``image:`` line
        for the same terms.
    """
    return load_yaml_str(lookup(f"container_{name}", *terms, **kwargs))["image"]


def core_version_passes(check, declared):
    """Args:
    check: the assert task of the core version.
    declared: what the runner image records as its core version.

    Returns:
        Whether the assert passes an apply of ``SELECTED``.
    """
    that = check["ansible.builtin.assert"]["that"]
    environment = Environment(autoescape=select_autoescape(default_for_string=False))
    variables = {
        CORE_CHECK: {"stdout": f"{declared}\n", "rc": 0},
        "WORKSPACE_CORE_VERSION": SELECTED,
    }
    return all(
        environment.compile_expression(condition)(variables)
        for condition in ([that] if isinstance(that, str) else that)
    )


def core_version_findings(tasks, image, spec):
    """Args:
    tasks: the parsed tasks of ``tasks/utils/workspace/runner/up.yml``.
    image: the image the compose project runs its runner on.
    spec: the text of ``test-workspace-runners.js``.

    Returns:
        Every way an apply of ``SELECTED`` passes or starts a runner image
        that records another core version, and every step the spec waits for
        in vain.
    """
    environment = Environment(autoescape=select_autoescape(default_for_string=False))
    environment.globals["lookup"] = image_lookup
    names = [
        environment.from_string(task["name"]).render(CORE_CHECK_CONTEXT)
        for task in tasks
    ]
    registers = [task.get("register") for task in tasks]
    step = f"Assert {ALIAS} runs core {SELECTED}"
    checks = [at for at, name in enumerate(names) if step in name]
    findings = []
    if f'expectStep(run, {SPEC_STEP}, ["ok"]);' not in spec:
        findings.append("the spec waits for no core version step of the apply")
    if CORE_CHECK not in registers:
        findings.append("no step reads the core version the runner image records")
    if not checks:
        findings.append(f"no step is named {step}")
    if CORE_CHECK not in registers or not checks:
        return findings
    read = tasks[registers.index(CORE_CHECK)]
    argv = [
        environment.from_string(item).render(CORE_CHECK_CONTEXT)
        for item in read["ansible.builtin.command"]["argv"]
    ]
    if argv[-2:] != [image, CORE_VERSION_FILE]:
        findings.append(f"the check reads {argv[-1]} of {argv[-2]}")
    if argv[:-2] != CORE_READ_ARGV:
        findings.append(f"the check runs {' '.join(argv[:-2])}")
    if read.get("environment") != CORE_READ_ENVIRONMENT:
        findings.append("the check runs with CA injection")
    up_at = registers.index(CORE_UP)
    order = [registers.index(CORE_BUILD), registers.index(CORE_CHECK), checks[0], up_at]
    if order != sorted(order):
        findings.append("the check does not sit between the build and the bring-up")
    if "--no-build" not in tasks[up_at]["ansible.builtin.command"]["argv"]:
        findings.append("the bring-up builds again after the check")
    verdicts = {
        declared: core_version_passes(tasks[checks[0]], declared)
        for declared in (SELECTED, OTHER)
    }
    if verdicts != {SELECTED: True, OTHER: False}:
        findings.append(f"the check of core {SELECTED} passes {verdicts}")
    return findings


OWN_TAG = "ci-0123abcd"
OWN_BUILD = f"registry.local:5000/infinito-nexus/core:{OWN_TAG}"
RELEASE_ONLY_BASE = "{{ SOFTWARE_IMAGE }}:v{{ WORKSPACE_CORE_VERSION }}"
RELEASE_ONLY_MATCH = "grep -F ':{{ semaphore_workspace_alias }}-v'"
RUNNER_REPOSITORY = "web-app-semaphore/task-runner"
RELEASE_RUNNER = f"{RUNNER_REPOSITORY}:{ALIAS}-v17.0.0"
OWN_RUNNER = f"{RUNNER_REPOSITORY}:{ALIAS}-{OWN_TAG}"
OTHER_RUNNERS = [
    f"{RUNNER_REPOSITORY}:ws-11111111-2222-4333-8444-555555555555-{OWN_TAG}",
    f"{RUNNER_REPOSITORY}:v17.1.0",
]
LISTED_RUNNERS = [RELEASE_RUNNER, OWN_RUNNER, *OTHER_RUNNERS]
NO_MATCH_GUARD = ' || [ "$?" -eq 1 ]; }'
CONTAINER_STUB = """#!/bin/sh
if [ "$1 $2" = "image ls" ]; then
  [ "$FAILING" = ls ] && exit 1
  exec cat "$LISTED"
fi
[ "$FAILING" = rm ] && exit 1
shift 2
printf '%s\\n' "$@" >> "$REMOVED"
"""
FAILING_GREP = "#!/bin/sh\ncat >/dev/null\nexit 2\n"
SPELLED_PRUNE = (
    "{{ semaphore_runner_images.stdout_lines"
    " | select('search', ':ws-[0-9a-f-]{36}-[^:/]+$') | list }}"
)


class TestWorkspaceRunnerBase(unittest.TestCase):
    def setUp(self):
        self.variables = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))

    def test_a_release_and_an_own_build_each_tag_the_runner_image(self):
        self.assertEqual(
            workspace_runner_image(self.variables, "17.0.0", ""),
            ("infinito:v17.0.0", IMAGE_TAG),
        )
        self.assertEqual(
            workspace_runner_image(self.variables, "17.1.0", OWN_BUILD),
            (OWN_BUILD, f"{ALIAS}-{OWN_TAG}"),
        )

    def test_negative_control_a_release_only_base_drops_the_own_build(self):
        self.assertNotEqual(
            self.variables["SEMAPHORE_WORKSPACE_RUNNER_BASE"], RELEASE_ONLY_BASE
        )
        planted = {
            **self.variables,
            "SEMAPHORE_WORKSPACE_RUNNER_BASE": RELEASE_ONLY_BASE,
        }
        self.assertEqual(
            workspace_runner_image(self.variables, "17.1.0", OWN_BUILD)[0], OWN_BUILD
        )
        self.assertEqual(
            workspace_runner_image(planted, "17.1.0", OWN_BUILD),
            ("infinito:v17.1.0", f"{ALIAS}-v17.1.0"),
        )


class TestRunnerImageRemoval(unittest.TestCase):
    def setUp(self):
        self.variables = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
        steps = load_yaml_str(read_text(str(REMOVE)))
        self.shell = next(
            step["ansible.builtin.shell"]
            for step in steps
            if "ansible.builtin.shell" in step
        )

    def test_destroy_removes_the_runner_images_of_its_workspace_alone(self):
        self.assertEqual(
            destroyed_images(self.shell, self.variables, LISTED_RUNNERS),
            (0, [RELEASE_RUNNER, OWN_RUNNER]),
        )

    def test_negative_control_a_release_only_matcher_misses_an_own_build(self):
        real = REMOVE_MATCH.search(self.shell).group(0)
        self.assertNotEqual(real, RELEASE_ONLY_MATCH)
        planted = self.shell.replace(real, RELEASE_ONLY_MATCH)
        self.assertIn(
            OWN_RUNNER, destroyed_images(self.shell, self.variables, LISTED_RUNNERS)[1]
        )
        self.assertEqual(
            destroyed_images(planted, self.variables, LISTED_RUNNERS),
            (0, [RELEASE_RUNNER]),
        )

    def test_a_destroy_without_images_of_its_workspace_is_a_clean_no_op(self):
        for listed in (OTHER_RUNNERS, []):
            with self.subTest(listed=listed):
                self.assertEqual(
                    destroyed_images(self.shell, self.variables, listed), (0, [])
                )

    def test_negative_control_a_bare_grep_fails_the_repeated_destroy(self):
        self.assertEqual(self.shell.count(NO_MATCH_GUARD), 1)
        planted = self.shell.replace("{ grep", "grep").replace(NO_MATCH_GUARD, "")
        self.assertEqual(
            destroyed_images(planted, self.variables, OTHER_RUNNERS), (1, [])
        )

    def test_a_failing_listing_match_or_removal_fails_the_destroy(self):
        for failing in ("ls", "grep", "rm"):
            with self.subTest(failing=failing):
                status, _ = destroyed_images(
                    self.shell, self.variables, LISTED_RUNNERS, failing
                )
                self.assertNotEqual(status, 0)

    def test_negative_control_a_blanket_true_hides_a_failing_match(self):
        planted = self.shell.replace(NO_MATCH_GUARD, " || true; }")
        self.assertEqual(
            destroyed_images(planted, self.variables, LISTED_RUNNERS, "grep"), (0, [])
        )


def prune_pattern_findings(variables):
    """Args:
    variables: the role vars, possibly planted.

    Returns:
        Every way the prune of the platform runner reads the workspace runner
        images apart from ``SEMAPHORE_WORKSPACE_RUNNER_TAG_PREFIX``: a regex
        of its own in ``SEMAPHORE_RUNNER_WORKSPACE_IMAGES`` or ``_BASES``, an
        image of the workspace ``ALIAS`` the pattern misses, or a base it
        derives with a rest of the prefix.
    """
    findings = [
        f"{name} spells its own pattern"
        for name in (
            "SEMAPHORE_RUNNER_WORKSPACE_IMAGES",
            "SEMAPHORE_RUNNER_WORKSPACE_BASES",
        )
        if "SEMAPHORE_RUNNER_WORKSPACE_TAG_PATTERN" not in variables[name]
    ]
    pattern = variables["SEMAPHORE_RUNNER_WORKSPACE_TAG_PATTERN"]
    image = f"{RUNNER_REPOSITORY}:{runner_tag_prefix(variables)}{OWN_TAG}"
    if not re.search(f"{pattern}[^:/]+$", image):
        findings.append(f"the pattern misses {image}")
    base = re.sub(f"^.*{pattern}", "infinito:", image)
    if base != f"infinito:{OWN_TAG}":
        findings.append(f"{image} keeps the base {base}")
    return findings


class TestRunnerPrunePattern(unittest.TestCase):
    def setUp(self):
        self.variables = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))

    def test_the_prune_reads_the_workspace_images_by_the_runner_tag_prefix(self):
        self.assertEqual(prune_pattern_findings(self.variables), [])

    def test_negative_control_a_renamed_prefix_or_a_spelled_pattern_is_caught(self):
        renamed = {
            **self.variables,
            "SEMAPHORE_WORKSPACE_RUNNER_TAG_PREFIX": "{{ SEMAPHORE_WORKSPACE_ALIAS }}_",
        }
        image = f"{RUNNER_REPOSITORY}:{ALIAS}_{OWN_TAG}"
        self.assertEqual(
            prune_pattern_findings(renamed),
            [f"the pattern misses {image}", f"{image} keeps the base {image}"],
        )
        spelled = {
            **self.variables,
            "SEMAPHORE_RUNNER_WORKSPACE_IMAGES": SPELLED_PRUNE,
        }
        self.assertEqual(
            prune_pattern_findings(spelled),
            ["SEMAPHORE_RUNNER_WORKSPACE_IMAGES spells its own pattern"],
        )


class TestBringUpChange(unittest.TestCase):
    def test_a_second_apply_with_a_cached_build_reports_no_change(self):
        self.assertIn("--no-build", bring_up()["ansible.builtin.command"]["argv"])
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

    def test_the_runner_image_labels_the_base_of_its_version(self):
        args = self.project["services"]["runner"]["build"]["args"]
        labels = final_stage_labels(read_text(str(DOCKERFILE)), args)
        self.assertEqual(args[BASE_ARG], workspace_runner_base("17.0.0"))
        self.assertEqual(labels[BASE_LABEL], "infinito:v17.0.0")

    def test_negative_control_a_base_arg_left_above_the_stages_labels_nothing(self):
        dockerfile = read_text(str(DOCKERFILE))
        head, _, stage = dockerfile.rpartition(FINAL_FROM)
        planted = head + FINAL_FROM + stage.replace(f"ARG {BASE_ARG}\n", "", 1)
        self.assertNotEqual(planted, dockerfile)
        args = self.project["services"]["runner"]["build"]["args"]
        self.assertEqual(final_stage_labels(planted, args)[BASE_LABEL], "")

    def test_the_runner_image_records_the_version_of_its_base_tree(self):
        dockerfile = read_text(str(DOCKERFILE))
        self.assertIn(f"> {CORE_VERSION_FILE}", dockerfile)
        pyproject = read_text(str(PROJECT_ROOT / "pyproject.toml"))
        self.assertEqual(
            recorded_version(dockerfile, pyproject),
            tomllib.loads(pyproject)["project"]["version"],
        )
        self.assertEqual(
            {
                recorded_version(dockerfile, TOOL_FIRST.format(version))
                for version in ("17.0.0", "16.2.3")
            },
            {"17.0.0", "16.2.3"},
        )

    def test_negative_control_a_record_without_the_project_table_reads_another(self):
        dockerfile = read_text(str(DOCKERFILE))
        planted = dockerfile.replace(SECTION_GUARD, "", 1)
        self.assertNotEqual(planted, dockerfile)
        self.assertEqual(
            {
                recorded_version(planted, TOOL_FIRST.format(version))
                for version in ("17.0.0", "16.2.3")
            },
            {"0.0.1"},
        )

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

    def test_the_apply_asserts_the_core_version_the_runner_image_records(self):
        tasks = load_yaml_str(read_text(str(RUNNER_UP_TASKS)))
        image = self.project["services"]["runner"]["image"]
        spec = read_text(str(SPEC))
        self.assertEqual(core_version_findings(tasks, image, spec), [])

    def test_negative_control_each_weakened_core_version_check_is_reported(self):
        tasks = load_yaml_str(read_text(str(RUNNER_UP_TASKS)))
        image = self.project["services"]["runner"]["image"]
        spec = read_text(str(SPEC))
        expected_step = f'expectStep(run, {SPEC_STEP}, ["ok"]);'
        unspecified = spec.replace(expected_step, "")
        self.assertNotEqual(unspecified, spec)
        read = next(at for at, t in enumerate(tasks) if t.get("register") == CORE_CHECK)
        up = next(at for at, t in enumerate(tasks) if t.get("register") == CORE_UP)
        step = f"Assert {ALIAS} runs core {SELECTED}"
        passed_both = {SELECTED: True, OTHER: True}
        platform = CORE_CHECK_CONTEXT["SEMAPHORE_RUNNER_IMAGE"]
        egress = f"web-app-semaphore/egress:{IMAGE_TAG}"
        dropped = " ".join(
            flag for flag in CORE_READ_ARGV if flag not in ("--network", "none")
        )

        def unchanged(steps):
            return steps

        def without_check(steps):
            del steps[read : read + 2]

        def presence_only(steps):
            steps[read + 1]["ansible.builtin.assert"]["that"] = f"{CORE_CHECK}.rc == 0"

        def platform_image(steps):
            steps[read]["ansible.builtin.command"]["argv"][-2] = (
                "{{ SEMAPHORE_RUNNER_IMAGE }}"
            )

        def swapped_service(steps):
            argv = steps[read]["ansible.builtin.command"]["argv"]
            argv[-2] = argv[-2].replace("SEMAPHORE_RUNNER_SERVICE", "'egress'")

        def network_kept(steps):
            argv = steps[read]["ansible.builtin.command"]["argv"]
            del argv[argv.index("--network") : argv.index("--network") + 2]

        def ca_injected(steps):
            steps[read].pop("environment")

        def read_after_up(steps):
            steps[up + 1 : up + 1] = steps[read : read + 2]
            del steps[read : read + 2]

        def read_before_build(steps):
            steps.insert(0, steps.pop(read))

        def rebuilt_at_up(steps):
            argv = steps[up]["ansible.builtin.command"]["argv"]
            argv[argv.index("--no-build")] = "--build"

        def renamed(steps):
            steps[read + 1]["name"] = "🛡️ Assert the runner image of {{ WORKSPACE }}"

        order = "the check does not sit between the build and the bring-up"
        plants = {
            "the apply without the check": (
                without_check,
                spec,
                [
                    "no step reads the core version the runner image records",
                    f"no step is named {step}",
                ],
            ),
            "a check that only sees the image start": (
                presence_only,
                spec,
                [f"the check of core {SELECTED} passes {passed_both}"],
            ),
            "the platform runner image": (
                platform_image,
                spec,
                [f"the check reads {CORE_VERSION_FILE} of {platform}"],
            ),
            "the image of another service": (
                swapped_service,
                spec,
                [f"the check reads {CORE_VERSION_FILE} of {egress}"],
            ),
            "a read with a network": (
                network_kept,
                spec,
                [f"the check runs {dropped}"],
            ),
            "a read with CA injection": (
                ca_injected,
                spec,
                ["the check runs with CA injection"],
            ),
            "a check after the bring-up": (read_after_up, spec, [order]),
            "a read before the build": (read_before_build, spec, [order]),
            "a bring-up that builds again": (
                rebuilt_at_up,
                spec,
                ["the bring-up builds again after the check"],
            ),
            "a step the spec does not wait for": (
                renamed,
                spec,
                [f"no step is named {step}"],
            ),
            "a spec that waits for no step": (
                unchanged,
                unspecified,
                ["the spec waits for no core version step of the apply"],
            ),
        }
        for name, (plant, text, expected) in plants.items():
            with self.subTest(name):
                steps = copy.deepcopy(tasks)
                plant(steps)
                self.assertEqual(core_version_findings(steps, image, text), expected)

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
        self.assertEqual(runner["image"], f"web-app-semaphore/task-runner:{IMAGE_TAG}")


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
    variables = load_yaml_str(text)
    prefix = variables["SEMAPHORE_WORKSPACE_RUNNER_TAG_PREFIX"]
    if prefix != "{{ SEMAPHORE_WORKSPACE_ALIAS }}-":
        findings.append(f"the runner image tag prefix is {prefix}")
    image_tag = variables["SEMAPHORE_WORKSPACE_RUNNER_IMAGE_TAG"]
    if not image_tag.startswith("{{ SEMAPHORE_WORKSPACE_RUNNER_TAG_PREFIX }}"):
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
        prefix = (
            'SEMAPHORE_WORKSPACE_RUNNER_TAG_PREFIX: "{{ SEMAPHORE_WORKSPACE_ALIAS }}-"'
        )
        self.assertEqual(self.text.count(prefix), 1)
        text = self.text.replace(
            prefix, f'SEMAPHORE_WORKSPACE_RUNNER_TAG_PREFIX: "{SPELLED}-"'
        )
        project = copy.deepcopy(self.project)
        project["services"]["runner"]["environment"]["SEMAPHORE_RUNNER_TAGS"] = (
            IMAGE_TAG
        )
        self.assertEqual(
            tag_findings(text, self.tasks, project, self.applied),
            [
                f"the role vars spell {SPELLED} 2 times",
                f"the runner image tag prefix is {SPELLED}-",
                f"the runner registers with the tag {IMAGE_TAG}",
            ],
        )

    def test_the_stack_host_alone_owns_the_projects_row_and_runner(self):  # nocheck: test.text-presence -- analyzes the parsed task lists, mutation-tested  # fmt: skip
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
