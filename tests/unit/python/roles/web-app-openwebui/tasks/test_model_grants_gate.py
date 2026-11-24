from __future__ import annotations

import shlex
import unittest

from jinja2 import Environment, StrictUndefined

from tests.utils.ansible_assert import assert_task, evaluate, holds, message
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles/web-app-openwebui"
CORE_TASKS = ROLE / "tasks/00_core.yml"
GRANT_TASKS = ROLE / "tasks/utils/agent_models.yml"
ADMIN_TASKS = ROLE / "tasks/utils/admin.yml"
REGISTRY_PASSWORD = "registry-password-sentinel"
OLD_ADMIN_STDIN = (
    "{{ OPENWEBUI_ADMIN_USER.password }}\n{{ lookup('file', 'python/administrator.py') }}"
)
REFRESH_TASKS = ROLE / "tasks/utils/refresh_model_grants.yml"
LITELLM_TASKS = PROJECT_ROOT / "roles/svc-ai-litellm/tasks/00_core.yml"
GRANT_FILE = "agent_models.yml"
ADMIN_FILE = "utils/admin.yml"
MCP_FILE = "utils/mcp.yml"
API_KEY_ASSERT = "🛑 Refuse the grant steps while Open WebUI refuses API keys"
API_KEY_SETTING = "applications.web-app-openwebui.services.openwebui.enable_api_keys"
AGENT_GROUPS = {"hermes": "/roles/web-app-hermes/agent-user"}
MCP_SERVER = {"id": "web-app-nextcloud"}
BROKER_GATE = "OPENWEBUI_AGENT_BROKER_ENABLED | bool"
CONFIG_BROKER_GATE = (
    "lookup('config', 'web-app-openwebui', 'services.agent-broker.enabled') | bool"
)
OLD_ADMIN_GATE = [
    "not (OPENWEBUI_OIDC_ENABLED | bool)",
    "not (OPENWEBUI_LDAP_ENABLED | bool)",
]
DERIVED = (
    "OPENWEBUI_AGENT_MODELS",
    "OPENWEBUI_MODEL_GRANTS_ENABLED",
    "OPENWEBUI_API_KEY_NEEDED",
)


def role_vars():
    return load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))


def task_including(path, matches):
    """
    Args:
        path: the Ansible task file.
        matches: predicate over one task.

    Returns:
        The only task of ``path`` that ``matches`` accepts.
    """
    found = [task for task in load_yaml_any(str(path)) or [] if matches(task)]
    if len(found) != 1:
        raise AssertionError(f"{path}: {len(found)} matching tasks, expected 1")
    return found[0]


def includes(name):
    return lambda task: name in str(task.get("ansible.builtin.include_tasks", ""))


def includes_refresh(task):
    included = task.get("ansible.builtin.include_role") or {}
    return included.get("tasks_from") == "utils/refresh_model_grants.yml"


def runs(task, variables):
    """
    Args:
        task: one Ansible task.
        variables: the variables its ``when`` reads.

    Returns:
        Whether every ``when`` condition of ``task`` holds.
    """
    conditions = task.get("when") or []
    if isinstance(conditions, str):
        conditions = [conditions]
    return all(bool(evaluate(str(condition), variables)) for condition in conditions)


def role_variables(broker, litellm, mcp_servers):
    """
    Args:
        broker: whether ``services.agent-broker`` is on.
        litellm: whether ``services.litellm`` is on.
        mcp_servers: the MCP tool servers Open WebUI serves.

    Returns:
        The grant gate variables of vars/main.yml, evaluated for that input.
    """
    variables = role_vars()
    scope = {
        "OPENWEBUI_AGENT_BROKER_ENABLED": broker,
        "OPENWEBUI_LITELLM_ENABLED": litellm,
        "OPENWEBUI_AGENT_GROUPS": AGENT_GROUPS,
        "OPENWEBUI_MCP_SERVERS": mcp_servers,
    }
    for name in DERIVED:
        template = variables[name].strip().removeprefix("{{").removesuffix("}}")
        scope[name] = evaluate(template, scope)
    return scope


def running(variables):
    return {**variables, "openwebui_running": {"stdout": "cid\n"}}


def litellm_scope(broker):
    return {"group_names": ["web-app-openwebui"], "lookup": lambda *_rest: broker}


