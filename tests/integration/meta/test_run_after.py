from __future__ import annotations

import unittest

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES


def run_after(role: str, entity: str) -> list[str]:
    services = load_yaml_any(
        str(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES)
    )
    return services[entity].get("run_after", [])


class TestRunAfter(unittest.TestCase):
    def test_openbao_runs_after_semaphore(self) -> None:
        self.assertIn("web-app-semaphore", run_after("web-app-openbao", "openbao"))

    def test_semaphore_never_waits_for_openbao(self) -> None:
        self.assertNotIn("web-app-openbao", run_after("web-app-semaphore", "semaphore"))


if __name__ == "__main__":
    unittest.main()
