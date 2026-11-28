"""Unit test: the designer, implementer and compose loop routine decision nodes
route on parsed evidence and default to their forward branch when the evidence
is absent; the compose loop reaches done only through the reinstall final gate,
after the mode=update redeploy or a full_cycle reinstall, and every red
redeploy enters the red chain."""

from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

from agents.routines import design, implementer
from agents.routines.iterate import compose
from tests.unit.python.agents.routines import written_text
from utils.roles.mapping import (
    ROLE_FILE_META_CSP,
    ROLE_FILE_META_DOMAINS,
    ROLE_FILE_META_INFO,
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_MCP,
    ROLE_FILE_META_NETWORKS,
    ROLE_FILE_META_RBAC,
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_TESTS,
    ROLE_FILE_META_USERS,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_TASKS_MAIN,
)

_HAVE_LANGGRAPH = importlib.util.find_spec("langgraph") is not None

_ROLE = "web-app-gitea"
_ROLE_TASKS_MAIN = f"roles/{_ROLE}/{ROLE_FILE_TASKS_MAIN}"
_INVENTORY_FILES = {
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_META_USERS,
}
_OUTSIDE_SYNC_FILES = {
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_INFO,
    ROLE_FILE_META_NETWORKS,
    ROLE_FILE_META_DOMAINS,
    ROLE_FILE_META_RBAC,
    ROLE_FILE_META_MCP,
    ROLE_FILE_META_TESTS,
    "templates/test.env.j2",
}
_OUTSIDE_SYNC_DIRS = ("files/test/",)
_ROLE_LOCAL = (
    _ROLE_TASKS_MAIN,
    f"roles/{_ROLE}/templates/app.ini.j2",
    f"roles/{_ROLE}/files/javascript.js",
    f"roles/{_ROLE}/{ROLE_FILE_META_CSP}",
    f"roles/{_ROLE}/README.md",
    f"tests/unit/python/roles/{_ROLE}/test_app_ini.py",
    f"tests/unit/javascript/roles/{_ROLE}/test_javascript.js",
    "docs/contributing/actions/deploy.md",
    "README.md",
)
_NEEDS_UPDATE = (
    *(f"roles/{_ROLE}/{inner}" for inner in sorted(_OUTSIDE_SYNC_FILES)),
    *(f"roles/{_ROLE}/{inner}test.sh" for inner in _OUTSIDE_SYNC_DIRS),
    f"roles/svc-db-postgres/{ROLE_FILE_TASKS_MAIN}",
    "roles/svc-db-postgres/README.md",
    f"roles/web-app-gitea-runner/{ROLE_FILE_TASKS_MAIN}",
    "group_vars/all/00_general.yml",
    "inventories/localhost/devices.yml",
    "plugins/lookup/applications.py",
    "utils/cache/applications.py",
    "tasks/utils/sync/role.yml",
)
_NEEDS_REBUILD = (
    *(f"roles/{_ROLE}/{inner}" for inner in sorted(_INVENTORY_FILES)),
    *(f"roles/svc-db-postgres/{inner}" for inner in sorted(_INVENTORY_FILES)),
)
_BARE_VARIANT = re.compile(r"(?<!\[)variant=<idx>")
_JUNIT_RED = (
    '<testsuite><testcase name="t"><failure message="x">boom</failure>'
    "</testcase></testsuite>"
)


class TestDesignerDecisions(unittest.TestCase):
    def test_spec_green_reads_junit(self) -> None:
        self.assertEqual(design._spec_green({"junit_xml": _JUNIT_RED})["D3"], "❌ red")
        self.assertEqual(design._spec_green({})["D3"], "✅ green")

    def test_negative_control_passes_only_red_then_green(self) -> None:
        passed = design._negative_control(
            {"nc_before_red": True, "nc_after_green": True}
        )
        self.assertEqual(passed["D4"], "✅ turns red")
        failed = design._negative_control(
            {"nc_before_red": False, "nc_after_green": True}
        )
        self.assertEqual(failed["D4"], "❌ stays green")
        self.assertEqual(design._negative_control({})["D4"], "✅ turns red")


