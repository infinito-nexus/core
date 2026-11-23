from __future__ import annotations

import copy
import re

import jinja2
from ansible.plugins.filter.core import FilterModule
from ansible.plugins.test.core import TestModule as JinjaTests
from jinja2.nativetypes import NativeEnvironment

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import ROLE, role_task
from .test_spec_secrets_helper import load_helper

SECRETS_TASKS = "03_run_pass/spec_secrets.yml"
QUEUE_TASKS = "03_run_pass/queue.yml"
TEMPLATE_EXISTS = "_playwright_secrets_template_stat.stat.exists"
PROBE_GATE = (
    "_playwright_probe is skipped"
    " or (_playwright_probe.rc is defined and _playwright_probe.rc == 0)"
)
PATH_FACT = "_playwright_spec_secrets_path"
RUNS_FACT = "_playwright_spec_secrets_runs"
SECRETS_PATH = "{{ " + PATH_FACT + " }}"
HELPER_CALL = "{{ role_path }}/files/spec_secrets.py"
HELPER_SHIP = {
    "src": HELPER_CALL,
    "dest": "{{ TEST_E2E_PLAYWRIGHT_TOOLS_DIR }}/spec_secrets.py",
    "mode": "0755",
}
SHIPPED = tuple(
    {"src": f"{{{{ role_path }}}}/files/{name}", "dest": dest, "mode": mode}
    for name, dest, mode in (
        (
            "spec_secrets_match.py",
            "{{ TEST_E2E_PLAYWRIGHT_TOOLS_DIR }}/spec_secrets_match.py",
            "0644",
        ),
        ("spec_secrets_mask.py", "{{ TEST_E2E_PLAYWRIGHT_MASKER }}", "0755"),
    )
)
PYTHON = ["python3", "-I", "-B"]
SERIAL_SCRUB = [
    *PYTHON,
    "{{ TEST_E2E_PLAYWRIGHT_MASKER }}",
    "scrub",
    SECRETS_PATH,
    "{{ _playwright_pass_reports_dir }}",
    "container",
]
PARALLEL_SCRUB = (
    "{{ ['python3', '-I', '-B', TEST_E2E_PLAYWRIGHT_MASKER, 'scrub']"
    " + playwright_spec_secrets_run + ['container'] }}"
)
SHIPPED_HELPER = [*PYTHON, "{{ TEST_E2E_PLAYWRIGHT_TOOLS_DIR }}/spec_secrets.py"]
PRUNE_ARGV = [*SHIPPED_HELPER, "prune"]
CHECKED = ["--grep", "talk admin", "--workers=2"]
SWEEP = {"path": "{{ playwright_spec_secrets_run | first }}", "state": "absent"}
TARGET = "/run/spec-secrets"
SWITCH = ["-e", "INFINITO_PLAYWRIGHT_NO_CAPTURE=true"]
QUIET = ["-e", "NO_COLOR=1", "-e", "FORCE_COLOR=0", "--log-driver=none"]
SECRETS_DIR = "/tmp/infinito-playwright-spec-secrets/run.abc123"
STALE_DIR = "/tmp/infinito-playwright-spec-secrets/run.stale"
STAGE_DIR = "/tmp/test-e2e-playwright/web-app-x"
REPORTS_DIR = "/reports/web-app-x"
MASKER = "/tools/spec_secrets_mask.py"
GUARD = [*PYTHON, "/tools/spec_secrets.py", "guard"]
MASKED = [*PYTHON, MASKER, "mask", SECRETS_DIR, REPORTS_DIR, "--"]
MASK_PREFIX = [*GUARD, *MASKED]
STAGED_MOUNT = f"{SECRETS_DIR}/reports:/reports"
PLAIN_MOUNT = f"{REPORTS_DIR}:/reports"
SALT = "#{{ (2 ** 128) | random }}\n"
KEEP_REMOTE = (
    "not (lookup('ansible.builtin.config', 'DEFAULT_KEEP_REMOTE_FILES') | bool)"
)
IMAGE = "mcr.microsoft.com/playwright:v0-noble"
ARGV_VARS = {
    "IS_SWARM_MODE": True,
    "test_e2e_playwright_keep": False,
    "TEST_E2E_PLAYWRIGHT_GLOBAL_TIMEOUT_MS": "1000",
    "TEST_E2E_PLAYWRIGHT_PROXY": "",
    "test_e2e_playwright_workers": 2,
    "TEST_E2E_PLAYWRIGHT_FULLY_PARALLEL": False,
    "TIMEOUT_FACTOR": 1,
    "TEST_E2E_PLAYWRIGHT_IS_ONION": False,
    "_playwright_stage_dir": STAGE_DIR,
    "_playwright_pass_reports_dir": REPORTS_DIR,
    "TEST_E2E_PLAYWRIGHT_MASKER": MASKER,
    "TEST_E2E_PLAYWRIGHT_TOOLS_DIR": "/tools",
    "_playwright_ca_required": False,
    "TEST_E2E_PLAYWRIGHT_SHARED_NODE_MODULES": "/shared/node_modules",
    "TEST_E2E_PLAYWRIGHT_SHARED_PERSONAS": "/shared/personas",
    "TEST_E2E_PLAYWRIGHT_LDAP_SOCKET_MOUNTED": False,
    "TEST_E2E_PLAYWRIGHT_IMAGE": IMAGE,
    "TEST_E2E_PLAYWRIGHT_COMMAND": "npx playwright test",
    "TEST_E2E_PLAYWRIGHT_ARGUMENTS": ["--max-failures=5"],
}
PLAIN_TAIL = ["/bin/bash", "-lc", ARGV_VARS["TEST_E2E_PLAYWRIGHT_COMMAND"]]
SECRET_TAIL = ["--", *ARGV_VARS["TEST_E2E_PLAYWRIGHT_ARGUMENTS"]]