def rendered_admin_step(task, ldap):
    """
    Args:
        task: the shell task of tasks/utils/admin.yml.
        ldap: whether LDAP signs the administrator in.

    Returns:
        The task's command, stdin and environment as Ansible renders them.
    """
    environment = Environment(undefined=StrictUndefined, trim_blocks=True)
    environment.filters["bool"] = lambda value: str(value).lower() == "true"
    environment.filters["quote"] = shlex.quote
    scope = {
        "OPENWEBUI_LDAP_ENABLED": ldap,
        "OPENWEBUI_ADMIN_USER": {
            "email": "administrator@example.org",
            "username": "administrator",
            "password": REGISTRY_PASSWORD,
        },
        "OPENWEBUI_LOCAL_CID": "cid",
        "lookup": lambda *_rest: "SCRIPT",
    }
    shell = task["ansible.builtin.shell"]
    return (
        environment.from_string(shell["cmd"]).render(scope),
        environment.from_string(shell["stdin"]).render(scope),
        {
            key: environment.from_string(value).render(scope)
            for key, value in task["environment"].items()
        },
    )


def grant_result(rc):
    return {
        "OPENWEBUI_GATEWAY_FAILED_RC": role_vars()["OPENWEBUI_GATEWAY_FAILED_RC"],
        "openwebui_model_grants": {"rc": rc},
    }


class TestGrantTaskGate(unittest.TestCase):
    def test_the_grant_task_runs_without_the_broker(self):
        task = task_including(CORE_TASKS, includes(GRANT_FILE))
        variables = role_variables(broker=False, litellm=True, mcp_servers=[])
        self.assertEqual(variables["OPENWEBUI_AGENT_MODELS"], {})
        self.assertTrue(runs(task, variables))

    def test_the_grant_task_runs_for_the_broker_alone(self):
        task = task_including(CORE_TASKS, includes(GRANT_FILE))
        variables = role_variables(broker=True, litellm=False, mcp_servers=[])
        self.assertEqual(variables["OPENWEBUI_AGENT_MODELS"], AGENT_GROUPS)
        self.assertTrue(runs(task, variables))

    def test_without_gateway_and_broker_the_grant_task_is_skipped(self):
        task = task_including(CORE_TASKS, includes(GRANT_FILE))
        variables = role_variables(broker=False, litellm=False, mcp_servers=[])
        self.assertFalse(runs(task, variables))

    def test_negative_control_the_broker_gate_skips_the_grant_task(self):
        task = dict(task_including(CORE_TASKS, includes(GRANT_FILE)), when=BROKER_GATE)
        variables = role_variables(broker=False, litellm=True, mcp_servers=[])
        self.assertFalse(runs(task, variables))


class TestRefreshGate(unittest.TestCase):
    def test_a_running_open_webui_is_regranted_without_the_broker(self):
        task = task_including(REFRESH_TASKS, includes(GRANT_FILE))
        variables = role_variables(broker=False, litellm=True, mcp_servers=[])
        self.assertTrue(runs(task, running(variables)))

    def test_without_gateway_and_broker_the_refresh_is_skipped(self):
        task = task_including(REFRESH_TASKS, includes(GRANT_FILE))
        variables = role_variables(broker=False, litellm=False, mcp_servers=[])
        self.assertFalse(runs(task, running(variables)))

    def test_a_litellm_deploy_refreshes_open_webui_without_the_broker(self):
        task = task_including(LITELLM_TASKS, includes_refresh)
        self.assertTrue(runs(task, litellm_scope(broker=False)))

    def test_negative_control_the_broker_gate_skips_the_refresh(self):
        task = task_including(LITELLM_TASKS, includes_refresh)
        gated = dict(task, when=[task["when"], CONFIG_BROKER_GATE])
        self.assertFalse(runs(gated, litellm_scope(broker=False)))


class TestApiKeyGate(unittest.TestCase):
    def refused(self, task, broker, litellm, mcp_servers):
        variables = role_variables(broker, litellm, mcp_servers)
        variables["OPENWEBUI_ENABLE_API_KEYS"] = False
        return not holds(task, variables)

    def test_api_keys_off_with_a_gateway_are_refused_by_name(self):
        task = assert_task(CORE_TASKS, API_KEY_ASSERT)
        self.assertTrue(self.refused(task, False, True, []))
        self.assertIn(API_KEY_SETTING, message(task, {}))

    def test_api_keys_off_with_mcp_servers_are_refused(self):
        task = assert_task(CORE_TASKS, API_KEY_ASSERT)
        self.assertTrue(self.refused(task, False, False, [MCP_SERVER]))

    def test_api_keys_off_without_any_grant_step_pass(self):
        task = assert_task(CORE_TASKS, API_KEY_ASSERT)
        self.assertFalse(self.refused(task, False, False, []))

    def test_the_refusal_comes_before_any_grant_step(self):
        names = [task.get("name", "") for task in load_yaml_any(str(CORE_TASKS))]
        grant = task_including(CORE_TASKS, includes(GRANT_FILE))["name"]
        self.assertLess(names.index(API_KEY_ASSERT), names.index(grant))

    def test_negative_control_an_always_true_assert_lets_the_gateway_pass(self):
        task = assert_task(CORE_TASKS, API_KEY_ASSERT)
        hollow = {**task["ansible.builtin.assert"], "that": ["true"]}
        task = dict(task, **{"ansible.builtin.assert": hollow})
        self.assertFalse(self.refused(task, False, True, []))