class TestImplementerDecisions(unittest.TestCase):
    def test_gate_reads_the_table(self) -> None:
        self.assertEqual(
            implementer._gate({"gate_output": "FAILED TARGETS: x"})["D2"], "❌ red"
        )
        self.assertEqual(implementer._gate({})["D2"], "✅ green")

    def test_watch_flags_a_red_app(self) -> None:
        self.assertEqual(implementer._watch({"app_red": True})["D4"], "🔴 app red")
        self.assertEqual(implementer._watch({})["D4"], "🟢 all green")


def _steps() -> dict:
    return {step.id: step for step in compose.STEPS}


def _targets(step) -> set[str]:
    return ({step.nxt} if step.nxt else set()) | {t for _, t in step.branches}


def _into(target: str) -> set[str]:
    return {sid for sid, step in _steps().items() if target in _targets(step)}


class TestIterateComposeDecisions(unittest.TestCase):
    def test_routed_role_files_are_pinned(self) -> None:
        self.assertEqual(set(compose._INVENTORY_FILES), _INVENTORY_FILES)
        self.assertEqual(set(compose._OUTSIDE_SYNC_FILES), _OUTSIDE_SYNC_FILES)
        self.assertEqual(compose._OUTSIDE_SYNC_DIRS, _OUTSIDE_SYNC_DIRS)

    def test_role_local_fix_takes_the_role_sync(self) -> None:
        self.assertEqual(
            compose.redeploy_target(_ROLE, list(_ROLE_LOCAL)), compose.ROLE_SYNC
        )

    def test_any_shared_path_keeps_mode_update(self) -> None:
        for path in _NEEDS_UPDATE:
            with self.subTest(path=path):
                self.assertEqual(
                    compose.redeploy_target(_ROLE, [*_ROLE_LOCAL, path]),
                    compose.UPDATE,
                )

    def test_inventory_baked_file_rebuilds_the_inventory(self) -> None:
        for path in _NEEDS_REBUILD:
            with self.subTest(path=path):
                self.assertEqual(
                    compose.redeploy_target(
                        _ROLE, [*_ROLE_LOCAL, *_NEEDS_UPDATE, path]
                    ),
                    compose.REBUILD,
                )

    def test_unknown_diff_keeps_mode_update(self) -> None:
        self.assertEqual(compose.redeploy_target(_ROLE, []), compose.UPDATE)
        self.assertEqual(
            compose.redeploy_target(_ROLE, [f"tests/unit/python/roles/{_ROLE}/x.py"]),
            compose.UPDATE,
        )
        self.assertEqual(
            compose.redeploy_target("", [_ROLE_TASKS_MAIN]),
            compose.UPDATE,
        )

    def test_scope_node_writes_its_branch(self) -> None:
        node = _steps()["scope"]
        self.assertEqual(node.kind, "decision")
        self.assertEqual(
            dict(node.branches),
            {
                compose.UPDATE: "redeploy",
                compose.ROLE_SYNC: "sync",
                compose.REBUILD: "rebuild",
            },
        )
        self.assertEqual(node.branches[0][0], compose.UPDATE)
        state = {"role": _ROLE, "changed_paths": [_ROLE_TASKS_MAIN]}
        self.assertEqual(node.fn(dict(state))["scope"], compose.ROLE_SYNC)
        self.assertEqual(node.fn({})["scope"], compose.UPDATE)

    def test_a_sync_limit_ends_the_role_sync_for_the_loop(self) -> None:
        node = _steps()["scope"]
        local = {"role": _ROLE, "changed_paths": [_ROLE_TASKS_MAIN]}
        limited = node.fn({**local, "sync": compose.SYNC_LIMIT})
        self.assertEqual(limited["scope"], compose.UPDATE)
        red = node.fn({**local, "sync": "❌ red"})
        self.assertEqual(red["scope"], compose.ROLE_SYNC)
        baked = {
            "role": _ROLE,
            "changed_paths": [f"roles/{_ROLE}/{ROLE_FILE_META_VARIANTS}"],
        }
        self.assertEqual(
            node.fn({**baked, "sync": compose.SYNC_LIMIT})["scope"], compose.REBUILD
        )

    def test_sync_names_the_target_and_has_an_escape(self) -> None:
        sync = _steps()["sync"]
        self.assertIn("make compose-role-sync role=<role> [variant=<idx>]", sync.label)
        self.assertEqual(
            dict(sync.branches),
            {
                "✅ green": "redeploy",
                "❌ red": "hung",
                compose.SYNC_LIMIT: "redeploy",
                "⏳ running": "hung",
            },
        )

    def test_rebuild_reinstalls_then_gates(self) -> None:
        rebuild = _steps()["rebuild"]
        self.assertIn(
            "make compose-deploy mode=reinstall apps=<roles> full_cycle=true [variant=<idx>]",
            rebuild.label,
        )
        self.assertEqual(
            dict(rebuild.branches),
            {"✅ green": "gate", "❌ red": "hung", "⏳ running": "hung"},
        )

    def test_scope_names_the_sync_limit_fallback(self) -> None:
        self.assertIn("(after a sync limit: mode=update)", _steps()["scope"].label)

    def test_variant_stays_optional_in_every_label(self) -> None:
        for step in compose.STEPS:
            with self.subTest(step=step.id):
                self.assertIsNone(_BARE_VARIANT.search(step.label))

    def test_unit_tests_run_before_any_deploy(self) -> None:
        order = [step.id for step in compose.STEPS]
        self.assertEqual(order[0], "unit")
        self.assertIn("tests/unit/*/roles/<role>/", compose.STEPS[0].label)
        self.assertNotIn("compose-", compose.STEPS[0].label)

    def test_done_only_after_an_update_pass_and_the_final_gate(self) -> None:
        steps = _steps()
        self.assertEqual(_into("done"), {"tune_design"})
        self.assertEqual(_into("tune_design"), {"tune_velocity"})
        self.assertEqual(_into("tune_velocity"), {"gate"})
        self.assertEqual(_into("gate"), {"redeploy", "rebuild", "wait"})
        self.assertEqual(_into("redeploy"), {"scope", "sync", "wait"})
        self.assertIn(
            "make test, then make compose-deploy mode=update apps=<roles> [variant=<idx>]",
            steps["redeploy"].label,
        )
        self.assertEqual(
            dict(steps["redeploy"].branches),
            {"✅ green": "gate", "❌ red": "hung", "⏳ running": "hung"},
        )
        self.assertIn(
            "make compose-deploy mode=reinstall apps=<roles> full_cycle=true (no variant)",
            steps["gate"].label,
        )
        self.assertEqual(
            dict(steps["gate"].branches),
            {"✅ green": "tune_velocity", "❌ red": "hung", "⏳ running": "hung"},
        )
        self.assertEqual(steps["done"].kind, "terminal")

    def test_the_relevant_delta_decides_before_the_scope(self) -> None:
        self.assertEqual(_steps()["verify"].nxt, "relevant_delta")
        self.assertEqual(_into("scope"), {"relevant_delta"})

    def test_scope_records_its_decision_in_the_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            compose._scope({"ledger": str(ledger), "role": _ROLE})
            (line,) = written_text(ledger).splitlines()
        self.assertEqual(json.loads(line)["outcome"], compose.UPDATE)

    @unittest.skipUnless(
        _HAVE_LANGGRAPH,
        "langgraph ships in the orchestrator image, not the sandbox venv",
    )
    def test_stub_run_takes_mode_update(self) -> None:
        self.assertEqual(compose.build().invoke({})["scope"], compose.UPDATE)


if __name__ == "__main__":
    unittest.main()
