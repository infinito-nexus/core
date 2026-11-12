# nocheck: workflow-references  fixture workflow names, not real files
from __future__ import annotations

import copy
import unittest

from cli.meta.ci.iterate import plan
from cli.meta.ci.iterate.classify import DOC_SEED, FULL, NONE, SEED, TESTS, Change
from utils.roles.mapping import (
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_PLAYWRIGHT_SPEC,
    ROLE_FILE_TASKS_MAIN,
)

from ._catalog_fixture import ROLES, FakeCatalog


def _build(changes, catalog=None, **options):
    values = {"loop": "", "disable": "", "timings": ""}
    values.update(options)
    return plan.build(
        [c.path for c in changes], changes, catalog or FakeCatalog(), **values
    )


def _seed(path, role):
    return Change(path, "role", SEED, (role,), (), "role file")


def _task(role):
    return _seed(f"roles/{role}/{ROLE_FILE_TASKS_MAIN}", role)


def _rows(result, tier):
    return [r for r in result["rows"] if r["tier"] == tier]


class TestRoleSeed(unittest.TestCase):
    def setUp(self) -> None:
        self.result = _build([_task("web-app-light")])

    def test_inner_loop_syncs_the_role(self) -> None:
        self.assertEqual(
            [r["command"] for r in _rows(self.result, "T1")],
            ["make compose-role-sync role=web-app-light"],
        )

    def test_pre_push_takes_the_gate_and_every_swarm_variant(self) -> None:
        self.assertEqual(
            [(r["deploy"], r["mode"]) for r in _rows(self.result, "T2")],
            [("gate", "compose"), ("zombie", "swarm")],
        )

    def test_swarm_row_pins_multi(self) -> None:
        self.assertEqual(self.result["network"], {"web-app-light#0": "multi"})

    def test_whitelist_is_the_closure(self) -> None:
        self.assertEqual(self.result["tiers"]["T3"]["whitelist"], "web-app-light")

    def test_default_disable_is_proposed(self) -> None:
        self.assertEqual(self.result["disable"], list(plan.DEFAULT_DISABLE))

    def test_role_unit_tests_run_in_t0(self) -> None:
        self.assertEqual(
            self.result["tiers"]["T0"]["tests"],
            ["tests/unit/python/roles/web-app-light"],
        )

    def test_footprint_fits(self) -> None:
        self.assertEqual(
            {e["verdict"] for e in self.result["footprint"]["tiers"].values()}, {"fits"}
        )

    def test_no_role_is_cut_from_every_tier(self) -> None:
        self.assertFalse([c for c in self.result["cuts"] if c["tier"] == "all"])


class TestUnitTier(unittest.TestCase):
    EXTERNAL = "tests/external/update/test_pins.py"
    UNIT = "tests/unit/python/utils/test_x.py"

    def setUp(self) -> None:
        change = Change(
            "utils/x.py", "module", TESTS, (), (self.EXTERNAL, self.UNIT), "module"
        )
        self.result = _build([change])

    def test_file_inside_a_listed_directory_is_dropped(self) -> None:
        folder = "tests/unit/python/utils"
        change = Change("utils/x.py", "module", TESTS, (), (folder, self.UNIT), "m")
        self.assertEqual(
            _build([change])["tiers"]["T0"]["commands"][0], plan.PYTEST + folder
        )

    def test_pytest_runs_the_unit_test_in_importlib_mode(self) -> None:
        self.assertEqual(
            self.result["tiers"]["T0"]["commands"][0],
            f"PYTHONPATH=. python3 -m pytest --import-mode=importlib -q {self.UNIT}",
        )

    def test_external_test_is_cut_to_the_opt_in_suite(self) -> None:
        cut = next(c for c in self.result["cuts"] if c["reason"] == plan.EXTERNAL_CUT)
        self.assertEqual(cut["paths"], {self.EXTERNAL: "opt-in live test"})

    def test_negative_control_no_external_test_no_external_cut(self) -> None:
        change = Change("utils/x.py", "module", TESTS, (), (self.UNIT,), "module")
        reasons = {c["reason"] for c in _build([change])["cuts"]}
        self.assertNotIn(plan.EXTERNAL_CUT, reasons)

    def test_deleted_test_runs_its_directory(self) -> None:
        gone = "tests/unit/python/utils/test_gone.py"
        catalog = FakeCatalog()
        catalog.exists = lambda path: path != gone
        change = Change(gone, "test", TESTS, (), (gone,), "test")
        self.assertEqual(
            _build([change], catalog)["tiers"]["T0"]["tests"],
            ["tests/unit/python/utils"],
        )

    def test_negative_control_present_test_runs_itself(self) -> None:
        self.assertIn(self.UNIT, self.result["tiers"]["T0"]["tests"])

    def test_tooling_target_is_listed_and_not_run(self) -> None:
        change = Change(
            "cli/x.py", "tooling", TESTS, (), (), "t", targets=("lint-markdown",)
        )
        t0 = _build([change])["tiers"]["T0"]
        self.assertEqual(t0["targets"], ["make lint-markdown"])
        self.assertNotIn("make lint-markdown", t0["commands"])

    def test_unconsumed_tooling_path_is_a_named_cut(self) -> None:
        change = Change("scripts/lint/x.sh", "tooling", NONE, reason="no role")
        cut = next(
            c for c in _build([change])["cuts"] if c["reason"] == plan.UNCHECKED_CUT
        )
        self.assertEqual(cut["paths"], {"scripts/lint/x.sh": "no role"})

    def test_negative_control_format_only_tooling_path_is_no_cut(self) -> None:
        change = Change("cli/x.py", "tooling", NONE, format_only=True)
        reasons = {c["reason"] for c in _build([change])["cuts"]}
        self.assertNotIn(plan.UNCHECKED_CUT, reasons)


