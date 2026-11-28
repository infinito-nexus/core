from __future__ import annotations

import ast
import os
import re
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN
from utils.software import SOFTWARE_VARS

from . import PROJECT_ROOT
from .test_policies import (
    ROLE_DIR,
    effective,
    literal_vars,
    parse,
    planted,
    render,
    template_source,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

TOKEN_LOOKUP_GRANTS = {
    "auth/token/accessors": {"list", "sudo"},
    "auth/token/lookup-accessor": {"update"},
    "sys/capabilities-accessor": {"update"},
}
PLAYWRIGHT_GRANTS = {
    "tenant/data/+/proxmox": {"read"},
    "tenant/data/+/incus": {"read"},
    "tenant/data/+/s3": {"read"},
    "tenant/data/+/dns": {"read"},
    "platform/data/provision/proxmox-*": {"read"},
    "platform/data/provision/incus-*": {"read"},
    "platform/data/provision/transit/ws-*": {"read"},
    "transit/keys/ws-*": {"read"},
    "platform/data/fixture/+/workspace-ssh": {"read"},
    "platform/data/playwright/semaphore": {"read"},
    "platform/data/playwright/store": {"read"},
    "auth/token/revoke-self": {"update"},
    **TOKEN_LOOKUP_GRANTS,
}
PLAYWRIGHT_PROBES = {
    "tenant/data/ws-0a-provision/proxmox": {"read"},
    "tenant/data/ws-0a-provision/incus": {"read"},
    "tenant/data/ws-0a-provision/s3": {"read"},
    "tenant/data/ws-0a-provision/dns": {"read"},
    "platform/data/provision/proxmox-echoserver": {"read"},
    "platform/data/provision/incus-echoserver": {"read"},
    "platform/data/provision/transit/ws-0a": {"read"},
    "transit/keys/ws-0a-provision": {"read"},
    "transit/datakey/plaintext/ws-0a-provision": set(),
    "transit/decrypt/ws-0a-provision": set(),
    "transit/export/encryption-key/ws-0a-provision": set(),
    "transit/backup/ws-0a-provision": set(),
    "platform/metadata/provision/transit/ws-0a": set(),
    "platform/data/fixture/platform/workspace-ssh": {"read"},
    "platform/data/fixture/platform/apps/web-app-semaphore": set(),
    "platform/data/fixture/platform/users/platform_administrator": set(),
    "platform/data/fixture/platform/workspace-ssh/extra": set(),
    "platform/metadata/fixture/platform/workspace-ssh": set(),
    "platform/data/playwright/semaphore": {"read"},
    "platform/data/playwright/store": {"read"},
    "tenant/data/ws-0a/probe/alpha": set(),
    "tenant/data/ws-0a-provision/proxmox/extra": set(),
    "tenant/metadata/ws-0a-provision/proxmox": set(),
    "platform/data/store/gitea": set(),
    "platform/data/store/semaphore": set(),
    "platform/data/provision/hetzner": set(),
    "platform/data/provision/cloudflare/example.org": set(),
    "platform/data/provision/cloudflare-zones": set(),
    "platform/data/workspaces/route53": set(),
    "platform/data/playwright/other": set(),
    "platform/metadata/playwright/store": set(),
    "auth/approle/role/store/secret-id": set(),
    "auth/approle/role/playwright/secret-id": set(),
    "sys/policies/acl/playwright": set(),
    "auth/token/accessors": {"list", "sudo"},
    "auth/token/accessors/x": set(),
    "auth/token/lookup-accessor": {"update"},
    "sys/capabilities-accessor": {"update"},
    "auth/token/revoke-accessor": set(),
    "auth/token/lookup": set(),
    "auth/token/lookup-self": set(),
    "auth/token/create": set(),
    "auth/token/create/ws-0a-transit-child": set(),
    "sys/capabilities": set(),
}
RUNTIME_GATE = re.compile(r"RUNTIME in \[[^\]]*\]")
TASKS_DIR = ROLE_DIR / "tasks"
STAGE_FILE = "08_playwright.yml"
STAGE_INCLUDER = "01_init.yml"
WRITER = "utils/playwright.yml"
TASK_INCLUDES = (
    "ansible.builtin.include_tasks",
    "include_tasks",
    "ansible.builtin.import_tasks",
    "import_tasks",
)
ROLE_INCLUDES = (
    "ansible.builtin.include_role",
    "include_role",
    "ansible.builtin.import_role",
    "import_role",
)
LOOPS = ("loop", "with_items")
BLOCKS = ("block", "rescue", "always")
PLAYWRIGHT_VAR = "OPENBAO_PLAYWRIGHT_APPROLE"
WRITE_GATE = "OPENBAO_PLAYWRIGHT_ENABLED | bool"
WITHDRAW_GATE = "not (OPENBAO_PLAYWRIGHT_ENABLED | bool)"
POLICY_REFERENCE = re.compile(
    rf"playwright\.hcl\.j2|{PLAYWRIGHT_VAR}\s*~\s*['\"]\.hcl\.j2['\"]"
)
POLICY_DELETE = "bao policy delete"
PLANTED_GATE = "OPENBAO_WORKSPACES_ENABLED | bool"
PLANTED_POLICY = f"{{{{ {PLAYWRIGHT_VAR} }}}}"
PATH_ABSOLUTE_WRITER = (
    "{{ lookup('path_absolute', 'roles/web-app-openbao/tasks/utils/playwright.yml') }}"
)


def playwright_findings(grants: dict[str, set[str]]) -> list[str]:
    findings = [] if grants == PLAYWRIGHT_GRANTS else [f"grants {grants}"]
    findings.extend(
        f"{path}: {sorted(effective(grants, path))} != {sorted(expected)}"
        for path, expected in PLAYWRIGHT_PROBES.items()
        if effective(grants, path) != expected
    )
    return findings


def playwright_config() -> dict:
    services = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SERVICES))
    return services["openbao"]["workspaces"]["playwright"]


