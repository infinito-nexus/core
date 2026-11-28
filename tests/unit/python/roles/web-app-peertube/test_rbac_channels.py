import unittest

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles/web-app-peertube"
PROVISION = load_yaml_any(str(ROLE_DIR / "tasks/rbac/provision.yml"))
VARS = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))


def _conditions(task):
    when = task.get("when", [])
    return list(when) if isinstance(when, list) else [when]


def _flattened(tasks, inherited=()):
    """Returns the leaf tasks in run order, each with the ``when`` conditions of
    its enclosing blocks prepended to its own as a list.

    Args:
        tasks: a task list as loaded from YAML.
        inherited: the conditions of the enclosing blocks.
    """
    flat = []
    for task in tasks:
        conditions = [*inherited, *_conditions(task)]
        if "block" in task:
            flat.extend(_flattened(task["block"], conditions))
        else:
            flat.append({**task, "when": conditions})
    return flat


RBAC = _flattened(load_yaml_any(str(ROLE_DIR / "tasks/05_rbac.yml")))


def _hook_vars():
    return next(
        task["vars"]
        for task in RBAC
        if "rbac/sync.yml" in str(task.get("ansible.builtin.include_tasks", ""))
    )


def _api_task():
    return next(task for task in PROVISION if "rbac/provision.py" in str(task))


class TestPeertubeRbacSplitsByChannel(unittest.TestCase):
    """In swarm the hook runs on the database node, where PeerTube publishes
    no port; only its own network namespace reaches the API."""

    def test_the_hook_receives_no_api_url_and_no_root_password(self):
        env = _hook_vars()["rbac_sync_env"]
        self.assertNotIn("PEERTUBE_URL", env)
        self.assertNotIn("PEERTUBE_HOSTNAME", env)
        self.assertNotIn("PEERTUBE_ROOT_PASSWORD", env)
        self.assertNotIn("PEERTUBE_ROOT_PASSWORD", str(_hook_vars()))

    def test_the_hook_ships_only_the_link_and_reconcile_sql(self):
        self.assertEqual(
            ["link-preprovisioned-accounts.sql", "reconcile-roles.sql"],
            [module["name"] for module in _hook_vars()["rbac_sync_modules"]],
        )

    def test_the_hook_carries_no_per_run_fact(self):
        """A per-run value in hook.json flips the hook to changed on every deploy
        and loses what a failed run created."""
        hook = str(_hook_vars())
        self.assertNotIn("PEERTUBE_RBAC_CREATED", hook)
        self.assertNotIn("hostvars", hook)
        self.assertNotIn("peertube_rbac_created", str(PROVISION))

    def test_provisioning_runs_once_on_the_stack_host_before_the_hook(self):
        names = [str(task.get("ansible.builtin.include_tasks")) for task in RBAC]
        provision = names.index("rbac/provision.yml")
        hook = next(i for i, name in enumerate(names) if "rbac/sync.yml" in name)
        self.assertLess(provision, hook)
        self.assertIn("inventory_hostname == STACK_HOST", RBAC[provision]["when"])
        self.assertNotIn("IS_STACK_HOST | bool", RBAC[provision]["when"])
        self.assertIn("PEERTUBE_OIDC_ENABLED | bool", RBAC[provision]["when"])

    def test_a_play_without_the_stack_host_fails_instead_of_skipping(self):
        """--limit manager2 would otherwise skip the creation silently."""
        names = [str(task.get("ansible.builtin.include_tasks")) for task in RBAC]
        guard = next(
            i for i, task in enumerate(RBAC) if "ansible.builtin.assert" in task
        )
        self.assertLess(guard, names.index("rbac/provision.yml"))
        self.assertEqual(
            "STACK_HOST in ansible_play_hosts_all",
            RBAC[guard]["ansible.builtin.assert"]["that"],
        )
        self.assertEqual(["PEERTUBE_OIDC_ENABLED | bool"], RBAC[guard]["when"])

    def test_a_transient_api_failure_is_retried_then_named_after_the_hook(self):
        """One unprovisionable member must not block the link and the demotions."""
        task = _api_task()
        self.assertEqual("peertube_rbac_provision.rc == 0", task["until"])
        self.assertGreaterEqual(task["retries"], 1)
        self.assertIs(False, task["failed_when"])
        self.assertFalse([t for t in PROVISION if "ansible.builtin.fail" in t])
        hook = next(
            i
            for i, t in enumerate(RBAC)
            if "rbac/sync.yml" in str(t.get("ansible.builtin.include_tasks", ""))
        )
        failure = next(i for i, t in enumerate(RBAC) if "ansible.builtin.fail" in t)
        self.assertGreater(failure, hook)
        self.assertIn(
            "peertube_rbac_provision.rc | default(0) != 0", RBAC[failure]["when"]
        )
        self.assertIn(
            ".failed | rejectattr('warning')",
            RBAC[failure]["ansible.builtin.fail"]["msg"],
        )

    def test_a_conflict_with_a_local_account_warns_without_failing(self):
        """A stranger's signup under a member's username or e-mail must not fail
        every deploy; the script exits 0 for it and the play only names it."""
        warning = next(i for i, t in enumerate(RBAC) if "ansible.builtin.debug" in t)
        failure = next(i for i, t in enumerate(RBAC) if "ansible.builtin.fail" in t)
        self.assertLess(warning, failure)
        self.assertIn(
            ".failed | selectattr('warning')",
            RBAC[warning]["ansible.builtin.debug"]["msg"],
        )
        for index in (warning, failure):
            self.assertIn("peertube_rbac_provision is defined", RBAC[index]["when"])

    def test_the_api_runs_inside_the_peertube_namespace_on_its_node(self):
        task = _api_task()
        self.assertEqual(
            "{{ PEERTUBE_NETNS_PYTHON }}", task["ansible.builtin.command"]["argv"]
        )
        self.assertEqual("{{ PEERTUBE_HOST_NODE }}", task["delegate_to"])
        self.assertIs(True, task["become"])
        self.assertEqual(
            "{{ PEERTUBE_NETNS_URL }}", task["vars"]["peertube_rbac_payload"]["url"]
        )

    def test_the_root_password_reaches_the_api_program_on_stdin_only(self):
        task = _api_task()
        self.assertIn("peertube_rbac_payload", task["ansible.builtin.command"]["stdin"])
        self.assertNotIn("environment", task)

    def test_no_host_port_url_is_left(self):
        self.assertNotIn("PEERTUBE_INTERNAL_URL", VARS)
        self.assertNotIn("ports.local", str(VARS.get("PEERTUBE_NETNS_URL")))


if __name__ == "__main__":
    unittest.main()
