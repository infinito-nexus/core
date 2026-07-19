"""The group-agnostic call order = preload services first (registry run_after
order), then the remaining invokable roles in run_after topological order,
with every prerequisite before its dependents."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from cli.meta.roles.order.run import __main__ as run


class TestBuildCallOrder(unittest.TestCase):
    def _order(self, preload, invokable, run_after):
        with (
            mock.patch.object(
                run, "build_service_registry_from_roles_dir", return_value={}
            ),
            mock.patch.object(
                run,
                "ordered_primary_service_entries",
                return_value=[{"role": r} for r in preload],
            ),
            mock.patch.object(run, "_invokable_role_dirs", return_value=invokable),
            mock.patch.object(
                run,
                "get_role_run_after",
                side_effect=lambda p, role_name: run_after.get(role_name, []),
            ),
        ):
            return run.build_call_order(Path("/roles"))

    def test_preload_first_then_main(self) -> None:
        order = self._order(
            preload=["svc-db-postgres", "svc-db-redis"],
            invokable=["svc-db-postgres", "svc-db-redis", "web-app-a", "web-app-b"],
            run_after={},
        )
        phases = [p for p, _ in order]
        roles = [r for _, r in order]
        self.assertEqual(phases[:2], ["preload", "preload"])
        self.assertEqual(set(roles[:2]), {"svc-db-postgres", "svc-db-redis"})
        self.assertEqual(set(roles[2:]), {"web-app-a", "web-app-b"})
        self.assertTrue(all(p == "main" for p in phases[2:]))

    def test_preload_roles_excluded_from_main(self) -> None:
        order = self._order(
            preload=["svc-db-redis"],
            invokable=["svc-db-redis", "web-app-a"],
            run_after={},
        )
        self.assertEqual([r for _, r in order].count("svc-db-redis"), 1)

    def test_main_respects_run_after(self) -> None:
        order = self._order(
            preload=[],
            invokable=["web-app-a", "web-app-b"],
            run_after={"web-app-a": ["web-app-b"]},
        )
        roles = [r for _, r in order]
        self.assertLess(roles.index("web-app-b"), roles.index("web-app-a"))


if __name__ == "__main__":
    unittest.main()