def role_vars() -> dict[str, Any]:
    return load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))


def playwright_gate() -> str:
    return role_vars()["OPENBAO_PLAYWRIGHT_ENABLED"]


def runner_runtimes() -> list[str]:
    """
    Returns:
        The runtimes ``OPENBAO_PLAYWRIGHT_ENABLED`` names, those of the test
        runner.
    """
    gate = RUNTIME_GATE.search(playwright_gate())
    if gate is None:
        raise AssertionError("OPENBAO_PLAYWRIGHT_ENABLED names no runtime")
    return ast.literal_eval(gate[0].removeprefix("RUNTIME in "))


def playwright_enabled(runtime: str) -> bool:
    """
    Args:
        runtime: the ``RUNTIME`` of a deploy with workspaces.

    Returns:
        ``OPENBAO_PLAYWRIGHT_ENABLED`` of that deploy, evaluated from the role
        vars.
    """
    expression = playwright_gate().strip().removeprefix("{{").removesuffix("}}")
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = bool
    return env.compile_expression(expression)(
        RUNTIME=runtime, OPENBAO_WORKSPACES_ENABLED=True
    )


def deployed_grants(runtime: str) -> dict[str, set[str]]:
    """
    Args:
        runtime: see ``playwright_enabled``.

    Returns:
        The grants of the policy ``playwright`` OpenBao holds after a deploy in
        that runtime: the rendered template while ``08_playwright.yml``
        includes its writer, none once it withdraws the policy.
    """
    return parse(render("playwright")) if playwright_enabled(runtime) else {}