def role_tasks(task_file: str) -> list[dict]:
    """Parse one task file of the role.

    Args:
        task_file: path below the role's ``tasks`` directory.

    Returns:
        Its top-level tasks.
    """
    return load_yaml_any(str(ROLE / "tasks" / task_file), default_if_missing=[])


def conditions(task: dict) -> list[str]:
    """List a task's ``when`` conditions.

    Args:
        task: a parsed task.

    Returns:
        Its ``when``, a single condition as a list of one, none as empty.
    """
    when = task.get("when", [])
    return when if isinstance(when, list) else [when]


def flattened(task_file: str) -> list[dict]:
    """Parse one task file of the role with each block's tasks in its place.

    Args:
        task_file: path below the role's ``tasks`` directory.

    Returns:
        A copy of its top-level tasks, a block replaced by its tasks, whose
        ``when`` lists the block's conditions before their own.
    """
    flat = []
    for task in copy.deepcopy(role_tasks(task_file)):
        for child in task.get("block", [task]):
            if child is not task:
                child["when"] = [*conditions(task), *conditions(child)]
            flat.append(child)
    return flat


def role_vars() -> dict:
    """Parse the role's ``vars/main.yml``.

    Returns:
        Its variables.
    """
    return load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})


def run_argv() -> str:
    """Return the container ``argv`` expression of the serial run.

    Returns:
        The Jinja expression the parallel job reuses through its YAML alias.
    """
    task = role_task("03_run_pass.yml", "▶️ Run Playwright container")
    return task["ansible.builtin.command"]["argv"]


def env_task() -> dict:
    """Return the task that renders the role-level ``.env``.

    Returns:
        The parsed task.
    """
    return role_task("03_run_pass.yml", "📄 Render .env")


def command_argv(task: dict) -> list:
    """Return the ``argv`` of a command task.

    Args:
        task: a parsed task.

    Returns:
        The argv, or an empty list for any other module or a command line.
    """
    return task.get("ansible.builtin.command", {}).get("argv") or []