class TestLintKey(unittest.TestCase):
    def test_every_linted_kind_maps_to_its_target(self) -> None:
        cases = {
            ".github/workflows/x.yml": "make lint-action",
            "Makefile": "make lint-makefile",
            "roles/r/files/Dockerfile": "make lint-dockerfile",
            f"roles/r/{ROLE_FILE_TASKS_MAIN}": "make lint-ansible",
        }
        for path, target in cases.items():
            with self.subTest(path=path):
                self.assertEqual(plan.LINTERS[plan.lint_key(path)], (target,))

    def test_negative_control_template_has_no_linter(self) -> None:
        self.assertEqual(plan.lint_key("roles/r/templates/x.conf.j2"), "")


class TestProviderSeed(unittest.TestCase):
    def setUp(self) -> None:
        self.result = _build([_task("svc-db-store")])

    def test_lightest_consumer_hosts_the_inner_loop(self) -> None:
        self.assertEqual(
            [r["app"] for r in _rows(self.result, "T1")], ["web-app-light"]
        )

    def test_variant_narrowed_consumer_stays_in_the_whitelist(self) -> None:
        self.assertIn(
            "web-app-multi#1", self.result["tiers"]["T3"]["whitelist"].split()
        )

    def test_consumers_without_a_local_row_are_cut_to_t3(self) -> None:
        local = [c for c in self.result["cuts"] if c["tier"] == "local"]
        self.assertEqual(local[0]["roles"], ["web-app-heavy", "web-app-multi"])

    def test_hosted_compose_row_is_a_pinned_reinstall(self) -> None:
        compose = [r for r in _rows(self.result, "T2") if r["mode"] == "compose"]
        self.assertEqual(compose[0]["deploy"], "reinstall")


class TestFullSet(unittest.TestCase):
    def setUp(self) -> None:
        self.result = _build(
            [Change("Makefile", "unknown", FULL, reason="unknown path")]
        )

    def test_whitelist_is_all(self) -> None:
        self.assertEqual(self.result["tiers"]["T3"]["whitelist"], plan.ALL)

    def test_inner_loop_takes_the_cheapest_base_cluster_row(self) -> None:
        self.assertEqual(
            [r["app"] for r in _rows(self.result, "T1")], ["web-app-light"]
        )

    def test_pre_push_is_the_roundtrip(self) -> None:
        self.assertEqual([r["deploy"] for r in _rows(self.result, "T2")], ["roundtrip"])

    def test_roundtrip_variant_limit_is_named(self) -> None:
        self.assertTrue(
            any("variant 0 only" in c["reason"] for c in self.result["cuts"])
        )

    def test_every_role_is_accounted(self) -> None:
        self.assertEqual(plan.accounted(self.result), set(ROLES))


class TestNarrowing(unittest.TestCase):
    def setUp(self) -> None:
        self.change = Change(
            "plugins/lookup/x.py",
            "plugin",
            NONE,
            reason="format-only",
            format_only=True,
        )
        self.result = _build([self.change])

    def test_format_only_plugin_runs_no_deploy(self) -> None:
        self.assertEqual((self.result["rows"], self.result["loop"]), ([], "none"))

    def test_every_role_the_baseline_widens_to_is_cut_by_name(self) -> None:
        cut = next(c for c in self.result["cuts"] if c["tier"] == "all")
        self.assertEqual(
            (cut["roles"], cut["paths"]),
            (list(ROLES), {"plugins/lookup/x.py": "format-only"}),
        )

    def test_baseline_is_accounted(self) -> None:
        self.assertLessEqual(
            set(self.result["baseline"]["roles"]), plan.accounted(self.result)
        )

    def test_negative_control_a_silently_dropped_role_is_not_accounted(self) -> None:
        broken = copy.deepcopy(self.result)
        next(c for c in broken["cuts"] if c["tier"] == "all")["roles"].remove(
            "web-app-heavy"
        )
        self.assertNotIn("web-app-heavy", plan.accounted(broken))

    def test_document_seed_cuts_its_consumers(self) -> None:
        result = _build(
            [
                Change(
                    "roles/svc-db-store/README.md",
                    "role",
                    DOC_SEED,
                    ("svc-db-store",),
                    (),
                    "role document",
                )
            ]
        )
        cut = next(c for c in result["cuts"] if c["tier"] == "all")
        self.assertEqual(
            cut["roles"], ["web-app-heavy", "web-app-light", "web-app-multi"]
        )


