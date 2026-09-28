"""Lint guard for service keys two roles would both claim.

A role's service key defaults to ``get_entity_name(role_name)``, which
strips the longest matching category prefix. Two roles under different
categories therefore collapse onto the same key whenever the remainder is
equal (``svc-ai-libretranslate`` and ``web-svc-libretranslate`` both reduce
to ``libretranslate``). The service registry raises on that, but only once
some unrelated consumer builds it, so the failure surfaces far from the role
that caused it.

``provides:`` only renames the key a role registers under. The entity name
itself still drives the instance directory, the compose project and the
container name, so two roles that ship a compose template and reduce to the
same entity overwrite each other's rendered stack no matter what they
advertise. That is unfixable with ``provides:`` and needs a role rename.

Failure modes covered:
  * Two roles resolve to the same service key and neither disambiguates
    with ``meta/services.yml.<entity>.provides``.
  * Two roles that both render a compose stack share an entity name, so the
    later one overwrites the earlier one's instance directory.
"""

from __future__ import annotations

import unittest
from collections import defaultdict

from utils.roles.applications.services.registry import (
    discover_role_services,
    load_applications_from_roles_dir,
)
from utils.roles.entity.name import get_entity_name

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
COMPOSE_TEMPLATE = ("templates", "compose.yml.j2")


class TestServiceKeyCollision(unittest.TestCase):
    def test_roles_sharing_an_entity_name_declare_provides(self):
        owners: dict[str, set[str]] = defaultdict(set)
        for role_name, config in load_applications_from_roles_dir(ROLES_DIR).items():
            for service_key in discover_role_services(role_name, config):
                owners[service_key].add(role_name)

        clashes = {key: roles for key, roles in owners.items() if len(roles) > 1}
        if clashes:
            self.fail(
                "Service key claimed by more than one role:\n"
                + "\n".join(
                    f"  - '{key}': {', '.join(sorted(roles))}"
                    for key, roles in sorted(clashes.items())
                )
                + "\n\nFix: a role's key defaults to its name minus the category "
                "prefix, so two categories sharing a suffix collide. Give all but "
                "one of them a distinct `provides:` under "
                "`meta/services.yml.<entity>`."
            )

    def test_roles_rendering_a_compose_stack_have_distinct_entity_names(self):
        owners: dict[str, set[str]] = defaultdict(set)
        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            if role_dir.joinpath(*COMPOSE_TEMPLATE).is_file():
                owners[get_entity_name(role_dir.name)].add(role_dir.name)

        self.assertTrue(owners, f"no role under {ROLES_DIR} renders a compose stack")

        clashes = {key: roles for key, roles in owners.items() if len(roles) > 1}
        if clashes:
            self.fail(
                "Entity name shared by more than one compose-rendering role:\n"
                + "\n".join(
                    f"  - '{key}': {', '.join(sorted(roles))}"
                    for key, roles in sorted(clashes.items())
                )
                + "\n\nFix: the entity name keys the instance directory, the "
                "compose project and the container name, so the role deployed "
                "later overwrites the other's rendered stack. `provides:` does "
                "not help here; rename one of the roles."
            )