def prune_violations(orchestrate: list[dict]) -> list[str]:
    """Check that every run starts by pruning a killed run's secrets with the shipped helper.

    Args:
        orchestrate: the parsed ``01_setup/orchestrate.yml``.

    Returns:
        One message per broken expectation: the prune is not one command
        with exactly ``PRUNE_ARGV`` after the setup that ships ``HELPER_SHIP``
        and before the first run, can fail or reports changed wrongly, also
        for a result without stdout, which Ansible's strict templating raises on.
    """
    problems = []
    pruned = [
        i for i, task in enumerate(orchestrate) if command_argv(task) == PRUNE_ARGV
    ]
    first_run = next(i for i, t in enumerate(orchestrate) if t["name"].startswith("▶"))
    setup = [
        i
        for i, t in enumerate(orchestrate)
        if t.get("ansible.builtin.include_tasks") == "01_setup.yml"
    ]
    if len(pruned) != 1 or pruned[0] > first_run or not setup or setup[0] > pruned[0]:
        return ["a run does not start by removing a killed run's secrets"]
    if HELPER_SHIP not in [
        t.get("ansible.builtin.copy") for t in role_tasks("01_setup.yml")
    ]:
        problems.append("the prune runs a helper the setup does not ship")
    prune = orchestrate[pruned[0]]
    if prune.get("failed_when") is not False:
        problems.append("the prune can fail a role without the template")
    register = str(prune.get("register"))
    template = environment(strict=True).from_string(
        "{{ (" + str(prune.get("changed_when", "true")) + ") | bool }}"
    )
    changed = []
    for value in (
        {"stdout": "spec secrets removed: 1"},
        {"stdout": "nothing to prune"},
        {},
    ):
        try:
            changed.append(template.render(**{register: value}) == "True")
        except jinja2.UndefinedError:
            changed.append("undefined")
    if changed != [True, False, False]:
        problems.append(f"the prune reports changed {changed}")
    return problems


def environment(native: bool = False, strict: bool = False) -> jinja2.Environment:
    """Build a Jinja environment with Ansible's filters and tests.

    Args:
        native: whether templates render to Python values instead of text.
        strict: whether using an undefined value raises, as Ansible does.

    Returns:
        The environment.
    """
    undefined = jinja2.StrictUndefined if strict else jinja2.Undefined
    env = (
        NativeEnvironment(undefined=undefined)
        if native
        else jinja2.Environment(
            autoescape=jinja2.select_autoescape(default_for_string=False),
            undefined=undefined,
        )
    )
    env.filters.update(FilterModule().filters())
    env.tests.update(JinjaTests().tests())
    return env


def holds(conditions, **variables) -> bool:
    """Evaluate a ``when`` the way Ansible does.

    Args:
        conditions: one condition or the list a task holds.
        **variables: the variables in scope.

    Returns:
        Whether every condition is true.
    """
    items = conditions if isinstance(conditions, list) else [conditions]
    env = environment()
    return all(
        env.from_string("{{ (" + item + ") | bool }}").render(**variables) == "True"
        for item in items
    )


def render(expression: str, **variables):
    """Render one Jinja expression to a Python value.

    Args:
        expression: the template, such as a task argument.
        **variables: the variables in scope.

    Returns:
        The rendered value.
    """
    return environment(native=True).from_string(expression).render(**variables)


def render_argv(
    expression: str, template_exists: bool, secrets_dir: str, mask_argv=None
) -> list:
    """Render the container argv of one pass.

    Args:
        expression: the ``argv`` the run task holds.
        template_exists: whether the role ships ``playwright.secrets.j2``.
        secrets_dir: the directory the pass created, stale without the template.
        mask_argv: a ``TEST_E2E_PLAYWRIGHT_MASK_ARGV`` an extra var sets, None
            for the role's own.

    Returns:
        The argv list.
    """
    facts = {
        **ARGV_VARS,
        "_playwright_secrets_template_stat": {"stat": {"exists": template_exists}},
        PATH_FACT: secrets_dir,
    }
    masked = (
        render(role_vars()["TEST_E2E_PLAYWRIGHT_MASK_ARGV"], **facts)
        if mask_argv is None
        else mask_argv
    )
    return render(expression, **facts, TEST_E2E_PLAYWRIGHT_MASK_ARGV=masked)