def _listed(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def include_key(task: dict) -> str | None:
    """
    Args:
        task: one task.

    Returns:
        The include or import module the task calls, None for any other task.
    """
    return next((key for key in (*TASK_INCLUDES, *ROLE_INCLUDES) if key in task), None)


def included_file(task: dict) -> str | None:
    """
    Args:
        task: one task.

    Returns:
        The task file it includes or imports as the task writes it, for a
        role include its ``tasks_from`` with ``.yml``; None for any other
        task and for a role include without ``tasks_from``.
    """
    key = include_key(task)
    if key is None:
        return None
    target = task[key]
    if key in ROLE_INCLUDES:
        if "tasks_from" not in target:
            return None
        name = target["tasks_from"]
        return name if name.endswith(".yml") else f"{name}.yml"
    return target["file"] if isinstance(target, dict) else target


def names_target(written: str, target: str) -> bool:
    """
    Args:
        written: an include target as a task writes it.
        target: a task file relative to the role's tasks directory.

    Returns:
        Whether ``written`` is ``target`` or a path ending in ``/<target>``,
        also inside a Jinja expression.
    """
    pattern = rf"(?:^|[/'\"\s]){re.escape(target)}(?=$|['\"\s])"
    return re.search(pattern, written) is not None


def _conditions(task: dict) -> list[str]:
    found = _listed(task["when"]) if "when" in task else []
    key = include_key(task)
    if key is not None and isinstance(task[key], dict):
        applied = task[key]
        if "apply" in applied and "when" in applied["apply"]:
            found = [*found, *_listed(applied["apply"]["when"])]
    return found


def _tasks(
    node: Any, inherited: tuple[str, ...]
) -> Iterator[tuple[dict, tuple[str, ...]]]:
    """
    Args:
        node: a parsed task file, task list or task.
        inherited: the conditions of the blocks around ``node``.

    Yields:
        ``(task, conditions)`` of every task, its conditions being its own
        ``when``, the ``when`` of an include's ``apply`` and those of the
        blocks around it.
    """
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item, inherited)
    elif isinstance(node, dict):
        conditions = (*inherited, *_conditions(node))
        yield node, conditions
        for key in BLOCKS:
            if key in node:
                yield from _tasks(node[key], conditions)


def role_task_files() -> dict[str, str]:
    """
    Returns:
        ``{path relative to the role's tasks directory: text}`` of every task
        file of the role.
    """
    return {
        str(Path(path).relative_to(TASKS_DIR)): read_text(path)
        for path in iter_project_files(extensions=(".yml",))
        if path.startswith(f"{TASKS_DIR}{os.sep}")
    }


def role_stages() -> dict[str, Any]:
    """
    Returns:
        ``{path relative to the role's tasks directory: parsed tasks}`` of
        every task file of the role.
    """
    return {path: load_yaml_any(str(TASKS_DIR / path)) for path in role_task_files()}


def gate_findings(stage: list[dict]) -> list[str]:
    """
    Args:
        stage: the parsed ``tasks/08_playwright.yml``.

    Returns:
        One message when the writer of the policy is included without the
        test-runtime gate, and one when no task outside that gate deletes the
        policy.
    """
    includes = [
        task
        for task in stage
        if (written := included_file(task)) is not None
        and names_target(written, WRITER)
    ]
    findings = (
        []
        if includes and all(task.get("when") == WRITE_GATE for task in includes)
        else [f"{WRITER} is included without {WRITE_GATE}"]
    )
    if not any(
        task.get("when") == WITHDRAW_GATE
        and any(POLICY_DELETE in str(step) for step in task["block"])
        for task in stage
        if "block" in task
    ):
        findings.append(
            "no task deletes the playwright policy outside the test runtimes"
        )
    return findings


def includers(stages: dict[str, Any], target: str) -> dict[str, list[tuple[str, ...]]]:
    """
    Args:
        stages: see ``role_stages``.
        target: a task file relative to the role's tasks directory.

    Returns:
        ``{path: [conditions of each include]}`` of every task file that
        includes ``target``.
    """
    found: dict[str, list[tuple[str, ...]]] = {}
    for path, tasks in stages.items():
        for task, conditions in _tasks(tasks, ()):
            written = included_file(task)
            if written is not None and names_target(written, target):
                found.setdefault(path, []).append(conditions)
    return found


