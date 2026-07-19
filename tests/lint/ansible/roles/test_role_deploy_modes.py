"""Lint: every role with a compose template MUST declare its deploy modes.

A role that ships a ``templates/*compose*.yml.j2`` renders a Docker stack, so
it MUST state on its primary service entity whether it participates in each
deploy mode::

    <primary_entity>:
      modes:
        compose:
          enabled: true
        swarm:
          enabled: true

This is the SPOT that replaced the former ``meta/tests.yml.skip`` list.
``enabled: false`` opts the role out of that mode's test-deploy matrix (read
by :func:`utils.roles.meta_lookup.get_role_skip`).
"""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_COMPOSE_GLOB = "templates/*compose*.yml.j2"
_MODES = ("compose", "swarm")


def _compose_template_roles():
    roles_dir = PROJECT_ROOT / "roles"
    if not roles_dir.is_dir():
        return
    for role_dir in sorted(roles_dir.iterdir()):
        if role_dir.is_dir() and any(role_dir.glob(_COMPOSE_GLOB)):
            yield role_dir


def _mode_problems(role_dir) -> list[str]:
    services_path = role_dir / ROLE_FILE_META_SERVICES
    if not services_path.is_file():
        return ["missing meta/services.yml (needed to declare deploy modes)"]
    services = load_yaml_any(str(services_path), default_if_missing={})
    entity = get_entity_name(role_dir.name) or role_dir.name
    primary = services.get(entity) if isinstance(services, dict) else None
    if not isinstance(primary, dict):
        return [f"no primary entity '{entity}' block in meta/services.yml"]
    modes = primary.get("modes")
    if not isinstance(modes, dict):
        return [f"'{entity}.modes' missing (declare compose + swarm enablement)"]
    problems: list[str] = []
    for mode in _MODES:
        entry = modes.get(mode)
        if not isinstance(entry, dict) or not isinstance(entry.get("enabled"), bool):
            problems.append(f"'{entity}.modes.{mode}.enabled' missing or not a bool")
    return problems


class TestRoleDeployModes(unittest.TestCase):
    def test_compose_roles_declare_deploy_modes(self) -> None:
        offenders: dict[str, list[str]] = {}
        for role_dir in _compose_template_roles():
            problems = _mode_problems(role_dir)
            if problems:
                offenders[role_dir.name] = problems

        if not offenders:
            return

        lines = [
            f"{len(offenders)} role(s) with a compose template do not declare "
            "their deploy modes on the primary service entity:"
        ]
        for name, problems in sorted(offenders.items()):
            lines.append(f"  - {name}:")
            lines.extend(f"      * {problem}" for problem in problems)
        lines.append("")
        lines.append("Add under the primary entity in meta/services.yml:")
        lines.append(
            "  modes:\n"
            "    compose:\n      enabled: true\n"
            "    swarm:\n      enabled: true"
        )
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