def mount_violations(expression: str) -> list[str]:
    """Check that only a run with the template mounts the secrets and drops capture.

    Args:
        expression: the container ``argv`` expression.

    Returns:
        One message per broken expectation.
    """
    problems = []
    plain = render_argv(expression, False, STALE_DIR)
    secret = render_argv(expression, True, SECRETS_DIR)
    if any(TARGET in str(item) or "NO_CAPTURE" in str(item) for item in plain):
        problems.append("a run without the template mounts secrets or drops capture")
    if plain[:2] != ["container", "run"]:
        problems.append("a run without the template is wrapped")
    if secret[: len(MASK_PREFIX)] != MASK_PREFIX:
        return [*problems, "a run with the template is not masked on the host"]
    secret = secret[len(MASK_PREFIX) :]
    if secret[:2] != ["docker", "run"]:
        problems.append("a run with the template goes through the CA wrapper")
    secret = [*plain[:1], *secret[1:]]
    reports = [item for item in secret if str(item).endswith(":/reports")]
    if reports != [STAGED_MOUNT]:
        problems.append(f"a run with the template reports into {reports}")
    read_only = [f"{STAGE_DIR}:/e2e:ro", f"{STAGE_DIR}/volume:/volume:ro"]
    if not set(read_only) <= set(secret):
        problems.append("a run with the template may write into the stage dir")
    writable = {item: item.removesuffix(":ro") for item in read_only}
    secret = [writable.get(item, item) for item in secret]
    secret = [PLAIN_MOUNT if item == STAGED_MOUNT else item for item in secret]
    bind = f"type=bind,src={SECRETS_DIR},dst={TARGET},readonly"
    added = ["--mount", bind, *SWITCH, *QUIET, f"--cidfile={SECRETS_DIR}/.cid"]
    starts = [i for i in range(len(secret)) if secret[i : i + len(added)] == added]
    if len(starts) != 1:
        return [*problems, "a run with the template lacks the bind mount or the switch"]
    rest = secret[: starts[0]] + secret[starts[0] + len(added) :]
    if rest[: rest.index(IMAGE) + 1] != plain[: plain.index(IMAGE) + 1]:
        problems.append("the template changes the argv beyond the mount and switch")
    if plain[plain.index(IMAGE) + 1 :] != PLAIN_TAIL:
        problems.append("a run without the template does not run its command")
    if rest[rest.index(IMAGE) + 1 :] != SECRET_TAIL:
        problems.append("a run with the template renders a command, not the masker")
    if starts[0] > secret.index(IMAGE):
        problems.append("the mount lands after the image, as a command argument")
    return problems


def job_violations(content: str) -> list[str]:
    """Check that a queued job keeps the masker and gets its flags after the run.

    Args:
        content: the ``content`` of the task that writes the job file.

    Returns:
        One message per broken expectation.
    """
    found = re.search(r"'argv': (.*?),\s*'env':", content, re.DOTALL)
    problems = []
    for exists in (False, True):
        served = render_argv(run_argv(), exists, SECRETS_DIR)
        at = served.index("run") + 1
        job = render(
            "{{ " + (found.group(1) if found else "[]") + " }}",
            _playwright_argv=served,
            _playwright_parallel_flags=["--name=job"],
            TEST_E2E_PLAYWRIGHT_MASK_ARGV=MASK_PREFIX if exists else [],
        )
        if job != [*served[:at], "--name=job", *served[at:]]:
            problems.append(f"the job argv is wrong with template={exists}")
    return problems


