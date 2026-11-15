from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES

BACK = PROJECT_ROOT / "roles/svc-stack/tasks/batch/back.yml"
CONTRACT = "roles/svc-ai-litellm/tasks/utils/consumer_contract.yml"
BACKEND = "backend.yml"
GATEWAY_ENTITY = "litellm"
MOVED = (
    "roles/web-app-hermes/tasks/00_core.yml",
    "roles/web-app-openclaw/tasks/00_core.yml",
    "roles/web-app-openwebui/tasks/00_core.yml",
    "roles/web-svc-translate/tasks/00_core.yml",
    "roles/web-app-mattermost/tasks/utils/ai_gateway.yml",
    "roles/web-app-moodle/tasks/utils/ai_gateway.yml",
    "roles/web-app-n8n/tasks/utils/ai_gateway.yml",
    "roles/web-app-zammad/tasks/01_manager_ops.yml",
)


def _include(task: dict) -> str:
    return str(task.get("ansible.builtin.include_tasks"))


def _contract_task() -> dict:
    return next(task for task in load_yaml_any(str(BACK)) if CONTRACT in _include(task))


class TestBackGatewayContract(unittest.TestCase):
    def test_the_back_unit_checks_the_contract_before_the_backend(self) -> None:
        files = [_include(task) for task in load_yaml_any(str(BACK))]
        contract = next(index for index, name in enumerate(files) if CONTRACT in name)
        self.assertLess(contract, files.index(BACKEND))

    def test_the_contract_is_keyed_by_the_consumer_flag(self) -> None:
        task = _contract_task()
        when = " ".join(task["when"])
        self.assertIn("'services.litellm.enabled'", when)
        self.assertIn(f"entity_name) != '{GATEWAY_ENTITY}'", when)
        self.assertNotIn("default(", when)
        self.assertEqual(task["vars"], {"application_id": "{{ stack_batch_consumer }}"})

    def test_every_role_that_runs_the_gateway_service_is_excluded(self) -> None:
        for path in sorted(PROJECT_ROOT.glob(f"roles/*/{ROLE_FILE_META_SERVICES}")):
            block = load_yaml_any(str(path)).get("litellm")
            if isinstance(block, dict) and "modes" in block:
                role = path.relative_to(PROJECT_ROOT / "roles").parts[0]
                with self.subTest(role=role):
                    self.assertEqual(entity_name(role), GATEWAY_ENTITY)

    def test_no_moved_caller_keeps_its_own_contract_call(self) -> None:
        for rel in MOVED:
            with self.subTest(file=rel):
                self.assertNotIn(CONTRACT, read_text(str(PROJECT_ROOT / rel)))


if __name__ == "__main__":
    unittest.main()
