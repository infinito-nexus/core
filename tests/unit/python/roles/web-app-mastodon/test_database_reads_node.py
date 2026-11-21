from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader

from utils.cache import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-mastodon"
STACK_HOST = ROLE / "tasks" / "stack_host.yml"
READERS = ("06_design.yml", "07_login_methods.yml")
RESOLVER = "roles/sys-svc-compose/tasks/utils/swarm/resolve_host_cid.yml"
DATABASE_NODE = "{{ MASTODON_DATABASE_HOST_NODE }}"


def _load(path) -> list[dict]:
    return DataLoader().load_from_file(str(path), trusted_as_template=True)


def _included(task: dict) -> str:
    include = task.get("include_tasks") or task.get("ansible.builtin.include_tasks")
    return str(include.get("file", "") if isinstance(include, dict) else include or "")


class TestTheStoredSettingsAreReadOnTheDatabaseNode(unittest.TestCase):
    def test_every_database_read_runs_on_the_database_node(self) -> None:
        for name in READERS:
            reads = [
                task
                for task in _load(ROLE / "tasks" / name)
                if "database_query" in task
            ]
            with self.subTest(tasks=name):
                self.assertTrue(reads)
                for task in reads:
                    self.assertEqual(DATABASE_NODE, task.get("delegate_to"))

    def test_the_database_node_is_resolved_before_the_readers(self) -> None:
        tasks = _load(STACK_HOST)
        resolve = next(
            (
                index
                for index, task in enumerate(tasks)
                if RESOLVER in _included(task)
                and task["vars"]["resolve_output_prefix"] == "MASTODON_DATABASE"
            ),
            None,
        )
        self.assertIsNotNone(resolve, "stack_host.yml resolves no MASTODON_DATABASE")
        self.assertIn(
            "lookup('database', application_id, 'service_name')",
            tasks[resolve]["vars"]["resolve_service_name"],
        )
        self.assertIn(
            "lookup('database', application_id, 'container')",
            tasks[resolve]["vars"]["resolve_compose_cid"],
        )
        for name in READERS:
            with self.subTest(tasks=name):
                self.assertLess(
                    resolve,
                    next(i for i, task in enumerate(tasks) if _included(task) == name),
                )


if __name__ == "__main__":
    unittest.main()