class TestAdministratorFirst(unittest.TestCase):
    def test_ldap_without_sso_converges_the_platform_administrator(self):
        task = task_including(CORE_TASKS, includes(ADMIN_FILE))
        scope = {"OPENWEBUI_OIDC_ENABLED": False, "OPENWEBUI_LDAP_ENABLED": True}
        self.assertTrue(runs(task, scope))

    def test_sso_leaves_administrators_to_the_role_mapping(self):
        task = task_including(CORE_TASKS, includes(ADMIN_FILE))
        scope = {"OPENWEBUI_OIDC_ENABLED": True, "OPENWEBUI_LDAP_ENABLED": True}
        self.assertFalse(runs(task, scope))

    def test_the_administrator_exists_before_every_grant_step(self):
        names = [task.get("name", "") for task in load_yaml_any(str(CORE_TASKS))]
        admin = task_including(CORE_TASKS, includes(ADMIN_FILE))["name"]
        for step in (GRANT_FILE, MCP_FILE):
            with self.subTest(step=step):
                later = task_including(CORE_TASKS, includes(step))["name"]
                self.assertLess(names.index(admin), names.index(later))

    def test_negative_control_the_old_gate_skips_ldap(self):
        admin = task_including(CORE_TASKS, includes(ADMIN_FILE))
        task = dict(admin, when=OLD_ADMIN_GATE)
        scope = {"OPENWEBUI_OIDC_ENABLED": False, "OPENWEBUI_LDAP_ENABLED": True}
        self.assertFalse(runs(task, scope))


class TestLdapAdministratorPassword(unittest.TestCase):
    def setUp(self):
        self.task = task_including(ADMIN_TASKS, lambda t: "ansible.builtin.shell" in t)

    def test_ldap_never_hands_the_registry_password_over(self):
        cmd, stdin, environment = rendered_admin_step(self.task, ldap=True)
        self.assertNotIn(REGISTRY_PASSWORD, stdin)
        self.assertNotIn("OPENWEBUI_ADMIN_PASSWORD", cmd)
        self.assertEqual(stdin, "SCRIPT")
        self.assertEqual(environment["OPENWEBUI_ADMIN_LDAP"], "true")

    def test_without_ldap_the_registry_password_converges(self):
        cmd, stdin, environment = rendered_admin_step(self.task, ldap=False)
        self.assertEqual(stdin, f"{REGISTRY_PASSWORD}\nSCRIPT")
        self.assertIn("read -r OPENWEBUI_ADMIN_PASSWORD", cmd)
        self.assertIn("-e OPENWEBUI_ADMIN_PASSWORD", cmd)
        self.assertEqual(environment["OPENWEBUI_ADMIN_LDAP"], "false")

    def test_negative_control_the_old_stdin_hands_it_over_in_ldap_mode(self):
        shell = {**self.task["ansible.builtin.shell"], "stdin": OLD_ADMIN_STDIN}
        old = dict(self.task, **{"ansible.builtin.shell": shell})
        _cmd, stdin, _environment = rendered_admin_step(old, ldap=True)
        self.assertIn(REGISTRY_PASSWORD, stdin)


class TestGatewayFailureStops(unittest.TestCase):
    def setUp(self):
        self.grant = task_including(GRANT_TASKS, lambda t: "ansible.builtin.shell" in t)
        self.stop = task_including(GRANT_TASKS, lambda t: "ansible.builtin.fail" in t)
        self.failed_rc = role_vars()["OPENWEBUI_GATEWAY_FAILED_RC"]

    def test_a_gateway_failure_ends_the_retries_and_stops_with_its_reason(self):
        scope = grant_result(self.failed_rc)
        self.assertTrue(evaluate(self.grant["until"], scope))
        self.assertFalse(evaluate(self.grant["failed_when"], scope))
        self.assertTrue(runs(self.stop, scope))
        self.assertIn("stderr", self.stop["ansible.builtin.fail"]["msg"])

    def test_an_open_webui_failure_is_retried(self):
        scope = grant_result(1)
        self.assertFalse(evaluate(self.grant["until"], scope))
        self.assertTrue(evaluate(self.grant["failed_when"], scope))
        self.assertFalse(runs(self.stop, scope))

    def test_a_success_neither_retries_nor_stops(self):
        scope = grant_result(0)
        self.assertTrue(evaluate(self.grant["until"], scope))
        self.assertFalse(runs(self.stop, scope))

    def test_negative_control_the_old_until_retries_a_gateway_failure(self):
        scope = grant_result(self.failed_rc)
        self.assertFalse(evaluate("openwebui_model_grants.rc == 0", scope))


if __name__ == "__main__":
    unittest.main()
