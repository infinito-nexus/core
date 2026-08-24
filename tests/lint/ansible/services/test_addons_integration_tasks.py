"""Lint: service-coupled addons must ship a tasks/addons/<id>.yml hook.

An addon whose activation is coupled to another part of the deployment —
either because its ``enabled`` expression reads a service flag via
``lookup('config', '<role>', 'services.<svc>.enabled')`` or because it gates on
``'<role>' in group_names`` — is a deliberate integration, not a standalone
plugin. Its integration logic MUST live in the per-addon task hook
``roles/<role>/tasks/addons/<id>.yml`` so the wiring is explicit and greppable.

The hook is mandatory even when the generic addon ``config:`` payload already
covers everything: in that case the file MUST still exist and carry a short
comment stating that no extra integration logic beyond the generic config is
required. There is no exemption.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.update.addons import iter_addon_files

from . import PROJECT_ROOT

_SERVICE_ENABLED_RE = re.compile(r"services\.[A-Za-z0-9_]+\.enabled")
_GROUP_NAMES_RE = re.compile(r"\bin\s+group_names\b")


def _enabled_expr(addon_file) -> str:
    """Return the addon's ``enabled`` value as a string (empty if absent)."""
    text = read_text(str(addon_file))
    try:
        spec = load_yaml_str(text)
    except Exception:
        spec = None
    if isinstance(spec, dict) and "enabled" in spec:
        return str(spec["enabled"])
    match = re.search(r"^enabled:\s*(.+)$", text, re.MULTILINE)
    return match.group(1) if match else ""


def _is_service_coupled(enabled: str) -> bool:
    return bool(_SERVICE_ENABLED_RE.search(enabled) or _GROUP_NAMES_RE.search(enabled))


class TestAddonsIntegrationTasks(unittest.TestCase):
    def test_service_coupled_addons_have_a_tasks_hook(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")

        errors: list[str] = []
        for role, addon_file in iter_addon_files(roles_root):
            if not _is_service_coupled(_enabled_expr(addon_file)):
                continue
            addon_id = addon_file.stem
            tasks_path = roles_root / role / "tasks" / "addons" / f"{addon_id}.yml"
            if not tasks_path.is_file():
                errors.append(
                    f"{role}: addons.{addon_id} is service-coupled (enabled gates on "
                    f"a service flag or group_names) but has no integration hook at "
                    f"{tasks_path.relative_to(PROJECT_ROOT).as_posix()}; create it with "
                    f"the integration logic, or a comment stating no extra logic is "
                    f"needed beyond the generic addon config."
                )

        if errors:
            self.fail(
                f"service-coupled addon integration-hook violations ({len(errors)}):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
