"""Forbid ``placement: manager`` in a role that also enables the kata sandbox.

Rationale
=========
``roles/sys-svc-container/templates/deploy.yml.j2`` appends both constraints to
the same ``_constraints`` list, which swarm evaluates as a conjunction:

* ``node.role == manager`` when the role appears in ``roles_with_placement``
  (``:11-13``), which any ``placement: manager`` in its ``meta/services.yml``
  triggers, for every service of that role.
* ``node.labels.<SANDBOX_NODE_LABEL> == true`` when
  ``services.kata.enabled`` is truthy (``:18-20``), again role-wide.

``roles/svc-virt-kata/tasks/00_core.yml:62-70`` adds that label only
``when: not (IS_STACK_HOST | bool)``, so the manager never carries it. The two
constraints therefore have an empty intersection and the service becomes
unschedulable: the deploy does not fail at ``docker stack deploy`` but hangs in
the converge wait, which reads as a timeout rather than as a placement error.

Per-line opt-out
================
Add ``# nocheck: sandbox-placement-manager`` on the same line as
``placement: manager`` OR on the immediately preceding non-empty line, together
with a comment explaining how the manager is expected to obtain the sandbox
label.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

_RULE = "sandbox-placement-manager"

_PLACEMENT_MANAGER = re.compile(
    r"^\s*placement\s*:\s*['\"]?manager['\"]?\s*(?:#.*)?$"
)


def _is_scan_target(rel_path: str) -> bool:
    return (
        rel_path.startswith("roles/")
        and "/meta/" in rel_path
        and rel_path.endswith("services.yml")
    )


def _kata_is_enabled(content: str) -> bool:
    """True only for a literal ``true``; a template is not statically decidable."""
    try:
        data = load_yaml_str(content)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    kata = data.get("kata")
    return isinstance(kata, dict) and kata.get("enabled") is True


class TestNoPlacementManagerWithSandbox(unittest.TestCase):
    def test_a_sandboxed_role_is_never_pinned_to_the_manager(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel) or not _kata_is_enabled(content):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not _PLACEMENT_MANAGER.match(line):
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, idx + 1, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {s}"
                for p, n, s in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found `placement: manager` in a role whose `meta/services.yml` "
                "also sets `kata.enabled: true`. Both add a constraint to the "
                "same list in roles/sys-svc-container/templates/deploy.yml.j2, "
                "swarm ANDs them, and roles/svc-virt-kata/tasks/00_core.yml "
                "never labels the stack host, so no node can satisfy both. The "
                "service does not fail to deploy, it fails to schedule and the "
                "round dies in the converge wait.\n\n"
                "Default: drop the pin. A sandboxed workload belongs on a "
                "labelled worker; if it has to reach a manager-local resource, "
                "delegate that step to the owning node instead of pinning the "
                "whole service.\n\n"
                f"Offenders:\n{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