class TestDisableAndLoop(unittest.TestCase):
    def test_seed_provider_key_stays_on(self) -> None:
        result = _build([_task("web-app-matomo")])
        self.assertNotIn("matomo", result["disable"])
        self.assertIn("matomo", result["kept"])

    def test_none_disables_nothing(self) -> None:
        result = _build(
            [_task("web-app-light")],
            disable="none",
        )
        self.assertEqual(result["disable"], [])

    def test_spec_only_diff_takes_the_playwright_loop(self) -> None:
        result = _build(
            [_seed(f"roles/web-app-light/{ROLE_FILE_PLAYWRIGHT_SPEC}", "web-app-light")]
        )
        self.assertEqual(
            (result["loop"], _rows(result, "T1")[0]["command"]),
            ("playwright", "make compose-playwright role=web-app-light"),
        )

    def test_swarm_loop_takes_zombie_rows(self) -> None:
        result = _build([_task("web-app-light")], loop="swarm")
        self.assertEqual(_rows(result, "T1")[0]["deploy"], "zombie")

    def test_inventory_file_takes_a_reinstall(self) -> None:
        result = _build(
            [_seed(f"roles/web-app-multi/{ROLE_FILE_META_VARIANTS}", "web-app-multi")]
        )
        self.assertEqual(result["mode"], "reinstall")

    def test_host_only_role_is_cut_with_its_reason(self) -> None:
        result = _build([_task("dsk-tool")])
        reasons = {c["reason"] for c in result["cuts"] if c["tier"] == "T1"}
        self.assertEqual(
            reasons, {"CI tests dsk-tool on a host only, which no local loop deploys"}
        )

    def test_refused_seed_widens_to_the_full_set(self) -> None:
        catalog = FakeCatalog()
        catalog.refuse = frozenset({"web-app-light"})
        result = _build([_task("web-app-light")], catalog)
        self.assertEqual(result["tiers"]["T3"]["whitelist"], plan.ALL)


class TestBaselineRule(unittest.TestCase):
    def test_empty_diff_widens(self) -> None:
        self.assertTrue(plan.baseline_widens([]))

    def test_role_documents_and_tests_do_not_widen(self) -> None:
        self.assertFalse(
            plan.baseline_widens(["roles/a/x.yml", "docs/a.md", "tests/unit/x.py"])
        )

    def test_any_other_path_widens(self) -> None:
        self.assertTrue(plan.baseline_widens(["roles/a/x.yml", "utils/x.py"]))

    def test_a_file_directly_under_roles_widens(self) -> None:
        self.assertTrue(plan.baseline_widens(["roles/x.yml"]))

    def test_diff_without_role_seeds_widens_the_baseline(self) -> None:
        change = Change(
            "tests/unit/x/test_y.py", "test", TESTS, tests=("tests/unit/x/test_y.py",)
        )
        result = _build([change])
        self.assertEqual(
            (result["baseline"]["roles"], result["tiers"]["T3"]["push_widens"]),
            (list(ROLES), True),
        )

    def test_a_role_test_seeds_the_baseline_like_the_script(self) -> None:
        path = "tests/unit/python/roles/web-app-light/files/test_y.py"
        change = Change(path, "test", TESTS, tests=(path,))
        result = _build([change])
        self.assertEqual(
            (result["baseline"]["roles"], result["tiers"]["T3"]["push_widens"]),
            (["web-app-light"], False),
        )

    def test_seeded_role_reads_the_first_roles_segment_of_a_test(self) -> None:
        roles = frozenset(ROLES)
        cases = {
            "tests/unit/python/roles/web-app-light/test_x.py": "web-app-light",
            "tests/lint/ansible/roles/meta/test_x.py": "",
            "tests/unit/python/utils/roles/test_mapping.py": "",
            f"roles/web-app-light/{ROLE_FILE_TASKS_MAIN}": "",
        }
        for path, role in cases.items():
            with self.subTest(path=path):
                self.assertEqual(plan.seeded_role(path, roles), role)

    def test_negative_control_a_role_seed_keeps_the_baseline_narrow(self) -> None:
        result = _build([_task("web-app-light")])
        self.assertEqual(
            (result["baseline"]["roles"], result["tiers"]["T3"]["push_widens"]),
            (["web-app-light"], False),
        )

    def test_a_test_under_a_role_seeds_that_role(self) -> None:
        path = "tests/unit/python/roles/web-app-light/test_y.py"
        change = Change(path, "test", TESTS, tests=(path,))
        self.assertEqual(_build([change])["baseline"]["roles"], ["web-app-light"])

    def test_negative_control_a_roles_dir_naming_no_role_widens(self) -> None:
        path = "tests/integration/roles/meta/test_y.py"
        change = Change(path, "test", TESTS, tests=(path,))
        self.assertEqual(_build([change])["baseline"]["roles"], list(ROLES))


if __name__ == "__main__":
    unittest.main()
