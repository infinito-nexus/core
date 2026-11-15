from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from plugins.lookup.stack_batch import (
    BRIDGE,
    CANONICAL_BRIDGE,
    STACK_META,
    LookupModule,
    plan,
)
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
    ordered_primary_service_entries,
)
from utils.roles.order import ordered_roles
from utils.roles.stage import stage_groups

LITERAL_STACK = "---\nstack:\n  enabled: true\n  shared: true\n"
SERVICES = [
    {"id": "early", "role": "svc-early"},
    {"id": "stack", "role": "svc-stack"},
    {"id": "late", "role": "svc-late"},
    {"id": "idle", "role": "svc-idle"},
]
SERVER = (
    {"role": "web-app-x", "app": "web-app-x"},
    {"role": "web-app-y", "app": "web-app-y"},
    {"role": "web-app-z", "app": "web-app-z"},
)


def _farm(root: Path, bridged: dict[str, str]) -> None:
    """Args:
    root: an empty directory that becomes the roles directory.
    bridged: the roles that ship a bridge, each with its meta/services.yml text.
    """
    canonical = read_text(str(PROJECT_ROOT / "roles" / CANONICAL_BRIDGE))
    (root / CANONICAL_BRIDGE).parent.mkdir(parents=True)
    (root / CANONICAL_BRIDGE).write_text(canonical)
    for role, meta in bridged.items():
        (root / role / BRIDGE).parent.mkdir(parents=True)
        (root / role / BRIDGE).write_text(canonical)
        (root / role / STACK_META).parent.mkdir(parents=True)
        (root / role / STACK_META).write_text(meta)


def _plan(root: Path, closure: list[str], group_names: list[str]) -> list[dict]:
    """Args:
        root: the farm roles directory.
        closure: the deployment whitelist's dependency closure.
        group_names: the inventory groups of the current host.

    Returns:
        the plan of the farm with one server group holding SERVER.
    """
    with (
        patch("plugins.lookup.stack_batch.stage_groups", return_value=["web-app"]),
        patch("plugins.lookup.stack_batch.ordered_roles", return_value=SERVER),
    ):
        return plan(
            root,
            SERVICES,
            ["late"],
            closure,
            group_names,
            {"web-app-x": ["h"], "web-app-y": ["h"]},
            [],
            tls_mode=lambda app: "letsencrypt" if app.startswith("web-") else "off",
        )


