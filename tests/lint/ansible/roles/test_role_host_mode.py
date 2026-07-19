"""Lint: invokable non-stack roles MUST declare modes.host.enabled.

A role that is invokable but ships no container stack
(``templates/*compose*.yml.j2``) deploys in *host* mode: it configures the
host rather than running a stack. It MUST state that intent on its primary
service entity::

    <primary_entity>:
      modes:
        host:
          enabled: true

This is the SPOT that fills the complexity matrix's ``host`` column. Stack
roles use the compose/swarm modes instead (see
``test_role_deploy_modes.py``) and are exempt here.
"""

from __future__ import annotations

import unittest

from cli.meta.roles.applications.complexity.graph import role_has_stack
from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.validation.invokable import _get_invokable_paths, _is_role_invokable

from . import PROJECT_ROOT


def _host_problem(role_dir) -> str | None:
    services_path = role_dir / ROLE_FILE_META_SERVICES
    if not services_path.is_file():
        return "missing meta/services.yml (needed to declare modes.host.enabled)"
    services = load_yaml_any(str(services_path), default_if_missing={})
    entity = get_entity_name(role_dir.name) or role_dir.name
    primary = services.get(entity) if isinstance(services, dict) else None
    if not isinstance(primary, dict):
        return f"no primary entity '{entity}' block in meta/services.yml"
    modes = primary.get("modes")
    host = modes.get("host") if isinstance(modes, dict) else None
    if not isinstance(host, dict) or not isinstance(host.get("enabled"), bool):
        return f"'{entity}.modes.host.enabled' missing or not a bool"
    return None


class TestRoleHostMode(unittest.TestCase):
    def test_invokable_non_stack_roles_declare_host_mode(self) -> None:
        invokable_paths = _get_invokable_paths()
        offenders: dict[str, str] = {}
        for role_dir in sorted((PROJECT_ROOT / "roles").iterdir()):
            if not role_dir.is_dir():
                continue
            if not _is_role_invokable(role_dir.name, invokable_paths):
                continue
            if role_has_stack(role_dir):
                continue
            problem = _host_problem(role_dir)
            if problem:
                offenders[role_dir.name] = problem

        if not offenders:
            return

        lines = [
            f"{len(offenders)} invokable non-stack role(s) do not declare "
            "modes.host.enabled on their primary service entity:"
        ]
        for name, problem in sorted(offenders.items()):
            lines.append(f"  - {name}: {problem}")
        lines.append("")
        lines.append("Add under the primary entity in meta/services.yml:")
        lines.append("  modes:\n    host:\n      enabled: true")
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