def wiring_findings(stages: dict[str, Any]) -> list[str]:
    """
    Args:
        stages: see ``role_stages``.

    Returns:
        One message per task file beside ``08_playwright.yml`` that includes
        the writer, one when ``08_playwright.yml`` has another includer than
        ``01_init.yml``, and one per include of it that carries a condition.
    """
    findings = [
        f"{path} includes {WRITER}"
        for path in includers(stages, WRITER)
        if path != STAGE_FILE
    ]
    stage = includers(stages, STAGE_FILE)
    if sorted(stage) != [STAGE_INCLUDER]:
        findings.append(f"{STAGE_FILE} is included by {sorted(stage)}")
    findings.extend(
        f"{path} includes {STAGE_FILE} under {' and '.join(conditions)}"
        for path, includes in stage.items()
        for conditions in includes
        if conditions
    )
    return findings


def policy_writers(files: dict[str, str]) -> set[str]:
    """
    Args:
        files: see ``role_task_files``.

    Returns:
        Every task file that names the playwright policy template, by its
        basename or as ``'policies/' ~ OPENBAO_PLAYWRIGHT_APPROLE ~ '.hcl.j2'``.
    """
    return {path for path, text in files.items() if POLICY_REFERENCE.search(text)}


def policy_lists(values: dict[str, Any], stages: dict[str, Any]) -> list[str]:
    """
    Args:
        values: the role vars.
        stages: see ``role_stages``.

    Returns:
        Every list var with an item that names the playwright policy, by its
        value or through ``OPENBAO_PLAYWRIGHT_APPROLE``, and one entry per task
        whose ``loop`` or ``with_items`` names it.
    """
    name = values[PLAYWRIGHT_VAR]
    found = [
        key
        for key, value in values.items()
        if isinstance(value, list)
        and any(item == name or PLAYWRIGHT_VAR in str(item) for item in value)
    ]
    found.extend(
        f"{path} loops over {PLAYWRIGHT_VAR}"
        for path, tasks in stages.items()
        for task, _ in _tasks(tasks, ())
        for key in LOOPS
        if key in task
        and (PLAYWRIGHT_VAR in str(task[key]) or name in _listed(task[key]))
    )
    return sorted(found)


def stage_include_changed(change: Callable[[dict], dict]) -> dict[str, Any]:
    """
    Args:
        change: turns the include of ``08_playwright.yml`` into a planted one.

    Returns:
        The role stages with that include of ``01_init.yml`` replaced.
    """
    stages = role_stages()
    stages[STAGE_INCLUDER] = [
        change(task) if included_file(task) == STAGE_FILE else task
        for task in stages[STAGE_INCLUDER]
    ]
    return stages


def gated_apply(task: dict) -> dict:
    key = include_key(task)
    target = task[key]
    return {**task, key: {**target, "apply": {**target["apply"], "when": PLANTED_GATE}}}


class TestThePlaywrightPolicy(unittest.TestCase):
    def test_the_policy_reads_exactly_the_paths_the_specs_read(self) -> None:
        self.assertEqual(playwright_findings(parse(render("playwright"))), [])

    def test_control_a_widened_tenant_path_fails(self) -> None:
        grants = planted(
            "playwright",
            'path "tenant/data/*" {\n  capabilities = ["read"]\n}',
        )
        self.assertNotEqual(playwright_findings(grants), [])

    def test_control_a_widened_fixture_read_fails(self) -> None:
        grants = planted(
            "playwright",
            'path "platform/data/fixture/*" {\n  capabilities = ["read"]\n}',
        )
        self.assertNotEqual(playwright_findings(grants), [])

    def test_control_an_added_write_capability_fails(self) -> None:
        source = template_source("playwright").replace(
            '["read"]', '["create", "read"]', 1
        )
        self.assertNotEqual(source, template_source("playwright"))
        self.assertNotEqual(
            playwright_findings(parse(render("playwright", source))), []
        )

    def test_control_a_transit_data_key_grant_fails(self) -> None:
        grants = planted(
            "playwright",
            'path "transit/datakey/plaintext/ws-*" {\n  capabilities = ["update"]\n}',
        )
        self.assertNotEqual(playwright_findings(grants), [])

    def test_control_a_widened_transit_key_read_fails(self) -> None:
        grants = planted(
            "playwright",
            'path "transit/*" {\n  capabilities = ["read"]\n}',
        )
        self.assertNotEqual(playwright_findings(grants), [])

    def test_control_a_store_secret_id_grant_fails(self) -> None:
        grants = planted(
            "playwright",
            'path "auth/approle/role/store/secret-id" {\n  capabilities = ["update"]\n}',
        )
        self.assertNotEqual(playwright_findings(grants), [])

    def test_control_a_revoke_by_accessor_fails(self) -> None:
        grants = planted(
            "playwright",
            'path "auth/token/revoke-accessor" {\n  capabilities = ["update"]\n}',
        )
        self.assertNotEqual(playwright_findings(grants), [])

    def test_control_a_token_create_fails(self) -> None:
        grants = planted(
            "playwright",
            'path "auth/token/create" {\n  capabilities = ["update"]\n}',
        )
        self.assertNotEqual(playwright_findings(grants), [])