def layout_violations(tasks: list[dict]) -> list[str]:
    """Check where the spec secrets land and that no task prints a value.

    Args:
        tasks: the parsed spec secrets task file.

    Returns:
        One message per broken expectation.
    """
    problems = []
    variables = role_vars()
    if load_helper().PARENT.is_relative_to(
        variables["TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR"]
    ):
        problems.append("the spec secrets parent sits inside the stage dir")
    if any("SPEC_SECRETS" in name for name in variables):
        problems.append("a role variable can move the spec secrets parent")
    modules = [next(k for k in task if k.startswith("ansible.")) for task in tasks]
    expected = ["set_fact", "copy", "copy", "command", "command"]
    if modules != [
        f"ansible.builtin.{m}"
        for m in [*expected, "set_fact", "set_fact", "assert", "copy", "command"]
    ]:
        return [*problems, f"unexpected task sequence {modules}"]
    reset, *shipped, check, create, point, runs, kept, hand, split = tasks
    if reset["ansible.builtin.set_fact"] != {PATH_FACT: ""}:
        problems.append("a failed create leaves the previous pass's directory in place")
    if tuple(task["ansible.builtin.copy"] for task in shipped) != SHIPPED:
        problems.append("the masker the run starts is not the role's helper")
    checked = render(
        str(check["ansible.builtin.command"].get("argv", "")),
        TEST_E2E_PLAYWRIGHT_TOOLS_DIR="/tools",
        TEST_E2E_PLAYWRIGHT_ARGUMENTS=CHECKED,
    )
    if checked != [*PYTHON, "/tools/spec_secrets.py", "arguments", *CHECKED]:
        problems.append("the Playwright arguments reach the container unchecked")
    if create["ansible.builtin.command"].get("argv") != [*SHIPPED_HELPER, "create"]:
        problems.append("the create runs another program than the shipped helper")
    if create.get("become") is not False:
        problems.append("the login user cannot put the copy's temp dir into the run")
    created = {str(create.get("register")): {"stdout": f"{SECRETS_DIR}\n"}}
    if (
        render(point["ansible.builtin.set_fact"].get(PATH_FACT, ""), **created)
        != SECRETS_DIR
    ):
        problems.append("the mount does not follow the new directory")
    listed = runs["ansible.builtin.set_fact"].get(RUNS_FACT, "")
    run = [SECRETS_DIR, REPORTS_DIR]
    for earlier in ([], [["old"]]):
        found = render(
            listed,
            **{RUNS_FACT: earlier},
            **{PATH_FACT: SECRETS_DIR},
            _playwright_pass_reports_dir=REPORTS_DIR,
        )
        if found != [*earlier, run]:
            problems.append(f"the scrub list is wrong after {earlier}")
    if runs.get("when") != "_playwright_dispatch | bool" or "default(" in listed:
        problems.append("a serial pass appends to the parallel scrub list")
    if kept["ansible.builtin.assert"].get("that") != [KEEP_REMOTE]:
        problems.append("a kept remote temp copy of the template goes unnoticed")
    source = env_task()["ansible.builtin.copy"]["content"]
    lookup = source[source.index("lookup(") : source.index(") %}")]
    same = lookup.replace("_playwright_env_template", "_playwright_secrets_template")
    handed = {
        "content": f"{SALT}{{{{ {same}) }}}}",
        "dest": f"{SECRETS_PATH}/.rendered",
        "mode": "0400",
    }
    if hand["ansible.builtin.copy"] != handed:
        problems.append("the template does not reach the run directory as the .env")
    salts = {environment().from_string(SALT).render() for _ in range(2)}
    if len(salts) != 2 or hand.get("diff") is not False:
        problems.append("the copy may print a diff or a checksum of the values alone")
    remote_tmp = {**env_task().get("vars", {}), "ansible_remote_tmp": SECRETS_PATH}
    if hand.get("vars") != remote_tmp:
        problems.append("the copy may leave a temp copy outside the run directory")
    if split["ansible.builtin.command"] != {
        "argv": [*SHIPPED_HELPER, "split", SECRETS_PATH]
    }:
        problems.append("split gets another argument than the run directory")
    if any("no_log" in task for task in tasks):
        problems.append("a task of a test role hides its failure output")
    talkative = [
        task["name"]
        for task in tasks
        if ("register" in task and task is not create)
        or any(key in task for key in ("loop", "with_items", "ansible.builtin.debug"))
    ]
    if talkative:
        problems.append(f"tasks that could print a value: {talkative}")
    return problems
