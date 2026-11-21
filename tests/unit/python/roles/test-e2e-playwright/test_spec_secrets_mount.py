from __future__ import annotations

import copy
import fcntl
import importlib.util
import io
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout, suppress
from pathlib import Path

import jinja2
from ansible.plugins.filter.core import FilterModule
from ansible.plugins.test.core import TestModule as JinjaTests
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT, ROLE, role_task

SECRETS_TASKS = "03_run_pass/spec_secrets.yml"
QUEUE_TASKS = "03_run_pass/queue.yml"
CONFIG = ROLE / "files" / "playwright.config.js"
HELPER = ROLE / "files" / "spec_secrets.py"
RERUN = PROJECT_ROOT / "scripts" / "tests" / "e2e" / "rerun-spec.sh"
MAKEFILE = PROJECT_ROOT / "Makefile"
TEMPLATE_EXISTS = "_playwright_secrets_template_stat.stat.exists"
PATH_FACT = "_playwright_spec_secrets_path"
RUNS_FACT = "_playwright_spec_secrets_runs"
SECRETS_PATH = "{{ " + PATH_FACT + " }}"
HELPER_CALL = "{{ role_path }}/files/spec_secrets.py"
PRUNE_CALL = f"{HELPER_CALL} prune"
HOLD_VARS = {
    "role_path": "/role",
    "TEST_E2E_PLAYWRIGHT_PARALLEL_BUDGET": "9999",
    "TEST_E2E_PLAYWRIGHT_RUN_TIMEOUT_EFFECTIVE": "run-timeout",
    "TEST_E2E_PLAYWRIGHT_MASK_GRACE_SECONDS": "300",
    "TEST_E2E_PLAYWRIGHT_PLAY_PID": "4242",
}
HOLDS = {
    False: "/role/files/spec_secrets.py create 900 4242",
    True: "/role/files/spec_secrets.py create 10299 4242",
}
SHIPPED = (
    {
        "src": "{{ role_path }}/files/spec_secrets.py",
        "dest": "{{ TEST_E2E_PLAYWRIGHT_SHARED_DIR }}/spec_secrets.py",
        "mode": "0755",
    },
    {
        "src": "{{ role_path }}/files/spec_secrets_match.py",
        "dest": "{{ TEST_E2E_PLAYWRIGHT_SHARED_DIR }}/spec_secrets_match.py",
        "mode": "0644",
    },
    {
        "src": "{{ role_path }}/files/spec_secrets_mask.py",
        "dest": "{{ TEST_E2E_PLAYWRIGHT_MASKER }}",
        "mode": "0755",
    },
)
BASELINE = [
    "python3",
    "{{ TEST_E2E_PLAYWRIGHT_MASKER }}",
    "baseline",
    "{{ _playwright_stage_dir }}",
]
SERIAL_SCRUB = [
    "python3",
    "{{ TEST_E2E_PLAYWRIGHT_MASKER }}",
    "scrub",
    SECRETS_PATH,
    "{{ _playwright_stage_dir }}",
    "{{ _playwright_pass_reports_dir }}",
    "container",
]
PARALLEL_SCRUB = (
    "{{ ['python3', TEST_E2E_PLAYWRIGHT_MASKER, 'scrub']"
    " + playwright_spec_secrets_run + ['container'] }}"
)
RECORDING_ENV = (
    "PW_TEST_REPORTER",
    "PLAYWRIGHT_LIST_PRINT_STEPS",
    "PLAYWRIGHT_DASHBOARD",
    "DEBUG",
    "DEBUG_FILE",
)
DROP_RECORDING = (
    'if (captureOff) { process.env.PLAYWRIGHT_NO_COPY_PROMPT = "1";'
    " for (const name of recordingEnv) { delete process.env[name]; } }"
)
PLAY_PID_PIPE = "sed 's/.*) . //; s/ .*//' /proc/$PPID/stat"
SPLIT_CALL = f"{HELPER_CALL} split {{{{ {PATH_FACT} | quote }}}}"
SWEEP = {"path": "{{ playwright_spec_secrets_run | first }}", "state": "absent"}
SALT_LINE = "{{ '#' ~ ((2 ** 256) | random) }}"
TARGET = "/run/spec-secrets"
SWITCH = ["-e", "INFINITO_PLAYWRIGHT_NO_CAPTURE=true"]
NO_COLOR = ["-e", "NO_COLOR=1", "-e", "FORCE_COLOR=0"]
SENTINEL = "Sentinel-Value-9f3c"
BREAK_CHARS = ("\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")
SECRETS_DIR = "/tmp/infinito-playwright-spec-secrets/run.abc123"
STALE_DIR = "/tmp/infinito-playwright-spec-secrets/run.stale"
STAGE_DIR = "/tmp/test-e2e-playwright/web-app-x"
REPORTS_DIR = "/reports/web-app-x"
MASKER = "/shared/spec_secrets_mask.py"
MASK_PREFIX = ["python3", MASKER, "mask", SECRETS_DIR, STAGE_DIR, REPORTS_DIR, "--"]
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
    "TEST_E2E_PLAYWRIGHT_SHARED_NODE_MODULES": "/shared/node_modules",
    "TEST_E2E_PLAYWRIGHT_SHARED_PERSONAS": "/shared/personas",
    "TEST_E2E_PLAYWRIGHT_IMAGE": IMAGE,
    "TEST_E2E_PLAYWRIGHT_COMMAND": "npx playwright test",
}
CAPTURE_SNIPPETS = (
    (
        'const captureOff = (process.env.INFINITO_PLAYWRIGHT_NO_CAPTURE || "")'
        '.toLowerCase() === "true";'
    ),
    (
        'const capture = captureOff ? { trace: "off", screenshot: "off", video: "off" }'
        ' : { trace: keepAll ? "on" : "retain-on-failure",'
        ' screenshot: keepAll ? "on" : "only-on-failure",'
        ' video: keepAll ? "on" : "retain-on-failure" };'
    ),
    DROP_RECORDING,
    'outputDir: captureOff ? "/tmp/test-results" : "/reports/test-results",',
    (
        '...(captureOff ? [] : [["html", { outputFolder: "/reports/playwright-report",'
        ' open: "never" }]])'
    ),
    "...capture }",
)
RESTAGE = (
    'cp "$repo_root/roles/test-e2e-playwright/files/playwright.config.js"'
    ' "$stage_dir/playwright.config.js"'
)
EXEC_WITHOUT_SECRETS = '((${#secret_args[@]})) || exec "${run[@]}"'
HUP_TRAP = "trap 'docker rm --force \"$run_name\" >/dev/null 2>&1; wait; exit 129' HUP"
INT_TRAP = "trap 'docker rm --force \"$run_name\" >/dev/null 2>&1; wait; exit 130' INT"
TERM_TRAP = (
    "trap 'docker rm --force \"$run_name\" >/dev/null 2>&1; wait; exit 143' TERM"
)
MASKED_RUN = (
    'python3 -B "$masker" mask "$secrets_dir" "$stage_dir" "$reports_dir"'
    ' -- "${run[@]}" & wait "$!"'
)
EXIT_REMOVAL = 'docker rm --force "$run_name" >/dev/null 2>&1; '
PRE_SCRUB = 'python3 -B "$masker" scrub "$secrets_dir" "$stage_dir" "$reports_dir"'
EXIT_SCRUB = (
    f'trap \'{EXIT_REMOVAL}python3 -B "$masker" scrub'
    ' "$secrets_dir" "$stage_dir" "$reports_dir" ||'
    ' echo "spec secrets: check $reports_dir and $stage_dir, masking failed" >&2;'
    ' rm -rf -- "$secrets_dir"\' EXIT'
)
CREATE_LOCKED = 'secrets_dir="$(python3 "$spec_secrets" create 0 "$$")"'
CAPTURE_GUARD = '[[ ! "$cmd" =~ $capture_flags ]] ||'
DEFAULT_COMMAND = "npm install --no-fund --no-audit && npx playwright test"
REFUSED_FLAGS = (
    "--reporter=html",
    "--reporter html",
    "--output /e2e/out",
    "--trace on",
    "-c /e2e/tests/alt.config.js",
    "-c/e2e/tests/alt.config.js",
    "--config=/e2e/tests/alt.config.js",
    "--ui",
    "--ui-host 0.0.0.0",
    "--ui-port=8080",
    "-u",
    "-xu",
    "--update-snapshots=all",
)
ALLOWED_FLAGS = (
    "",
    "--grep trace",
    '--grep "talk admin"',
    "--grep-invert slow",
    "--project=chromium -j 4 -x",
)
RERUN_SNIPPETS = (
    'if [[ -f "$repo_root/roles/$role/templates/playwright.secrets.j2" ]]; then',
    CAPTURE_GUARD,
    'spec_secrets="$repo_root/roles/test-e2e-playwright/files/spec_secrets.py"',
    'masker="$repo_root/roles/test-e2e-playwright/files/spec_secrets_mask.py"',
    CREATE_LOCKED,
    EXIT_SCRUB,
    'install -m 0400 "$secrets_file" "$secrets_dir/.rendered"',
    f'python3 "$spec_secrets" split "$secrets_dir" {PRE_SCRUB}',
    HUP_TRAP,
    INT_TRAP,
    TERM_TRAP,
    (
        'secret_args=(--name "$run_name" --mount'
        f' "type=bind,src=$secrets_dir,dst={TARGET},readonly"'
        f" {' '.join(SWITCH + NO_COLOR)})"
        ' fi mkdir -p "$stage_dir/tests" "$stage_dir/volume" "$reports_dir"'
    ),
    '"${secret_args[@]}" -w /e2e "$image"',
    EXEC_WITHOUT_SECRETS,
    MASKED_RUN,
)
RERUN_CALL = "bash scripts/tests/e2e/rerun-spec.sh"
MAKE_FORWARD = f"$(if $(secrets),PLAYWRIGHT_SPEC_SECRETS_FILE=$(secrets) ){RERUN_CALL}"