class TestTheTokenLookupGrant(unittest.TestCase):
    def test_a_test_runtime_deploy_grants_the_token_lookup(self) -> None:
        for runtime in runner_runtimes():
            grants = deployed_grants(runtime)
            for path, capabilities in TOKEN_LOOKUP_GRANTS.items():
                with self.subTest(runtime=runtime, path=path):
                    self.assertEqual(effective(grants, path), capabilities)

    def test_negative_control_a_production_deploy_grants_no_token_lookup(
        self,
    ) -> None:
        runtime = load_yaml_any(str(SOFTWARE_VARS))["RUNTIME"]
        self.assertNotIn(runtime, runner_runtimes())
        grants = deployed_grants(runtime)
        for path in TOKEN_LOOKUP_GRANTS:
            with self.subTest(path=path):
                self.assertEqual(effective(grants, path), set())

    def test_only_the_gated_writer_renders_the_policy(self) -> None:
        self.assertEqual(policy_writers(role_task_files()), {WRITER})
        self.assertEqual(policy_lists(role_vars(), role_stages()), [])
        self.assertEqual(gate_findings(load_yaml_any(str(TASKS_DIR / STAGE_FILE))), [])

    def test_every_deploy_reaches_the_gated_writer_or_the_withdrawal(self) -> None:
        self.assertEqual(wiring_findings(role_stages()), [])

    def test_negative_control_an_ungated_writer_is_caught(self) -> None:
        stage = [
            {key: value for key, value in task.items() if key != "when"}
            if included_file(task) is not None
            else task
            for task in load_yaml_any(str(TASKS_DIR / STAGE_FILE))
        ]
        self.assertEqual(
            gate_findings(stage), [f"{WRITER} is included without {WRITE_GATE}"]
        )

    def test_negative_control_a_stage_that_keeps_the_policy_is_caught(
        self,
    ) -> None:
        stage = [
            task
            for task in load_yaml_any(str(TASKS_DIR / STAGE_FILE))
            if task.get("when") != WITHDRAW_GATE
        ]
        self.assertEqual(
            gate_findings(stage),
            ["no task deletes the playwright policy outside the test runtimes"],
        )

    def test_negative_control_a_second_includer_of_the_writer_is_caught(
        self,
    ) -> None:
        stages = {
            **role_stages(),
            "planted.yml": [{"ansible.builtin.include_tasks": {"file": WRITER}}],
        }
        self.assertEqual(wiring_findings(stages), [f"planted.yml includes {WRITER}"])

    def test_negative_control_a_path_absolute_include_of_the_writer_is_caught(
        self,
    ) -> None:
        stages = {
            **role_stages(),
            "planted.yml": [
                {"ansible.builtin.include_tasks": {"file": PATH_ABSOLUTE_WRITER}}
            ],
        }
        self.assertEqual(wiring_findings(stages), [f"planted.yml includes {WRITER}"])

    def test_negative_control_a_role_include_of_the_writer_is_caught(self) -> None:
        stages = {
            **role_stages(),
            "planted.yml": [
                {
                    "ansible.builtin.include_role": {
                        "name": "web-app-openbao",
                        "tasks_from": WRITER.removesuffix(".yml"),
                    }
                }
            ],
        }
        self.assertEqual(wiring_findings(stages), [f"planted.yml includes {WRITER}"])

    def test_negative_control_a_gated_stage_include_is_caught(self) -> None:
        expected = [f"{STAGE_INCLUDER} includes {STAGE_FILE} under {PLANTED_GATE}"]
        for kind, change in (
            ("when", lambda task: {**task, "when": PLANTED_GATE}),
            ("block", lambda task: {"block": [task], "when": PLANTED_GATE}),
            ("apply", gated_apply),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(
                    wiring_findings(stage_include_changed(change)), expected
                )

    def test_negative_control_a_basename_reference_is_caught(self) -> None:
        files = {
            **role_task_files(),
            "planted.yml": '- ansible.builtin.template:\n    src: "playwright.hcl.j2"\n',
        }
        self.assertEqual(policy_writers(files), {WRITER, "planted.yml"})

    def test_negative_control_a_dynamic_reference_is_caught(self) -> None:
        files = {
            **role_task_files(),
            "planted.yml": (
                "- ansible.builtin.shell: bao policy write - \n"
                "  args:\n"
                "    stdin: \"{{ lookup('template', 'policies/' ~ "
                f"{PLAYWRIGHT_VAR} ~ '.hcl.j2') }}}}\"\n"
            ),
        }
        self.assertEqual(policy_writers(files), {WRITER, "planted.yml"})

    def test_negative_control_a_policy_list_that_names_playwright_is_caught(
        self,
    ) -> None:
        values = role_vars()
        for item in (values[PLAYWRIGHT_VAR], PLANTED_POLICY):
            with self.subTest(item=item):
                planted_values = {
                    **values,
                    "OPENBAO_TENANCY_POLICIES": [
                        *values["OPENBAO_TENANCY_POLICIES"],
                        item,
                    ],
                }
                self.assertEqual(
                    policy_lists(planted_values, role_stages()),
                    ["OPENBAO_TENANCY_POLICIES"],
                )

    def test_negative_control_a_loop_that_names_playwright_is_caught(self) -> None:
        stages = {
            **role_stages(),
            "planted.yml": [{"name": "planted", "loop": ["tenant", PLANTED_POLICY]}],
        }
        self.assertEqual(
            policy_lists(role_vars(), stages),
            [f"planted.yml loops over {PLAYWRIGHT_VAR}"],
        )


class TestThePlaywrightLogins(unittest.TestCase):
    def test_the_logins_live_on_the_platform_mount(self) -> None:
        self.assertEqual(
            playwright_config()["mount"], literal_vars()["OPENBAO_PLATFORM_MOUNT"]
        )

    def test_the_policy_reads_exactly_the_configured_logins(self) -> None:
        config = playwright_config()
        prefix = f"{config['mount']}/data/playwright/"
        self.assertEqual(
            {
                pattern
                for pattern in parse(render("playwright"))
                if pattern.startswith(prefix)
            },
            {f"{config['mount']}/data/{path}" for path in config["logins"].values()},
        )

    def test_the_deploy_seeds_every_configured_login(self) -> None:
        self.assertEqual(
            set(role_vars()["OPENBAO_PLAYWRIGHT_LOGINS"]),
            set(playwright_config()["logins"]),
        )

    def test_the_deploy_writes_and_withdraws_every_login(self) -> None:
        config = playwright_config()
        grants = parse(render("ansible-admin"))
        for path in config["logins"].values():
            with self.subTest(path=path):
                self.assertLessEqual(
                    {"create", "update"},
                    effective(grants, f"{config['mount']}/data/{path}"),
                )
                self.assertLessEqual(
                    {"delete"}, effective(grants, f"{config['mount']}/metadata/{path}")
                )

    def test_the_approle_follows_the_runtimes_of_the_test_runner(self) -> None:
        stage = read_text(str(PROJECT_ROOT / "tasks/stages/02_server.yml"))
        self.assertEqual(
            set(RUNTIME_GATE.findall(playwright_gate())),
            set(RUNTIME_GATE.findall(stage)),
        )


if __name__ == "__main__":
    unittest.main()
