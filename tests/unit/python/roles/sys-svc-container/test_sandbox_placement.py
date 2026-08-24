import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT

TEMPLATES = Path(PROJECT_ROOT) / "roles" / "sys-svc-container" / "templates"

SANDBOX_LABEL = "kata-capable"


def _ansible_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"y", "yes", "true", "on", "1"}
    return bool(value)


BASE = {
    "compose_mode": "swarm",
    "application_id": "web-app-hermes",
    "service_name": "hermes",
    "RUNTIME": "local",
    "SANDBOX_NODE_LABEL": SANDBOX_LABEL,
    "DOCKER_RESTART_POLICY": "unless-stopped",
    "RESOURCE_CPUS": "1",
    "RESOURCE_MEM_LIMIT": "1g",
    "RESOURCE_MEM_RESERVATION": "256m",
    "RESOURCE_PIDS_LIMIT": "512",
}


class TestSandboxPlacement(unittest.TestCase):
    def _render(
        self, kata_enabled, manager_placed=False, sandbox_tier=True, **overrides
    ):
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATES)),
            trim_blocks=True,
            lstrip_blocks=False,
            undefined=StrictUndefined,
            autoescape=select_autoescape(),
        )
        env.filters["bool"] = _ansible_bool
        env.filters["resource_filter"] = lambda _apps, *_a, **_k: ""
        env.filters["swarm_restart_condition"] = lambda value: value

        def _lookup(name, *args, **kwargs):
            if name == "applications":
                return {}
            if name == "compose_replicas":
                return "replicas: 3"
            if name == "roles_with_placement":
                return ["web-app-hermes"] if manager_placed else []
            if name == "config":
                return kata_enabled
            raise AssertionError(f"unexpected lookup: {name}")

        env.globals["lookup"] = _lookup
        groups = {"svc-virt-kata": ["wrk-02"]} if sandbox_tier else {}
        return env.get_template("deploy.yml.j2").render(
            {**BASE, "groups": groups, **overrides}
        )

    def _constraints(self, rendered):
        lines = [line.strip() for line in rendered.splitlines()]
        return [line[2:] for line in lines if line.startswith("- node.")]

    def test_sandbox_consumer_is_pinned_to_a_sandbox_node(self):
        constraints = self._constraints(self._render(kata_enabled=True))
        self.assertIn(f"node.labels.{SANDBOX_LABEL} == true", constraints)

    def test_every_other_service_is_kept_off_the_sandbox_nodes(self):
        constraints = self._constraints(self._render(kata_enabled=False))
        self.assertIn(f"node.labels.{SANDBOX_LABEL} != true", constraints)

    def test_the_two_directions_are_mutually_exclusive(self):
        for enabled in (True, False):
            with self.subTest(kata_enabled=enabled):
                constraints = self._constraints(self._render(kata_enabled=enabled))
                self.assertEqual(len([c for c in constraints if SANDBOX_LABEL in c]), 1)

    def test_a_cluster_without_a_sandbox_tier_gets_no_sandbox_constraint(self):
        for enabled in (True, False):
            with self.subTest(kata_enabled=enabled):
                constraints = self._constraints(
                    self._render(kata_enabled=enabled, sandbox_tier=False)
                )
                self.assertEqual([c for c in constraints if SANDBOX_LABEL in c], [])

    def test_manager_placement_composes_with_the_sandbox_constraint(self):
        constraints = self._constraints(
            self._render(kata_enabled=False, manager_placed=True)
        )
        self.assertIn("node.role == manager", constraints)
        self.assertIn(f"node.labels.{SANDBOX_LABEL} != true", constraints)

    def test_manager_placement_survives_without_a_sandbox_tier(self):
        constraints = self._constraints(
            self._render(kata_enabled=False, manager_placed=True, sandbox_tier=False)
        )
        self.assertEqual(constraints, ["node.role == manager"])

    def test_compose_mode_emits_no_deploy_block(self):
        rendered = self._render(kata_enabled=True, compose_mode="compose")
        self.assertEqual(rendered.strip(), "")


if __name__ == "__main__":
    unittest.main()
