from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar

from cli.meta.ci.iterate import __main__ as entry
from cli.meta.ci.iterate import diff, plan, tiers
from cli.meta.ci.iterate.catalog import Catalog
from cli.meta.ci.iterate.classify import FULL, NONE, SEED, classify
from cli.meta.ci.iterate.symbols import Index
from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_VARS_MAIN,
)
from utils.tests.buckets import buckets, register

SAMPLE = {
    "8d6040948c": "provider role template plus its unit test",
    "8ce4934dab": "role meta/services.yml image pin, 201 consumers",
    "c95ed5ca9c": "role README only",
    "d601adbf9e": "two roles, a root TODO.md and a lint test",
    "bf1b1f2769": "shared lookup plugin plus a role template",
    "f52da1c875": "group_vars key plus two roles",
    "c068e44d1b": "shared utils module plus its unit test",
    "1c561a1e7d": "unit test only",
    "2d7bf740b0": "workflow, runner scripts and a utils module",
    "d965f00041": "Makefile, .dockerignore and .gitignore",
    "92ddeb0750": "scripts/meta/resolve/image/ci.sh only, the image of every CI deploy",
    "8a29ba0bfd": "three cli/contributing/mirror package __main__ files",
}
WIDENS = ("92ddeb0750", "8a29ba0bfd")
TESTS_ONLY = "1c561a1e7d"
ROLE_ONLY = "8ce4934dab"
SCRIPTS = (
    "scripts/meta/resolve/diff/affected_roles.sh",
    "scripts/meta/resolve/baseline_remote.sh",
)
STUB = """#!/usr/bin/env bash
case "$1" in
fetch) exit 0 ;;
merge-base) printf '%s\\n' "$STUB_BASE" ;;
diff) cat "$STUB_PATHS" ;;
*) exec {git} "$@" ;;
esac
"""
CONTROLLED = (TESTS_ONLY, ROLE_ONLY, *WIDENS)
PLAN_BUCKETS = (
    CONTROLLED,
    *buckets([sha for sha in SAMPLE if sha not in CONTROLLED], 3),
)
KEYCLOAK_VARS = f"roles/web-app-keycloak/{ROLE_FILE_VARS_MAIN}"
DASHBOARD_VARIANTS = f"roles/web-app-dashboard/{ROLE_FILE_META_VARIANTS}"
JOB_NAMES_TESTS = tuple(
    f"tests/unit/python/cli/administration/deploy/ci/test_{name}.py"
    for name in ("trigger", "status", "runs", "selections", "timings")
)