class TestStackBatchPlan(unittest.TestCase):
    def test_the_tree_plans_every_bridged_role_once_and_admits_it(self) -> None:
        roles_dir = PROJECT_ROOT / "roles"
        bridged = [
            path.relative_to(roles_dir).parts[0]
            for path in roles_dir.glob(f"*/{BRIDGE}")
        ]
        ordered = ordered_primary_service_entries(
            build_service_registry_from_roles_dir(roles_dir), roles_dir
        )
        server = [
            entry["app"]
            for group in stage_groups("server")
            for entry in ordered_roles(str(roles_dir), group)
        ]
        everything = [entry["role"] for entry in ordered] + server
        planned = plan(
            roles_dir,
            ordered,
            [entry["id"] for entry in ordered],
            [],
            everything,
            {role: ["h"] for role in everything},
            [],
            tls_mode=lambda _app: "off",
        )
        self.assertTrue(bridged)
        self.assertCountEqual([entry["role"] for entry in planned], bridged)
        self.assertEqual([entry for entry in planned if entry["errors"]], [])

    def test_only_bridged_roles_entered_after_the_stack_slot_are_planned(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _farm(
                root,
                dict.fromkeys(
                    ["svc-early", "svc-late", "svc-idle", "web-app-x", "web-app-y"],
                    LITERAL_STACK,
                ),
            )
            planned = _plan(root, [], ["web-app-x"])
        self.assertEqual(
            [
                (item["id"], item["phase"], item["tls_mode"], item["errors"])
                for item in planned
            ],
            [
                ("svc-late", "preload", "off", []),
                ("web-app-x", "server", "letsencrypt", []),
            ],
        )

    def test_a_preloaded_service_that_is_also_a_server_role_is_planned_once(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _farm(root, {"svc-late": LITERAL_STACK})
            with (
                patch("plugins.lookup.stack_batch.stage_groups", return_value=["svc"]),
                patch(
                    "plugins.lookup.stack_batch.ordered_roles",
                    return_value=({"role": "svc-late", "app": "svc-late"},),
                ),
            ):
                planned = plan(
                    root,
                    SERVICES,
                    ["late"],
                    [],
                    ["svc-late"],
                    {"svc-late": ["h"]},
                    [],
                    tls_mode=lambda _app: "off",
                )
        self.assertEqual(
            [(item["id"], item["phase"]) for item in planned],
            [("svc-late", "preload")],
        )

    def test_the_whitelist_closure_scopes_the_preload_part(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _farm(root, {"svc-late": LITERAL_STACK})
            planned = _plan(root, ["web-app-x"], [])
        self.assertEqual(planned, [])

    def test_every_reason_a_planned_role_cannot_join_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _farm(root, {"svc-late": '---\nstack:\n  enabled: "{{ true }}"\n'})
            (root / "svc-late" / BRIDGE).write_text("---\n[]\n")
            planned = _plan(root, [], [])
        self.assertEqual(len(planned), 1)
        self.assertEqual(len(planned[0]["errors"]), 2)


class TestStackBatchLookup(unittest.TestCase):
    def test_the_lookup_feeds_the_loader_inputs_into_the_plan(self) -> None:
        answers = {
            "service": [{"id": "late", "required": True}, {"id": "idle"}],
            "deployment": [{"whitelist": ["web-app-x"]}],
            "application_closure": [["web-app-x", "svc-late"]],
            "domains": [{"web-app-x": ["x.example"]}],
            "tls": ["letsencrypt"],
        }
        calls = []

        def get(name, **_kwargs):
            def run(terms, variables=None, **kwargs):
                calls.append((name, terms, kwargs))
                return answers[name]

            return MagicMock(run=run)

        variables = {"group_names": ["web-app-x"], "groups": {"web-app-x": ["h"]}}
        lookup = LookupModule()
        with (
            patch("plugins.lookup.stack_batch.lookup_loader") as loader,
            patch("plugins.lookup.stack_batch.plan", return_value=[]) as planned,
        ):
            loader.get.side_effect = get
            self.assertEqual(lookup.run([], variables=variables), [[]])
            tls_mode = planned.call_args.kwargs["tls_mode"]
            modes = (tls_mode("web-app-x"), tls_mode("svc-late"))
        _, ordered, required, closure, group_names, groups, whitelist = (
            planned.call_args.args
        )
        self.assertEqual(
            next(terms for name, terms, _ in calls if name == "service"),
            [[entry["id"] for entry in ordered]],
        )
        self.assertEqual(
            (required, closure, group_names, groups, whitelist),
            (
                ["late"],
                ["web-app-x", "svc-late"],
                ["web-app-x"],
                {"web-app-x": ["h"]},
                ["web-app-x"],
            ),
        )
        self.assertEqual(modes, ("letsencrypt", "off"))
        self.assertIn(("tls", ["web-app-x", "mode"], {}), calls)
        self.assertNotIn("svc-late", [call[1][0] for call in calls if call[0] == "tls"])

    def test_one_application_id_yields_its_late_item_without_a_plan(self) -> None:
        answers = {"domains": [{"web-app-x": ["x.example"]}], "tls": ["letsencrypt"]}
        calls = []

        def get(name, **_kwargs):
            def run(terms, variables=None, **kwargs):
                calls.append(name)
                return answers[name]

            return MagicMock(run=run)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _farm(root, {"web-app-x": '---\nstack:\n  enabled: "{{ true }}"\n'})
            with (
                patch("plugins.lookup.stack_batch.lookup_loader") as loader,
                patch("plugins.lookup.stack_batch.plan") as planned,
            ):
                loader.get.side_effect = get
                late = LookupModule().run(
                    ["web-app-x"], variables={}, role="web-app-x", roles_dir=str(root)
                )
        self.assertEqual(
            [
                {**item, "errors": len(item["errors"])}
                for batch in late
                for item in batch
            ],
            [
                {
                    "id": "web-app-x",
                    "role": "web-app-x",
                    "phase": "late",
                    "tls_mode": "letsencrypt",
                    "errors": 1,
                }
            ],
        )
        planned.assert_not_called()
        self.assertEqual(calls, ["domains", "tls"])


if __name__ == "__main__":
    unittest.main()
