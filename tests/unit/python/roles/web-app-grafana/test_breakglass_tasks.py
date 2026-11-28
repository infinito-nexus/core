import unittest

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles/web-app-grafana"
TASKS = load_yaml_any(str(ROLE_DIR / "tasks/01_breakglass.yml"))
VARS = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))


def _reset_task(tasks):
    return next(
        task
        for task in tasks
        if "reset-admin-password" in str(task.get("ansible.builtin.command", ""))
    )


def _resolve_task(tasks):
    return next(
        task
        for task in tasks
        if "resolve_host_cid.yml" in str(task.get("ansible.builtin.include_tasks", ""))
    )


class TestBreakglassReachesTheInstanceTask(unittest.TestCase):
    """In swarm a ``container_address`` is a ``$(resolve-container-id ...)``
    subshell; a label suffix appended to it names no container, and the
    resolver refuses to run off the manager. The reset must exec into the
    instance's own task on the node that runs it."""

    def test_reset_execs_into_the_resolved_local_container(self):
        argv = _reset_task(TASKS)["ansible.builtin.command"]["argv"]
        self.assertEqual(["container", "exec", "-i"], argv[:3])
        self.assertEqual("{{ GRAFANA_LOCAL_CID }}", argv[3])

    def test_reset_runs_on_the_node_of_the_instance(self):
        self.assertEqual(
            "{{ GRAFANA_HOST_NODE }}", _reset_task(TASKS).get("delegate_to")
        )

    def test_password_reaches_grafana_on_stdin_only(self):
        command = _reset_task(TASKS)["ansible.builtin.command"]
        self.assertEqual("{{ GRAFANA_BREAKGLASS_PASSWORD }}", command["stdin"])
        self.assertNotIn("GRAFANA_BREAKGLASS_PASSWORD", " ".join(command["argv"]))

    def test_compose_fallback_is_the_instance_container_name(self):
        compose_cid = _resolve_task(TASKS)["vars"]["resolve_compose_cid"]
        self.assertEqual("{{ GRAFANA_INSTANCE_CONTAINER }}", compose_cid)
        self.assertEqual(
            "{{ GRAFANA_CONTAINER | labelled(grafana_instance.label, '-') }}",
            VARS["GRAFANA_INSTANCE_CONTAINER"],
        )

    def test_no_label_is_appended_to_a_swarm_resolver_subshell(self):
        for name, value in VARS.items():
            if "labelled" in str(value):
                self.assertNotIn("container_address", str(value), name)
                self.assertNotIn("CONTAINER_ADDRESS", str(value), name)


if __name__ == "__main__":
    unittest.main()
