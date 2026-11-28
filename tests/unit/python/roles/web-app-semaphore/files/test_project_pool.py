"""The Semaphore project converger seeds the pool project only when asked to."""

from __future__ import annotations

import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from ._semaphore_fake import (
    ROLE,
    FakeSemaphore,
    app_control_spec,
    load_project,
    playbook_refusal,
)

POOL_PROJECT = "Infinito.Nexus Pool"
CHECKOUT = "/home/operator/.local/share/worktrees/github.com/infinito-nexus/core/main"
SCRIPT = "scripts/tests/deploy/job/semaphore.sh"


def pool_spec():
    return {
        "project": POOL_PROJECT,
        "runner_tag": "pool",
        "inventory": "deploy",
        "repository": {"name": "deploy", "path": CHECKOUT},
        "environment": "deploy",
        "task_template": {"name": "deploy", "playbook": SCRIPT},
    }


class PoolConvergeTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api = FakeSemaphore(self.mod.ApiError)

    def converge(self, document):
        return self.mod.converge(self.api, document, lambda seconds: None)[0]

    def test_negative_control_without_a_pool_block_no_pool_project_exists(self):
        self.converge(app_control_spec(["web-app-wiki"]))
        self.assertNotIn(POOL_PROJECT, [p["name"] for p in self.api.projects])

    def test_the_pool_project_runs_the_pinned_submit_on_the_pool_tag(self):
        self.converge({**app_control_spec(["web-app-wiki"]), "pool": pool_spec()})
        project_id = self.api.project_id(POOL_PROJECT)
        templates = self.api.templates(project_id)
        self.assertEqual(sorted(templates), ["deploy"])
        template = templates["deploy"]
        self.assertEqual(template["runner_tag"], "pool")
        self.assertEqual(template["playbook"], SCRIPT)
        self.assertEqual(template["app"], self.mod.APP)
        self.assertIsNone(playbook_refusal(template["playbook"]))
        self.assertEqual(
            [(v["name"], v["required"]) for v in template["survey_vars"]],
            [("APPS", True)],
        )
        (repository,) = self.api.objects[(project_id, "repositories")]
        self.assertEqual(repository["git_url"], CHECKOUT)

    def test_a_second_run_writes_nothing(self):
        document = {**app_control_spec(["web-app-wiki"]), "pool": pool_spec()}
        self.converge(document)
        self.assertEqual(self.converge(document), [])

    def test_the_script_is_the_one_the_role_names(self):
        role_vars = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.assertEqual(role_vars["SEMAPHORE_POOL_SCRIPT"], SCRIPT)
        sync = read_text(str(ROLE / "tasks" / "utils" / "project" / "sync.yml"))
        self.assertIn(
            "combine({'pool': semaphore_project_pool} if SEMAPHORE_POOL_ENABLED | bool else {})",
            sync,
        )


if __name__ == "__main__":
    unittest.main()