class _Script:
    def __init__(self, root: Path) -> None:
        self.root = root
        for rel in SCRIPTS:
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_ROOT / rel, target)
        (root / "roles").symlink_to(PROJECT_ROOT / "roles")
        stub = root / "bin" / "git"
        stub.parent.mkdir()
        stub.write_text(STUB.format(git=shutil.which("git")), encoding="utf-8")
        stub.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if k != "GITHUB_REPOSITORY"}
        self.env.update(
            PATH=f"{stub.parent}{os.pathsep}{os.environ['PATH']}",
            PYTHON=sys.executable,
            PYTHONPATH=str(PROJECT_ROOT),
        )

    def tokens(self, base: str, paths: list[str]) -> list[str]:
        listing = self.root / f"paths-{base}"
        listing.write_text("".join(f"{p}\n" for p in paths), encoding="utf-8")
        result = subprocess.run(
            [shutil.which("bash"), str(self.root / SCRIPTS[0])],
            env={**self.env, "STUB_BASE": base, "STUB_PATHS": str(listing)},
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.split()


def _seeds_dropped(path, read, index, exists):
    change = classify(path, read, index, exists)
    if change.effect == SEED and path.startswith("roles/"):
        return change._replace(effect=NONE, roles=(), reason="mutant narrowing")
    return change


def _read(old: str, new: str):
    return lambda path: (old, new)


def _pin_edit() -> tuple[str, str]:
    old = read_text(str(PROJECT_ROOT / DASHBOARD_VARIANTS))
    return old, old.replace("web-app-matomo#reciprocal", "web-app-matomo#0")


def _exists(path: str) -> bool:
    return (PROJECT_ROOT / path).exists()


class TestRealPathsReachTheirConsumers(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = Index(PROJECT_ROOT)

    def _classify(self, path: str, old: str, new: str):
        return classify(path, _read(old, new), self.index, _exists)

    def test_package_main_run_by_python_m_widens(self) -> None:
        for path in (
            "cli/contributing/mirror/resolver/__main__.py",
            "cli/meta/ci/validate/__main__.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    self._classify(path, "x = 1\n", "x = 2\n").effect, FULL
                )

    def test_resolve_script_widens(self) -> None:
        for path in (
            "scripts/meta/resolve/image/ci.sh",
            "scripts/meta/resolve/apps.sh",
        ):
            with self.subTest(path=path):
                self.assertEqual(self._classify(path, "a\n", "b\n").effect, FULL)

    def test_type_swap_in_a_role_seeds_the_role(self) -> None:
        change = self._classify(KEYCLOAK_VARS, "x: 1\n", "x: true\n")
        self.assertEqual((change.effect, change.roles), (SEED, ("web-app-keycloak",)))

    def test_retargeted_variant_pin_seeds_the_role(self) -> None:
        old, new = _pin_edit()
        change = self._classify(DASHBOARD_VARIANTS, old, new)
        self.assertEqual((change.effect, change.roles), (SEED, ("web-app-dashboard",)))

    def test_shared_test_helper_runs_its_importers(self) -> None:
        change = self._classify("tests/utils/ci/job_names.py", "x = 1\n", "x = 2\n")
        self.assertLessEqual(set(JOB_NAMES_TESTS), set(change.tests))

    def test_script_a_test_builds_from_segments_runs_that_test(self) -> None:
        change = self._classify("scripts/github/split_runner_apps.sh", "a\n", "b\n")
        self.assertIn(
            "tests/unit/python/cli/gha/test_split_runner_apps.py", change.tests
        )

    def test_negative_control_respaced_role_value_is_format_only(self) -> None:
        change = self._classify(KEYCLOAK_VARS, "x: 1\n", "x:   1\n")
        self.assertEqual((change.effect, change.format_only), (NONE, True))


def _sampled_span(sha: str) -> tuple[diff.Span, list[str]] | None:
    """
    Args:
        sha: one commit of ``SAMPLE``.

    Returns:
        The commit's span against its parent and the paths ``git diff
        --name-only`` lists for it, or ``None`` when this clone lacks it.
    """
    try:
        span = diff.resolve(f"{sha}^", sha)
        renamed = diff._git("diff", "--name-only", "-z", span.base, span.head)
    except (SystemExit, LookupError):
        return None
    return span, sorted(p for p in renamed.split("\0") if p)


class TestTheSampleResolves(unittest.TestCase):
    def test_ci_clone_holds_every_sampled_commit(self) -> None:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            self.skipTest("a local clone may be shallow; CI checks out full history")
        self.assertEqual(
            sorted(sha for sha in SAMPLE if _sampled_span(sha) is None), []
        )

    def test_the_buckets_plan_every_sampled_commit_exactly_once(self) -> None:
        planned = [sha for bucket in PLAN_BUCKETS for sha in bucket]
        self.assertEqual(sorted(planned), sorted(SAMPLE))
        self.assertEqual(len(planned), len(set(planned)))


class TestRetargetedVariantPinPlansAReinstall(unittest.TestCase):
    def test_retargeted_variant_pin_plans_a_reinstall_of_its_role(self) -> None:
        old, new = _pin_edit()
        catalog = Catalog()
        change = classify(
            DASHBOARD_VARIANTS, _read(old, new), Index(PROJECT_ROOT), _exists
        )
        with mock.patch.object(
            catalog, "free_bytes", side_effect=RuntimeError("no daemon")
        ):
            result = plan.build(
                [DASHBOARD_VARIANTS],
                [change],
                catalog,
                loop="",
                disable="",
                timings="",
            )
        t1 = [row for row in result["rows"] if row["tier"] == "T1"]
        self.assertEqual(
            (result["seeds"], [row["deploy"] for row in t1]),
            (["web-app-dashboard"], ["reinstall"]),
        )


class _PlanBucket:
    """
    Args:
        shas: the commits of ``SAMPLE`` the class plans.
    """

    shas: ClassVar[tuple[str, ...]]

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.script = _Script(Path(cls._tmp.name))
        cls.catalog = Catalog()
        cls.index = Index(PROJECT_ROOT)
        cls.spans: dict[str, diff.Span] = {}
        cls.script_roles: dict[str, set[str]] = {}
        cls.same_paths: dict[str, bool] = {}
        cls.plans: dict[str, dict] = {}
        script_paths: dict[str, list[str]] = {}
        for sha in cls.shas:
            sampled = _sampled_span(sha)
            if sampled is None:
                continue
            cls.spans[sha], script_paths[sha] = sampled
        with ThreadPoolExecutor(max_workers=max(1, len(cls.spans))) as pool:
            pending = {
                sha: pool.submit(cls.script.tokens, span.base, script_paths[sha])
                for sha, span in cls.spans.items()
            }
            for sha, span in cls.spans.items():
                cls.same_paths[sha] = script_paths[sha] == diff.changed_paths(span)
                cls.plans[sha] = cls._plan(span)
            for sha, future in pending.items():
                tokens = future.result()
                cls.script_roles[sha] = (
                    set(cls.catalog.roles)
                    if tokens == [plan.ALL]
                    else plan.token_roles(tokens)
                )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    @classmethod
    def _plan(cls, span: diff.Span) -> dict:
        with (
            mock.patch.object(entry, "Index", return_value=cls.index),
            mock.patch.object(
                cls.catalog, "free_bytes", side_effect=RuntimeError("no daemon")
            ),
        ):
            return entry.plan_span(span, cls.catalog, loop="", disable="", timings="")

    def _require(self, sha: str) -> None:
        if sha not in self.plans:
            self.skipTest(f"{sha} ({SAMPLE[sha]}) is not in this clone's history")

    def _missing(self, sha: str, result: dict) -> set[str]:
        return self.script_roles[sha] - plan.accounted(result)

    def test_every_role_the_script_deploys_is_in_the_plan(self) -> None:
        for sha in self.shas:
            with self.subTest(sha=sha, diff=SAMPLE[sha]):
                self._require(sha)
                self.assertEqual(self._missing(sha, self.plans[sha]), set())

    def test_baseline_reproduces_the_script(self) -> None:
        for sha in self.shas:
            with self.subTest(sha=sha, diff=SAMPLE[sha]):
                self._require(sha)
                baseline = set(self.plans[sha]["baseline"]["roles"])
                if self.same_paths[sha]:
                    self.assertEqual(baseline, self.script_roles[sha])
                else:
                    self.assertLessEqual(self.script_roles[sha], baseline)


class TestPlanCoversTheAffectedRolesScript(_PlanBucket, unittest.TestCase):
    shas = PLAN_BUCKETS[0]

    def test_deploy_machinery_commits_plan_the_full_set(self) -> None:
        for sha in WIDENS:
            with self.subTest(sha=sha, diff=SAMPLE[sha]):
                self._require(sha)
                result = self.plans[sha]
                self.assertEqual(
                    (bool(result["full"]), result["tiers"]["T3"]["whitelist"]),
                    (True, plan.ALL),
                )
                self.assertNotEqual(result["loop"], "none")

    def test_negative_control_role_commit_keeps_its_seed(self) -> None:
        self._require(ROLE_ONLY)
        result = self.plans[ROLE_ONLY]
        self.assertEqual((result["seeds"], result["full"]), (["web-app-keycloak"], ""))

    def test_sample_holds_narrowed_and_widened_diffs(self) -> None:
        present = [sha for sha in self.shas if sha in self.plans]
        if not present:
            self.skipTest("no sampled commit is in this clone's history")
        narrowed = [
            sha
            for sha in present
            if self.plans[sha]["tiers"]["T3"]["whitelist"] != plan.ALL
        ]
        widened = [
            sha
            for sha in present
            if self.plans[sha]["tiers"]["T3"]["whitelist"] == plan.ALL
        ]
        self.assertTrue(narrowed and widened, (narrowed, widened))

    def test_negative_control_a_baseline_without_the_fail_safe_is_caught(self) -> None:
        self._require(TESTS_ONLY)
        with mock.patch.object(plan, "_baseline", return_value=(set(), "mutant")):
            mutant = self._plan(self.spans[TESTS_ONLY])
        self.assertTrue(self._missing(TESTS_ONLY, mutant))

    def test_negative_control_a_dropped_cut_is_caught(self) -> None:
        self._require(TESTS_ONLY)
        merge = tiers.merge_cuts

        def without_all(cuts: list[dict]) -> list[dict]:
            return [c for c in merge(cuts) if c["tier"] != "all"]

        with mock.patch.object(tiers, "merge_cuts", side_effect=without_all):
            mutant = self._plan(self.spans[TESTS_ONLY])
        self.assertTrue(self._missing(TESTS_ONLY, mutant))

    def test_negative_control_a_narrowing_classifier_is_named_not_silent(self) -> None:
        self._require(ROLE_ONLY)
        with mock.patch.object(entry, "classify", side_effect=_seeds_dropped):
            mutant = self._plan(self.spans[ROLE_ONLY])
        cut = next(c for c in mutant["cuts"] if c["tier"] == "all")
        self.assertEqual(
            (self._missing(ROLE_ONLY, mutant), sorted(cut["paths"])),
            (set(), [f"roles/web-app-keycloak/{ROLE_FILE_META_SERVICES}"]),
        )


for _index, _bucket in enumerate(PLAN_BUCKETS[1:], start=1):
    register(
        globals(),
        f"TestPlanCoversTheAffectedRolesScript_bucket_{_index}",
        _PlanBucket,
        shas=_bucket,
    )


if __name__ == "__main__":
    unittest.main()
