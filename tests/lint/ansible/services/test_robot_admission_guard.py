"""Lint: every embodiable agent runs the robot admission guard before deploying.

``svc-ai-robot`` hands an agent direct hardware access, so its admission checks
refuse a blanket device grant and refuse a host that carries other tenants. The
checks cannot live in ``svc-ai-robot``'s own tasks — the agent is a shared
service that ``sys-service-loader`` preloads a stage earlier — so each agent
role includes them itself. An agent that forgets the include deploys privileged
onto a shared node and nothing says a word.

The scan derives the agent set from ``svc-ai-robot``'s own service flags rather
than from a list, so a third agent added there fails here until it carries the
guard.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: robot-admission-guard`` on the flag's key line or the non-empty
  line above it.
"""

from __future__ import annotations

import os
import re
import unittest
from collections.abc import Mapping

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "robot-admission-guard"
_ROBOT_ROLE = "svc-ai-robot"
_GUARD = "roles/svc-ai-robot/tasks/utils/admit.yml"

_AGENT_FLAG = re.compile(r"'(?P<role>web-app-[a-z0-9-]+)'\s+in\s+group_names")


def _embodiable_roles() -> dict[str, str]:
    """Return ``{agent role id: flag name}`` for every embodiable agent."""
    services_path = PROJECT_ROOT / "roles" / _ROBOT_ROLE / ROLE_FILE_META_SERVICES
    services = load_yaml_any(str(services_path), default_if_missing={})
    lines = read_text(str(services_path)).splitlines()
    agents: dict[str, str] = {}
    if not isinstance(services, Mapping):
        return agents
    for flag, block in services.items():
        if not isinstance(block, Mapping):
            continue
        match = _AGENT_FLAG.search(str(block.get("enabled") or ""))
        if not match:
            continue
        line_no = next(
            (i + 1 for i, line in enumerate(lines) if line.startswith(f"{flag}:")),
            1,
        )
        if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
            continue
        agents[match["role"]] = flag
    return agents


def _includes_guard(role: str) -> bool:
    tasks_dir = str(PROJECT_ROOT / "roles" / role / "tasks") + os.sep
    return any(
        path.startswith(tasks_dir) and _GUARD in content
        for path, content in iter_project_files_with_content(extensions=(".yml",))
    )


class TestRobotAdmissionGuard(unittest.TestCase):
    def test_every_embodiable_agent_includes_the_guard(self) -> None:
        missing = [
            f"{role} (flag '{flag}'): {_ROBOT_ROLE} can embody it but no task "
            f"includes {_GUARD}, so it would take privileged hardware access "
            f"without the single-tenant and device-allowlist checks"
            for role, flag in sorted(_embodiable_roles().items())
            if not _includes_guard(role)
        ]
        self.assertEqual(
            [],
            missing,
            f"embodiable agent(s) without the admission guard ({len(missing)}):\n"
            + "\n".join(f"  - {m}" for m in missing),
        )

    def test_the_scan_finds_embodiable_agents(self) -> None:
        self.assertTrue(
            _embodiable_roles(),
            f"{_ROBOT_ROLE} declares no web-app agent flag, so the rule would "
            "pass vacuously; check that the scan still reads the right topic",
        )


if __name__ == "__main__":
    unittest.main()
