from __future__ import annotations

import unittest

from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
    ordered_primary_service_entries,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.meta_lookup import get_role_run_after

from . import PROJECT_ROOT
from .test_stack_batch_closure import P1_SEED, P2_SEED, STACK_ROLE, walk
from .test_stack_bridge import bridge_roles

ROLES = PROJECT_ROOT / "roles"


def loader_order() -> list[str]:
    """Returns:
    the shared-service roles in the order the loader preloads them.
    """
    return [
        entry["role"]
        for entry in ordered_primary_service_entries(
            build_service_registry_from_roles_dir(ROLES), ROLES
        )
    ]


def front_path_providers() -> list[str]:
    """Returns:
    the shared-service roles the warm-up or the fronts of the batch enter,
    svc-stack aside: the providers svc-stack must run after.
    """
    p1 = walk(P1_SEED)
    p2 = walk(P2_SEED, frozenset({*p1.flags, STACK_ROLE.replace("-", "_")}))
    entered = {
        path.relative_to(ROLES).parts[0]
        for path in p1.files | p2.files
        if path.is_relative_to(ROLES)
    }
    return sorted((entered & set(loader_order())) - {STACK_ROLE})


class TestStackBatchOrder(unittest.TestCase):
    def test_svc_stack_pins_every_provider_its_front_path_reaches(self) -> None:
        self.assertEqual(
            sorted(get_role_run_after(ROLES / STACK_ROLE, role_name=STACK_ROLE)),
            front_path_providers(),
            "declare exactly these roles as run_after of stack in "
            f"roles/svc-stack/{ROLE_FILE_META_SERVICES}",
        )

    def test_svc_stack_runs_after_each_pin(self) -> None:
        order = loader_order()
        early = [
            pin
            for pin in get_role_run_after(ROLES / STACK_ROLE, role_name=STACK_ROLE)
            if order.index(pin) > order.index(STACK_ROLE)
        ]
        self.assertEqual(early, [])

    def test_svc_stack_precedes_every_bridged_service(self) -> None:
        order = loader_order()
        before = [
            role
            for role in bridge_roles(PROJECT_ROOT)
            if role in order and order.index(role) < order.index(STACK_ROLE)
        ]
        self.assertEqual(
            before,
            [],
            "a bridged service the loader enters before svc-stack never joins "
            "the front batch",
        )


if __name__ == "__main__":
    unittest.main()