def load_helper(source: str = ""):
    """Load ``spec_secrets.py``, which the role ships as a plain file.

    Args:
        source: a changed helper source to load instead, for a negative control.

    Returns:
        A fresh module, so a test may change its constants.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = HELPER
        if source:
            path = Path(tmp) / HELPER.name
            path.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("playwright_spec_secrets", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def mutated_helper(*replacements: tuple[str, str]):
    """Load the helper with pieces of its source replaced.

    Args:
        *replacements: pairs of text the helper must hold exactly once and its
            replacement.

    Returns:
        The changed module.
    """
    source = read_text(str(HELPER))
    for old, new in replacements:
        if source.count(old) != 1:
            raise AssertionError(f"the helper no longer holds {old!r} once")
        source = source.replace(old, new)
    return load_helper(source)


def role_tasks(task_file: str) -> list[dict]:
    """Parse one task file of the role.

    Args:
        task_file: path below the role's ``tasks`` directory.

    Returns:
        Its top-level tasks.
    """
    return load_yaml_any(str(ROLE / "tasks" / task_file), default_if_missing=[])


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


def script_call(task: dict) -> str:
    """Return the whitespace-normalised command line of a script task.

    Args:
        task: a parsed task.

    Returns:
        The call, or an empty string for any other module.
    """
    return " ".join(str(task.get("ansible.builtin.script", "")).split())


def jinja() -> jinja2.Environment:
    """Build a Jinja environment with Ansible's filters and tests.

    Returns:
        The environment.
    """
    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False)
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
    return all(
        jinja().from_string("{{ (" + item + ") | bool }}").render(**variables) == "True"
        for item in items
    )


def render_argv(expression: str, template_exists: bool, secrets_dir: str) -> list:
    """Render the container argv of one pass.

    Args:
        expression: the ``argv`` the run task holds.
        template_exists: whether the role ships ``playwright.secrets.j2``.
        secrets_dir: the directory the last pass created, stale when the role
            has no template.

    Returns:
        The argv list.
    """
    env = NativeEnvironment()
    env.filters.update(FilterModule().filters())
    env.tests.update(JinjaTests().tests())
    facts = {
        **ARGV_VARS,
        "_playwright_secrets_template_stat": {"stat": {"exists": template_exists}},
        "_playwright_spec_secrets_path": secrets_dir,
    }
    masked = role_vars()["TEST_E2E_PLAYWRIGHT_MASK_ARGV"]
    facts["TEST_E2E_PLAYWRIGHT_MASK_ARGV"] = env.from_string(masked).render(**facts)
    return env.from_string(expression).render(**facts)


def job_argv(content: str, template_exists: bool) -> list:
    """Render the argv a queued job hands to the scheduler.

    Args:
        content: the ``content`` of the task that writes the job file.
        template_exists: whether the role ships ``playwright.secrets.j2``.

    Returns:
        The argv the scheduler starts.
    """
    found = re.search(r"'argv': (.*?),\s*'env':", content, re.DOTALL)
    if not found:
        return []
    env = NativeEnvironment()
    env.filters.update(FilterModule().filters())
    masked = MASK_PREFIX if template_exists else []
    return env.from_string("{{ " + found.group(1) + " }}").render(
        _playwright_argv=render_argv(run_argv(), template_exists, SECRETS_DIR),
        _playwright_parallel_flags=["--name=job"],
        TEST_E2E_PLAYWRIGHT_MASK_ARGV=masked,
    )


def job_violations(content: str) -> list[str]:
    """Check that a queued job keeps the masker and gets its flags after the run.

    Args:
        content: the ``content`` of the task that writes the job file.

    Returns:
        One message per broken expectation.
    """
    problems = []
    for template_exists in (False, True):
        served = render_argv(run_argv(), template_exists, SECRETS_DIR)
        at = served.index("container") + 2
        expected = [*served[:at], "--name=job", *served[at:]]
        if job_argv(content, template_exists) != expected:
            problems.append(f"the job argv is wrong with template={template_exists}")
    return problems


def render_salted(content: str) -> str:
    """Render the copy task's content with a stub template lookup.

    Args:
        content: the ``content`` of the render task.

    Returns:
        What the task writes to ``.rendered``.
    """
    env = jinja()
    env.globals["lookup"] = lambda name, *terms, **kwargs: f"A_KEY={SENTINEL}"
    return env.from_string(content).render(
        _playwright_secrets_template="playwright.secrets.j2",
        _playwright_pass_domain="web-app-x.example",
    )


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
        problems.append("a run with the template is not masked on the host")
        return problems
    secret = secret[len(MASK_PREFIX) :]
    bind = f"type=bind,src={SECRETS_DIR},dst={TARGET},readonly"
    added = ["--mount", bind, *SWITCH, *NO_COLOR, f"--cidfile={SECRETS_DIR}/.cid"]
    starts = [i for i in range(len(secret)) if secret[i : i + len(added)] == added]
    if len(starts) != 1:
        problems.append("a run with the template lacks the bind mount or the switch")
        return problems
    if secret[: starts[0]] + secret[starts[0] + len(added) :] != plain:
        problems.append("the template changes the argv beyond the mount and switch")
    if starts[0] > secret.index(IMAGE):
        problems.append("the mount lands after the image, as a command argument")
    at = plain.index("--env-file")
    if plain[at : at + 2] != ["--env-file", f"{STAGE_DIR}/.env"]:
        problems.append("the role-level .env is no longer passed as before")
    return problems


def hold_violations(create: dict) -> list[str]:
    """Render the create call for a serial and a parallel pass.

    Args:
        create: the task that creates the run directory.

    Returns:
        One message per pass whose child holds for anything but its own bound.
    """
    env = jinja()
    env.globals["lookup"] = lambda name, *terms, **kwargs: (
        "600" if (name, terms) == ("timeout", ("run-timeout",)) else ""
    )
    problems = []
    for dispatch, expected in HOLDS.items():
        call = " ".join(
            env.from_string(script_call(create))
            .render(**HOLD_VARS, _playwright_dispatch=dispatch)
            .split()
        )
        if call != expected:
            problems.append(
                f"a {'parallel' if dispatch else 'serial'} pass runs {call}"
            )
    return problems


def recording_env_violations(config: str) -> list[str]:
    """Check that the switch deletes every variable that brings recording back.

    Args:
        config: the text of ``playwright.config.js``.

    Returns:
        One message per variable that survives the switch.
    """
    flat = " ".join(config.split())
    listed = re.search(r"const recordingEnv = \[([^\]]*)\];", flat)
    names = set(re.findall(r'"([A-Z_]+)"', listed.group(1))) if listed else set()
    problems = [
        f"{name} survives the switch" for name in RECORDING_ENV if name not in names
    ]
    if DROP_RECORDING not in flat:
        problems.append("the switch does not delete the recording variables")
    return problems


def point_violations(point: dict, register: str) -> list[str]:
    """Render the facts that point the mount, the masking and the sweep.

    Args:
        point: the ``set_fact`` task after the create.
        register: the name the create registers its output under.

    Returns:
        One message per fact that misses the new directory or drops a run.
    """
    env = NativeEnvironment()
    created = {register: {"stdout": f"{SECRETS_DIR}\n"}}
    facts = {
        **created,
        "_playwright_stage_dir": STAGE_DIR,
        "_playwright_pass_reports_dir": REPORTS_DIR,
    }
    run = [SECRETS_DIR, STAGE_DIR, REPORTS_DIR]
    args = point["ansible.builtin.set_fact"]
    problems = []
    if sorted(args) != [PATH_FACT, RUNS_FACT]:
        return [f"the set_fact sets {sorted(args)}"]
    if env.from_string(args[PATH_FACT]).render(**facts) != SECRETS_DIR:
        problems.append("the mount does not follow the new directory")
    for earlier, expected in (({}, [run]), ({RUNS_FACT: [["old"]]}, [["old"], run])):
        if env.from_string(args[RUNS_FACT]).render(**facts, **earlier) != expected:
            problems.append(f"the masking and sweep list is wrong after {earlier}")
    return problems


def layout_violations(tasks: list[dict], dotenv: dict, variables: dict) -> list[str]:
    """Check where the spec secrets land and that no task prints a value.

    Args:
        tasks: the parsed spec secrets task file.
        dotenv: the task that renders the role-level ``.env``.
        variables: the role's ``vars/main.yml``.

    Returns:
        One message per broken expectation.
    """
    problems = []
    if load_helper().PARENT.is_relative_to(
        variables["TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR"]
    ):
        problems.append("the spec secrets parent sits inside the stage dir")
    if any("SPEC_SECRETS" in name for name in variables):
        problems.append("a role variable can move the spec secrets parent")
    env = jinja()
    env.globals["lookup"] = lambda name, *terms, **kwargs: (
        "4242" if (name, terms) == ("pipe", (PLAY_PID_PIPE,)) else ""
    )
    play_pid = str(variables.get("TEST_E2E_PLAYWRIGHT_PLAY_PID", ""))
    for connection, expected in (("local", "4242"), ("ssh", "0")):
        found = env.from_string(play_pid).render(ansible_connection=connection).strip()
        if found != expected:
            problems.append(f"over {connection} the owner pid is {found!r}")
    modules = [
        next(key for key in task if key.startswith("ansible.")) for task in tasks
    ]
    if modules != [
        "ansible.builtin.copy",
        "ansible.builtin.copy",
        "ansible.builtin.copy",
        "ansible.builtin.command",
        "ansible.builtin.script",
        "ansible.builtin.set_fact",
        "ansible.builtin.copy",
        "ansible.builtin.script",
    ]:
        problems.append(f"unexpected task sequence {modules}")
        return problems
    *shipped, kept, create, point, render, split = tasks
    if tuple(task["ansible.builtin.copy"] for task in shipped) != SHIPPED:
        problems.append("the masker the run starts is not the role's helper")
    if kept["ansible.builtin.command"].get("argv") != BASELINE:
        problems.append("the fresh stage dir's digests are not kept for a rerun")
    if script_call(split) != SPLIT_CALL:
        problems.append("split gets another argument than the run directory")
    problems.extend(hold_violations(create))
    problems.extend(point_violations(point, str(create.get("register"))))
    args = render["ansible.builtin.copy"]
    if (args.get("mode"), args.get("owner"), args.get("group")) != (
        "0400",
        "root",
        "root",
    ):
        problems.append("the rendered template is not 0400 root:root")
    if args.get("dest") != f"{SECRETS_PATH}/.rendered":
        problems.append("the template renders outside the spec secrets directory")
    if render.get("diff") is not False:
        problems.append("the render task may print the values as a diff")
    source = dotenv["ansible.builtin.copy"]["content"]
    lookup = source[source.index("lookup(") : source.index(") %}")]
    same = lookup.replace("_playwright_env_template", "_playwright_secrets_template")
    if args.get("content") != f"{SALT_LINE}\n{{{{ {same}) }}}}\n":
        problems.append("the template is not looked up as the .env is, behind a salt")
    if render.get("vars") != dotenv.get("vars"):
        problems.append("the template is not rendered with the .env variables")
    talkative = [
        task["name"]
        for task in tasks
        if ("register" in task and task is not create)
        or any(key in task for key in ("loop", "with_items", "ansible.builtin.debug"))
    ]
    if talkative:
        problems.append(f"tasks that could print a value: {talkative}")
    return problems


def cleanup_violations(
    run_pass: list[dict], parallel: list[dict], orchestrate: list[dict]
) -> list[str]:
    """Check that every path that writes the secrets also removes them.

    Args:
        run_pass: the parsed ``03_run_pass.yml``.
        parallel: the parsed ``01_setup/parallel.yml``.
        orchestrate: the parsed ``01_setup/orchestrate.yml``.

    Returns:
        One message per broken expectation.
    """
    problems = []
    serial = next(t for t in run_pass if t["name"].startswith("🏃"))
    queue = next(t for t in run_pass if t["name"].startswith("📬"))
    queued = (
        role_tasks(QUEUE_TASKS)
        if queue.get("ansible.builtin.include_tasks") == QUEUE_TASKS
        else []
    )
    for name, tasks in ((serial["name"], serial["block"]), (queue["name"], queued)):
        first = tasks[0] if tasks else {}
        wiring = (first.get("ansible.builtin.include_tasks"), first.get("when"))
        if wiring != (SECRETS_TASKS, TEMPLATE_EXISTS):
            problems.append(f"{name} writes no secrets before its run")
    removal = {"path": SECRETS_PATH, "state": "absent"}
    guards = [task for task in serial.get("always", []) if "block" in task]
    guard = guards[0] if len(guards) == 1 else {}
    closing = guard.get("block", [])
    removes = [task for task in closing if task.get("ansible.builtin.file") == removal]
    scrubs = [
        task
        for task in closing
        if task.get("ansible.builtin.command", {}).get("argv") == SERIAL_SCRUB
    ]
    if len(removes) != 1:
        problems.append("the serial run removes no secrets in its always section")
    elif (
        len(scrubs) != 1
        or closing.index(scrubs[0]) > closing.index(removes[0])
        or scrubs[0].get("when") != removes[0].get("when")
    ):
        problems.append("the serial run does not mask its files before the removal")
    else:
        cases = (
            (True, {PATH_FACT: SECRETS_DIR}, True),
            (True, {}, False),
            (False, {PATH_FACT: STALE_DIR}, False),
        )
        for exists, facts, expected in cases:
            actual = holds(
                guard.get("when", []),
                _playwright_secrets_template_stat={"stat": {"exists": exists}},
                **facts,
            )
            if actual != expected:
                problems.append(f"serial cleanup decides {actual} for {facts}")
    start = next(t for t in parallel if t["name"].startswith("📝 Start"))
    if start["ansible.builtin.set_fact"].get(RUNS_FACT) != []:
        problems.append("the parallel run does not start with an empty sweep list")
    staging = next(t for t in parallel if t["name"].startswith("📦"))
    always = staging.get("always", [])
    looped = "{{ " + RUNS_FACT + " }}"
    sweeps = [
        index
        for index, task in enumerate(always)
        if task.get("ansible.builtin.file") == SWEEP and task.get("loop") == looped
    ]
    scrubs = [
        index
        for index, task in enumerate(always)
        if task.get("ansible.builtin.command", {}).get("argv") == PARALLEL_SCRUB
        and task.get("loop") == looped
    ]
    reaped = [
        index
        for index, task in enumerate(always)
        if task["name"].startswith("🧹 Remove any")
    ]
    if len(sweeps) != 1 or len(reaped) != 1 or sweeps[0] < reaped[0]:
        problems.append("the parallel run removes no secrets after its containers")
    elif always[sweeps[0]].get("failed_when") is not False:
        problems.append("a failed sweep would skip the parallel run's reports")
    elif len(scrubs) != 1 or not reaped[0] < scrubs[0] < sweeps[0]:
        problems.append("the parallel run does not mask its files after its containers")
    elif "failed_when" in always[scrubs[0]]:
        problems.append("a failed masking would not fail the parallel run")
    names = [task["name"] for task in orchestrate]
    pruned = [
        i for i, task in enumerate(orchestrate) if script_call(task) == PRUNE_CALL
    ]
    first_run = next(i for i, name in enumerate(names) if name.startswith("▶"))
    if len(pruned) != 1 or pruned[0] > first_run:
        problems.append("a run does not start by removing a killed run's secrets")
    elif orchestrate[pruned[0]].get("failed_when") is not False:
        problems.append("the prune can fail a role without the template")
    return problems


def capture_violations(config: str) -> list[str]:
    """Check that the switch turns every recording of form input off.

    Args:
        config: the text of ``playwright.config.js``.

    Returns:
        One message per broken expectation.
    """
    flat = " ".join(config.split())
    problems = [
        f"playwright.config.js lost: {snippet}"
        for snippet in CAPTURE_SNIPPETS
        if snippet not in flat
    ]
    problems.extend(
        f"{key} is set outside the capture switch"
        for key in ("trace:", "screenshot:", "video:")
        if flat.count(key) != 2
    )
    if flat.count('["html"') != 1 or flat.count("outputDir:") != 1:
        problems.append("a report or output path is set outside the switch")
    return problems


def rerun_violations(script: str, makefile: str) -> list[str]:
    """Check that a rerun mounts the secrets the way the runner does.

    Args:
        script: the text of ``rerun-spec.sh``.
        makefile: the text of the ``Makefile``.

    Returns:
        One message per broken expectation.
    """
    flat = " ".join(script.replace("\\\n", " ").split())
    problems = [
        f"rerun-spec.sh lost: {snippet}"
        for snippet in RERUN_SNIPPETS
        if snippet not in flat
    ]
    if any(marker in script for marker in ("read -r", "IFS=")):
        problems.append("rerun-spec.sh parses the secrets itself")
    if makefile.count(MAKE_FORWARD) != 2:
        problems.append("a playwright make target does not forward secrets=")
    return problems


def restage_violations(script: str) -> list[str]:
    """Check that every rerun restages the config before the container starts.

    Args:
        script: the text of ``rerun-spec.sh``.

    Returns:
        One message per broken expectation.
    """
    lines = [line.strip() for line in script.splitlines()]
    if RESTAGE not in lines:
        return ["rerun-spec.sh keeps a stale playwright.config.js"]
    at = lines.index(RESTAGE)
    if script.splitlines()[at].startswith((" ", "\t")):
        return ["rerun-spec.sh restages the config only on some reruns"]
    if at > lines.index("run=(docker run --rm"):
        return ["rerun-spec.sh restages the config after the run"]
    return []


def run_helper(module, *args: str) -> tuple[int, str]:
    """Run one helper command and capture everything it prints.

    Args:
        module: the loaded helper.
        *args: the command and its arguments.

    Returns:
        The exit code and the joined stdout and stderr.
    """
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = module.main(["spec_secrets.py", *args])
    return code, out.getvalue() + err.getvalue()


def flag_violations(script: str) -> list[str]:
    """Run the rerun's capture flag guard against flags it must refuse or allow.

    Args:
        script: the text of ``rerun-spec.sh``.

    Returns:
        One message per flag the guard decides wrongly.
    """
    found = re.search(r"capture_flags='([^']*)'", script)
    if not found:
        return ["rerun-spec.sh has no capture flag guard"]
    cases = [(flags, True) for flags in REFUSED_FLAGS]
    cases += [(flags, False) for flags in ALLOWED_FLAGS]
    problems = []
    for flags, refused in cases:
        cmd = f"{DEFAULT_COMMAND} {flags}".rstrip()
        check = ["bash", "-c", '[[ "$1" =~ $2 ]]', "_", cmd, found.group(1)]
        if (subprocess.run(check, check=False).returncode == 0) != refused:
            problems.append(f"{'allows' if refused else 'refuses'} {flags!r}")
    return problems


def lockable(descriptor: int) -> bool:
    """Tell whether no other open file holds a lock on a directory.

    Args:
        descriptor: an own descriptor of the run directory.

    Returns:
        Whether an exclusive lock was free.
    """
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    return True


def wait_for(condition, seconds: float = 5) -> bool:
    """Poll a condition until it holds or the time is up.

    Args:
        condition: a callable without arguments.
        seconds: the longest to wait.

    Returns:
        Whether the condition held in time.
    """
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.02)
    return condition()


def owner_violations(module) -> list[str]:
    """Kill the owner of a held run directory and watch the child clean up.

    Args:
        module: the loaded helper.

    Returns:
        One message per broken expectation.
    """
    module.POLL_SECONDS = 0.05
    owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    problems = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            directory = module.create(0, owner.pid)
            watch = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                if lockable(watch):
                    problems.append("no child holds the lock while the owner lives")
                owner.kill()
                owner.wait()
                if not wait_for(lambda: not directory.exists(), 1):
                    problems.append("the directory outlives its owner")
                if not wait_for(lambda: lockable(watch), 1):
                    problems.append("the child outlives its owner")
            finally:
                os.close(watch)
    finally:
        owner.kill()
        owner.wait()
    return problems


def confinement_violations(module) -> list[str]:
    """Point a run entry at a directory outside ``PARENT`` and split and prune it.

    Args:
        module: the loaded helper.

    Returns:
        One message per file the helper touched outside ``PARENT``.
    """
    with tempfile.TemporaryDirectory() as tmp:
        module.PARENT = Path(tmp) / "spec-secrets"
        module.create(0, 0)
        outside = Path(tmp) / "outside"
        outside.mkdir(mode=0o700)
        (outside / ".rendered").write_text(f"A_KEY={SENTINEL}\n")
        link = module.PARENT / "run.link"
        link.symlink_to(outside)
        code, printed = run_helper(module, "split", str(link))
        with suppress(OSError):
            run_helper(module, "prune")
        left = sorted(path.name for path in outside.iterdir())
        problems = [] if code == 1 and "refused" in printed else [f"split rc {code}"]
        if left != [".rendered"]:
            problems.append(f"the helper left {left} outside the parent")
        return problems


def split_rendered(module, text: str) -> tuple[Path, int, str]:
    """Create a run directory, drop a rendered template in it and split it.

    Args:
        module: the loaded helper, its ``PARENT`` already moved to a scratch dir.
        text: the rendered template.

    Returns:
        The run directory, the exit code and everything printed.
    """
    directory = module.create(0, 0)
    (directory / ".rendered").write_bytes(text.encode("utf-8"))
    code, printed = run_helper(module, "split", str(directory))
    return directory, code, printed


def parse_leak_violations(module) -> list[str]:
    """Hide a key-shaped fragment behind each line break other than LF.

    Args:
        module: the loaded helper.

    Returns:
        One message per break that splits a value, writes a file or prints text.
    """
    problems = []
    for char in BREAK_CHARS:
        for fragment in ("SEED_FRAGMENT", "seed_fragment"):
            with tempfile.TemporaryDirectory() as tmp:
                module.PARENT = Path(tmp) / "spec-secrets"
                rendered = f"#salt\nA_KEY={SENTINEL}{char}{fragment}=tail\n"
                directory, code, printed = split_rendered(module, rendered)
                shown = [
                    text for text in (SENTINEL, fragment, "tail") if text in printed
                ]
                written = sorted(path.name for path in directory.iterdir())
                if code != 1 or shown or written:
                    problems.append(f"{char!r}: rc {code}, printed {shown}, {written}")
    return problems


def file_violations(directory: Path, expected: dict[str, str]) -> list[str]:
    """Check the written secrets: names, modes, owner and content.

    Args:
        directory: the spec secrets directory.
        expected: every key with the value its file must hold.

    Returns:
        One message per broken expectation, naming keys only.
    """
    problems = []
    if stat.S_IMODE(directory.lstat().st_mode) != 0o700:
        problems.append("the directory is not 0700")
    present = sorted(path.name for path in directory.iterdir())
    if present != sorted(expected):
        problems.append(f"the directory holds {present}")
    for key, value in expected.items():
        path = directory / key
        if not path.exists():
            continue
        info = path.lstat()
        if stat.S_IMODE(info.st_mode) != 0o400:
            problems.append(f"{key} has mode {stat.S_IMODE(info.st_mode):04o}")
        if info.st_uid != os.geteuid():
            problems.append(f"{key} is not owned by the writing user")
        if path.read_bytes().decode("utf-8") != value:  # nocheck: cache-read
            problems.append(f"{key} holds the wrong value")
    return problems


def role_vars() -> dict:
    """Parse the role's ``vars/main.yml``.

    Returns:
        Its variables.
    """
    return load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})


class TestSpecSecretsMount(unittest.TestCase):
    def test_only_a_role_with_the_template_gets_the_mount_and_the_switch(self) -> None:
        self.assertEqual(mount_violations(run_argv()), [])
        queued = role_task("03_run_pass.yml", "📬")["vars"]["_playwright_argv"]
        self.assertEqual(queued, run_argv())

    def test_the_role_level_env_file_is_untouched(self) -> None:
        self.assertEqual(env_task()["ansible.builtin.copy"]["mode"], "0644")
        self.assertNotIn("secrets", str(env_task()))

    def test_the_secrets_land_0400_in_a_0700_dir_and_no_task_prints_one(self) -> None:
        tasks = role_tasks(SECRETS_TASKS)
        self.assertEqual(layout_violations(tasks, env_task(), role_vars()), [])

    def test_the_rendered_file_starts_with_a_fresh_salt_the_helper_skips(self) -> None:
        render = role_task(SECRETS_TASKS, "📄")
        content = render["ansible.builtin.copy"]["content"]
        first, second = render_salted(content), render_salted(content)
        self.assertNotEqual(first.splitlines()[0], second.splitlines()[0])
        self.assertRegex(first.splitlines()[0], r"^#\d{20,}$")
        self.assertEqual(load_helper().parse(first), {"A_KEY": SENTINEL})

    def test_the_cleanup_runs_after_success_failure_and_a_killed_run(self) -> None:
        problems = cleanup_violations(
            role_tasks("03_run_pass.yml"),
            role_tasks("01_setup/parallel.yml"),
            role_tasks("01_setup/orchestrate.yml"),
        )
        self.assertEqual(problems, [])

    def test_capture_and_failure_context_are_off_only_with_the_switch(self) -> None:
        self.assertEqual(capture_violations(read_text(str(CONFIG))), [])

    def test_a_queued_job_keeps_the_masker_and_its_flags(self) -> None:
        content = role_task(QUEUE_TASKS, "📮")["ansible.builtin.copy"]["content"]
        self.assertEqual(job_violations(content), [])

    def test_the_switch_drops_env_that_turns_recording_back_on(self) -> None:
        self.assertEqual(recording_env_violations(read_text(str(CONFIG))), [])

    def test_a_serial_pass_holds_its_lock_for_its_own_run_timeout(self) -> None:
        create = role_task(SECRETS_TASKS, "📁")
        self.assertEqual(hold_violations(create), [])

    def test_a_rerun_mounts_locks_and_switches_like_the_runner(self) -> None:
        problems = rerun_violations(read_text(str(RERUN)), read_text(str(MAKEFILE)))
        self.assertEqual(problems, [])

    def test_every_rerun_restages_the_config_a_stale_stack_lacks(self) -> None:
        self.assertEqual(restage_violations(read_text(str(RERUN))), [])

    def test_a_rerun_refuses_every_flag_that_bypasses_the_switch(self) -> None:
        self.assertEqual(flag_violations(read_text(str(RERUN))), [])

    def test_the_helper_writes_0400_files_and_prints_a_count_only(self) -> None:
        module = load_helper()
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            directory, code, printed = split_rendered(
                module,
                f"#salt\n\nE2E_PASSWORD={SENTINEL}\nCLIENT_KEY={SENTINEL}=tail \n",
            )
            self.assertEqual((code, printed), (0, "spec secrets files written: 2\n"))
            expected = {"E2E_PASSWORD": SENTINEL, "CLIENT_KEY": f"{SENTINEL}=tail "}
            self.assertEqual(file_violations(directory, expected), [])

    def test_the_helper_names_a_bad_line_by_number_only(self) -> None:
        module = load_helper()
        cases = (
            (
                f"A_KEY={SENTINEL}\nA_KEY=other\n".encode(),
                "line 2 repeats an earlier key",
            ),
            (f"lower_key={SENTINEL}\n".encode(), "line 1 is not KEY=VALUE"),
            (f"A_KEY=x\n{SENTINEL}\n".encode(), "line 2 is not KEY=VALUE"),
            (f"{'K' * 256}={SENTINEL}\n".encode(), "line 1 is not KEY=VALUE"),
            (b"A_KEY=\xff\n", "not UTF-8"),
        )
        for rendered, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                module.PARENT = Path(tmp) / "spec-secrets"
                directory = module.create(0, 0)
                (directory / ".rendered").write_bytes(rendered)
                code, printed = run_helper(module, "split", str(directory))
                self.assertEqual(code, 1)
                self.assertIn(message, printed)
                for text in (SENTINEL, "A_KEY", "lower_key", "other", "K" * 20):
                    self.assertNotIn(text, printed)
                self.assertEqual(list(directory.iterdir()), [])

    def test_no_line_break_but_lf_splits_a_value(self) -> None:
        self.assertEqual(parse_leak_violations(load_helper()), [])

    def test_a_refused_run_directory_is_never_touched(self) -> None:
        module = load_helper()
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            directory = module.create(0, 0)
            (directory / ".rendered").write_text(f"A_KEY={SENTINEL}\n")
            directory.chmod(0o755)
            code, printed = run_helper(module, "split", str(directory))
            self.assertEqual(code, 1)
            self.assertIn("expected 0700", printed)
            self.assertEqual([path.name for path in directory.iterdir()], [".rendered"])
        self.assertEqual(confinement_violations(load_helper()), [])

    def test_prune_removes_only_unlocked_run_directories(self) -> None:
        module = load_helper()
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            self.assertEqual(run_helper(module, "prune"), (0, "nothing to prune\n"))
            killed, _, _ = split_rendered(module, f"A_KEY={SENTINEL}\n")
            live, _, _ = split_rendered(module, f"A_KEY={SENTINEL}\n")
            other = module.PARENT / "keep"
            other.mkdir(mode=0o700)
            held = os.open(live, os.O_RDONLY | os.O_DIRECTORY)
            fcntl.flock(held, fcntl.LOCK_SH)
            try:
                pruned = run_helper(module, "prune")
            finally:
                os.close(held)
            self.assertEqual(pruned, (0, "spec secrets removed: 1\n"))
            self.assertEqual((killed.exists(), live.exists()), (False, True))
            self.assertTrue(other.exists())
            self.assertEqual(stat.S_IMODE(module.PARENT.lstat().st_mode), 0o700)
            self.assertEqual(
                run_helper(module, "prune")[1], "spec secrets removed: 1\n"
            )
            self.assertTrue(other.exists())

    def test_create_leaves_its_lock_to_a_child_for_the_hold_time(self) -> None:
        module = load_helper()
        module.POLL_SECONDS = 0.05
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            self.assertEqual(run_helper(module, "create", "0", "0")[0], 2)
            code, printed = run_helper(module, "create", "1", "0")
            directory = Path(printed.strip())
            self.assertEqual((code, directory.parent), (0, module.PARENT))
            watch = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                self.assertFalse(lockable(watch))
                self.assertEqual(run_helper(module, "prune"), (0, "nothing to prune\n"))
                self.assertTrue(wait_for(lambda: lockable(watch), 10))
            finally:
                os.close(watch)
            self.assertEqual(
                run_helper(module, "prune")[1], "spec secrets removed: 1\n"
            )

    def test_the_child_removes_the_directory_once_its_owner_is_gone(self) -> None:
        self.assertEqual(owner_violations(load_helper()), [])
        module = load_helper()
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            gone = subprocess.Popen([sys.executable, "-c", "pass"])
            gone.wait()
            code, printed = run_helper(module, "create", "0", str(gone.pid))
            self.assertEqual(code, 1)
            self.assertIn(f"owner pid {gone.pid} is not running", printed)

    def test_a_foreign_parent_or_location_is_never_touched(self) -> None:
        module = load_helper()
        with tempfile.TemporaryDirectory() as tmp:
            planted = Path(tmp) / "planted"
            planted.mkdir()
            planted.chmod(0o755)
            (planted / "run.keep").mkdir(mode=0o700)
            target = Path(tmp) / "target"
            target.mkdir(mode=0o700)
            (target / "run.keep").mkdir(mode=0o700)
            link = Path(tmp) / "link"
            link.symlink_to(target)
            for parent in (planted, link):
                with self.subTest(parent=parent.name):
                    module.PARENT = parent
                    code, printed = run_helper(module, "prune")
                    self.assertEqual(code, 0)
                    self.assertIn("prune skipped", printed)
                    code, printed = run_helper(module, "create", "1", "0")
                    self.assertEqual(code, 1)
                    self.assertIn(f"{parent}", printed)
                    self.assertIn(f"rm -rf -- {parent} so the next run", printed)
            module.PARENT = Path(tmp) / "spec-secrets"
            self.assertEqual(run_helper(module, "prune", str(target))[0], 2)
            (target / ".rendered").write_text(f"A_KEY={SENTINEL}\n")
            code, printed = run_helper(module, "split", str(target))
            self.assertEqual(code, 1)
            self.assertIn("not a run directory", printed)
            self.assertEqual(
                sorted(path.name for path in target.iterdir()),
                [".rendered", "run.keep"],
            )
            self.assertEqual([p.name for p in planted.iterdir()], ["run.keep"])


class TestSpecSecretsNegativeControls(unittest.TestCase):
    def test_a_mount_without_the_template_condition_is_caught(self) -> None:
        unconditional = run_argv().replace(f"{TEMPLATE_EXISTS} | bool", "true")
        self.assertNotEqual(unconditional, run_argv())
        self.assertNotEqual(mount_violations(unconditional), [])

    def test_a_volume_flag_that_creates_a_missing_source_is_caught(self) -> None:
        volume = run_argv().replace(
            "'--mount', 'type=bind,src=' ~ _playwright_spec_secrets_path ~ "
            "',dst=/run/spec-secrets,readonly'",
            "'-v', _playwright_spec_secrets_path ~ ':/run/spec-secrets:ro'",
        )
        self.assertNotEqual(volume, run_argv())
        self.assertNotEqual(mount_violations(volume), [])

    def test_a_dropped_mode_diff_guard_or_salt_is_caught(self) -> None:
        for mutation in ("mode", "diff", "salt", "runs", "ship", "baseline"):
            with self.subTest(mutation=mutation):
                tasks = copy.deepcopy(role_tasks(SECRETS_TASKS))
                render = tasks[6]
                args = render["ansible.builtin.copy"]
                if mutation == "mode":
                    args.pop("mode")
                elif mutation == "diff":
                    render.pop("diff")
                elif mutation == "runs":
                    tasks[5]["ansible.builtin.set_fact"][RUNS_FACT] = "{{ [] }}"
                elif mutation == "ship":
                    tasks[2]["ansible.builtin.copy"]["src"] = HELPER_CALL
                elif mutation == "baseline":
                    tasks[3]["ansible.builtin.command"]["argv"] = BASELINE[:3]
                else:
                    args["content"] = args["content"].split("\n", 1)[1]
                problems = layout_violations(tasks, env_task(), role_vars())
                self.assertNotEqual(problems, [])

    def test_a_missing_cleanup_is_caught(self) -> None:
        run_pass = copy.deepcopy(role_tasks("03_run_pass.yml"))
        next(t for t in run_pass if t["name"].startswith("🏃")).pop("always")
        parallel = copy.deepcopy(role_tasks("01_setup/parallel.yml"))
        staging = next(t for t in parallel if t["name"].startswith("📦"))
        staging["always"] = [
            task
            for task in staging["always"]
            if task.get("ansible.builtin.file") != SWEEP
        ]
        orchestrate = [
            task
            for task in role_tasks("01_setup/orchestrate.yml")
            if script_call(task) != PRUNE_CALL
        ]
        problems = cleanup_violations(run_pass, parallel, orchestrate)
        self.assertEqual(len(problems), 3)

    def test_a_prune_that_can_fail_a_plain_role_is_caught(self) -> None:
        orchestrate = copy.deepcopy(role_tasks("01_setup/orchestrate.yml"))
        next(t for t in orchestrate if script_call(t) == PRUNE_CALL).pop("failed_when")
        problems = cleanup_violations(
            role_tasks("03_run_pass.yml"),
            role_tasks("01_setup/parallel.yml"),
            orchestrate,
        )
        self.assertEqual(problems, ["the prune can fail a role without the template"])

    def test_capture_or_failure_context_left_on_is_caught(self) -> None:
        config = read_text(str(CONFIG))
        for broken in (
            config.replace('trace: "off"', 'trace: "retain-on-failure"'),
            config.replace("captureOff ? [] : ", ""),
            config.replace('process.env.PLAYWRIGHT_NO_COPY_PROMPT = "1";', ""),
            config.replace('captureOff ? "/tmp/test-results" : ', ""),
        ):
            with self.subTest(broken=len(broken)):
                self.assertNotEqual(broken, config)
                self.assertNotEqual(capture_violations(broken), [])

    def test_a_missing_or_late_masking_after_the_run_is_caught(self) -> None:
        orchestrate = role_tasks("01_setup/orchestrate.yml")
        run_pass = copy.deepcopy(role_tasks("03_run_pass.yml"))
        closing = next(t for t in run_pass if t["name"].startswith("🏃"))["always"]
        closing[0]["block"].reverse()
        self.assertEqual(
            cleanup_violations(
                run_pass, role_tasks("01_setup/parallel.yml"), orchestrate
            ),
            ["the serial run does not mask its files before the removal"],
        )
        for mutation, message in (
            ("drop", "the parallel run does not mask its files after its containers"),
            ("late", "the parallel run does not mask its files after its containers"),
            ("lenient", "a failed masking would not fail the parallel run"),
        ):
            with self.subTest(mutation=mutation):
                parallel = copy.deepcopy(role_tasks("01_setup/parallel.yml"))
                always = next(t for t in parallel if t["name"].startswith("📦"))[
                    "always"
                ]
                at = next(i for i, t in enumerate(always) if t["name"].startswith("🫥"))
                scrub = always.pop(at)
                if mutation == "late":
                    always.append(scrub)
                elif mutation == "lenient":
                    always.insert(at, {**scrub, "failed_when": False})
                problems = cleanup_violations(
                    role_tasks("03_run_pass.yml"), parallel, orchestrate
                )
                self.assertEqual(problems, [message])

    def test_a_job_that_puts_its_flags_into_the_masker_is_caught(self) -> None:
        content = role_task(QUEUE_TASKS, "📮")["ansible.builtin.copy"]["content"]
        broken = re.sub(
            r"_playwright_argv\[:\(.*?\) \+ 2\]", "_playwright_argv[:2]", content
        )
        self.assertNotEqual(broken, content)
        self.assertEqual(
            job_violations(broken), ["the job argv is wrong with template=True"]
        )

    def test_a_recording_variable_left_to_the_run_is_caught(self) -> None:
        config = read_text(str(CONFIG))
        for broken in (
            config.replace('"PW_TEST_REPORTER", ', ""),
            config.replace(', "DEBUG", "DEBUG_FILE"', ""),
            config.replace("delete process.env[name];", ""),
        ):
            with self.subTest(size=len(broken)):
                self.assertNotEqual(broken, config)
                self.assertNotEqual(recording_env_violations(broken), [])

    def test_a_serial_hold_for_the_whole_round_or_without_grace_is_caught(self) -> None:
        for bound, expected in (
            (
                (
                    "(TEST_E2E_PLAYWRIGHT_PARALLEL_BUDGET | int)"
                    " + (TEST_E2E_PLAYWRIGHT_MASK_GRACE_SECONDS | int)"
                ),
                ["a serial pass runs /role/files/spec_secrets.py create 10299 4242"],
            ),
            (
                (
                    "(TEST_E2E_PLAYWRIGHT_PARALLEL_BUDGET if (_playwright_dispatch | bool)"
                    " else lookup('timeout', TEST_E2E_PLAYWRIGHT_RUN_TIMEOUT_EFFECTIVE))"
                    " | int"
                ),
                [
                    "a serial pass runs /role/files/spec_secrets.py create 600 4242",
                    "a parallel pass runs /role/files/spec_secrets.py create 9999 4242",
                ],
            ),
        ):
            with self.subTest(bound=bound):
                create = copy.deepcopy(role_task(SECRETS_TASKS, "📁"))
                create["ansible.builtin.script"] = (
                    f"{HELPER_CALL} create {{{{ {bound} }}}}"
                    " {{ TEST_E2E_PLAYWRIGHT_PLAY_PID | int }}"
                )
                self.assertEqual(hold_violations(create), expected)

    def test_a_rerun_that_drifts_from_the_runner_is_caught(self) -> None:
        script = read_text(str(RERUN))
        makefile = read_text(str(MAKEFILE))
        unforwarded = makefile.replace(MAKE_FORWARD, RERUN_CALL)
        for broken, broken_make in (
            (script.replace(EXEC_WITHOUT_SECRETS, 'exec "${run[@]}"'), makefile),
            (script.replace(" -e INFINITO_PLAYWRIGHT_NO_CAPTURE=true", ""), makefile),
            (script.replace(INT_TRAP, ""), makefile),
            (script.replace(HUP_TRAP, ""), makefile),
            (
                script.replace(CREATE_LOCKED, CREATE_LOCKED.replace('"$$"', "0")),
                makefile,
            ),
            (script.replace(CAPTURE_GUARD, "true ||"), makefile),
            (script.replace(" -e NO_COLOR=1 -e FORCE_COLOR=0", ""), makefile),
            (
                script.replace(EXIT_SCRUB, "trap 'rm -rf -- \"$secrets_dir\"' EXIT"),
                makefile,
            ),
            (script.replace(EXIT_REMOVAL + "python3", "python3"), makefile),
            (script.replace(f"\t{PRE_SCRUB}\n", ""), makefile),
            (script, unforwarded),
        ):
            with self.subTest(size=len(broken) + len(broken_make)):
                self.assertNotEqual((broken, broken_make), (script, makefile))
                self.assertNotEqual(rerun_violations(broken, broken_make), [])

    def test_a_rerun_on_a_stale_config_is_caught(self) -> None:
        script = read_text(str(RERUN))
        for broken in (
            script.replace(RESTAGE + "\n", ""),
            script.replace(RESTAGE + "\n", "").replace(
                "secret_args=()\n", f"secret_args=()\nif true; then\n\t{RESTAGE}\nfi\n"
            ),
        ):
            with self.subTest(size=len(broken)):
                self.assertNotEqual(broken, script)
                self.assertNotEqual(restage_violations(broken), [])

    def test_the_old_line_split_is_caught_leaking_a_value(self) -> None:
        for replacements, leaks in (
            ((('text.split("\\n")', "text.splitlines()"),), len(BREAK_CHARS)),
            (
                (
                    ('dir_fd=run), "rb"', 'dir_fd=run), "r", encoding="utf-8"'),
                    ('text = handle.read().decode("utf-8")', "text = handle.read()"),
                ),
                1,
            ),
        ):
            with self.subTest(leaks=leaks):
                problems = parse_leak_violations(mutated_helper(*replacements))
                self.assertEqual(len(problems), leaks)

    def test_a_split_that_follows_a_link_out_of_the_parent_is_caught(self) -> None:
        module = mutated_helper(
            (
                "OPEN_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW",
                "OPEN_DIR = os.O_RDONLY | os.O_DIRECTORY",
            )
        )
        self.assertNotEqual(confinement_violations(module), [])

    def test_a_child_that_ignores_its_owner_is_caught(self) -> None:
        module = mutated_helper(
            ("watched = [] if owner is None else [owner]", "watched = []")
        )
        self.assertEqual(
            owner_violations(module),
            ["the directory outlives its owner", "the child outlives its owner"],
        )

    def test_a_flag_guard_that_lets_a_bypass_through_is_caught(self) -> None:
        script = read_text(str(RERUN))
        for old, new in (("|config|", "|"), ("[cu])'", "[c])'"), ("ui|ui-host|", "")):
            with self.subTest(old=old):
                self.assertEqual(script.count(old), 1)
                self.assertNotEqual(flag_violations(script.replace(old, new)), [])

    def test_a_prune_that_ignores_a_held_lock_is_caught(self) -> None:
        module = mutated_helper(
            (
                "fcntl.flock(child, fcntl.LOCK_EX | fcntl.LOCK_NB)",
                "fcntl.flock(child, fcntl.LOCK_SH | fcntl.LOCK_NB)",
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            live = module.create(0, 0)
            held = os.open(live, os.O_RDONLY | os.O_DIRECTORY)
            fcntl.flock(held, fcntl.LOCK_SH)
            try:
                run_helper(module, "prune")
            finally:
                os.close(held)
            self.assertFalse(live.exists())

    def test_a_readable_file_mode_is_caught(self) -> None:
        module = load_helper()
        module.FILE_MODE = 0o644
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            directory, code, _ = split_rendered(module, f"A_KEY={SENTINEL}\n")
            self.assertEqual(code, 0)
            self.assertEqual(
                file_violations(directory, {"A_KEY": SENTINEL}),
                ["A_KEY has mode 0644"],
            )


if __name__ == "__main__":
    unittest.main()
