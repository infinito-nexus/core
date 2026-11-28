"""The compose project name, the container names and the slot of a stack.

Without ``INFINITO_STACK_NAME`` every name equals the one compose and the
``.env`` produced before the explicit ``-p``: the normalized checkout basename,
``INFINITO_CONTAINER`` and ``INFINITO_RUNNER_PREFIX`` as ``.env`` holds them.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import ClassVar

from cli.administration.deploy.development.env import compose_file_args
from cli.administration.deploy.development.slots import (
    Entry,
    SlotError,
    allocate,
    default_stack,
    entries,
    legacy_slot,
    registry_root,
    release,
    run,
)
from cli.administration.deploy.development.stack import (
    compose_argv,
    normalize,
    stack_name,
)
from tests.utils.unprivileged import unprivileged
from utils.cache.files import PROJECT_ROOT, read_text
from utils.env.handlers.infinito.cache.paths import ENTRIES, machine

ROOT = Path(PROJECT_ROOT)
MAIN_CHECKOUT = "infinito-nexus-core"
WORKTREE = "local-stack-092-r4"
SHOWN = (
    "INFINITO_DISTRO",
    "INFINITO_CONTAINER",
    "INFINITO_RUNNER_PREFIX",
    "INFINITO_STACK_NAME",
)
SLOTS = "cli.administration.deploy.development.slots"
WORKTREE_LIB = ROOT / "scripts" / "system" / "worktree" / "lib.sh"
MAX_SLOT = re.compile(r"^WORKTREE_MAX_SLOT=(\d+)$", re.MULTILINE)
LAST = int(MAX_SLOT.search(read_text(str(WORKTREE_LIB)))[1])


def scratch_dir(test: unittest.TestCase) -> Path:
    path = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, path)
    return path


def clean_env(**overrides: str) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("INFINITO_", "COMPOSE_"))
        and k not in ("BASH_ENV", "PYTHONPATH", "VENV", "PYTHON", "VIRTUAL_ENV")
    }
    env["PYTHONPATH"] = str(ROOT)
    env.update(overrides)
    return env


class TestDefaultProjectName(unittest.TestCase):
    def checkout(self, *parts: str) -> Path:
        path = scratch_dir(self).joinpath(*parts)
        path.mkdir(parents=True)
        return path

    def test_main_checkout_keeps_its_implicit_name(self):
        root = self.checkout("Repositories", "github.com", "owner", MAIN_CHECKOUT)
        self.assertEqual(stack_name(root, {}), MAIN_CHECKOUT)

    def test_worktree_keeps_its_implicit_name(self):
        root = self.checkout("worktrees", "core", "feature", "iam-reqs", WORKTREE)
        self.assertEqual(stack_name(root, {}), WORKTREE)

    def test_the_basename_is_normalized_like_compose_does(self):
        self.assertEqual(normalize("Infinito.Nexus_Core"), "infinitonexus_core")
        self.assertEqual(normalize("__-x.Y"), "xy")
        root = self.checkout("Some.Checkout")
        self.assertEqual(stack_name(root, {}), "somecheckout")

    def test_compose_project_name_still_wins_when_no_stack_is_named(self):
        root = self.checkout(WORKTREE)
        env = {"COMPOSE_PROJECT_NAME": "runner-1"}
        self.assertEqual(stack_name(root, env), "runner-1")

    def test_a_symlinked_pwd_names_the_project_like_go_getwd(self):
        base = scratch_dir(self)
        real = base / "real-name"
        real.mkdir()
        (base / "alias").symlink_to(real)
        self.assertEqual(stack_name(real, {"PWD": str(base / "alias")}), "alias")
        self.assertEqual(stack_name(real, {"PWD": str(base)}), "real-name")

    def test_compose_argv_only_adds_the_implicit_project(self):
        before = ["docker", "compose", *compose_file_args()]
        after = compose_argv(ROOT)
        self.assertEqual(
            after[:4], ["docker", "compose", "-p", stack_name(ROOT, os.environ)]
        )
        self.assertEqual([*after[:2], *after[4:]], before)


class TestNamedStack(unittest.TestCase):
    def test_the_stack_name_wins_over_both_implicit_sources(self):
        env = {"INFINITO_STACK_NAME": "demo", "COMPOSE_PROJECT_NAME": "runner-1"}
        self.assertEqual(stack_name(ROOT, env), "demo")

    def test_an_invalid_stack_name_is_refused(self):
        with self.assertRaises(SystemExit):
            stack_name(ROOT, {"INFINITO_STACK_NAME": "Demo.Stack"})

    def test_compose_argv_addresses_the_named_stack(self):
        with mock.patch.dict(os.environ, {"INFINITO_STACK_NAME": "demo"}):
            self.assertEqual(compose_argv(ROOT)[2:4], ["-p", "demo"])


class TestShellHelper(unittest.TestCase):
    def run_helper(self, **overrides: str) -> list[str]:
        bin_dir = scratch_dir(self)
        fake = bin_dir / "docker"
        fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        env = clean_env(
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            VENV=str(Path(sys.executable).parent.parent),
            **overrides,
        )
        proc = subprocess.run(
            [
                "bash",
                "-c",
                "source scripts/meta/compose.sh && infinito_compose ps -q infinito",
            ],
            env=env,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.splitlines()

    def test_unnamed_call_passes_the_implicit_project_and_the_files(self):
        argv = self.run_helper()
        self.assertEqual(
            argv[:5], ["compose", "-p", normalize(ROOT.name), "-f", "compose.yml"]
        )
        self.assertEqual(argv[-3:], ["ps", "-q", "infinito"])

    def test_named_call_passes_the_stack_name(self):
        argv = self.run_helper(INFINITO_STACK_NAME="demo")
        self.assertEqual(argv[:3], ["compose", "-p", "demo"])


class TestLoaderContainerNames(unittest.TestCase):
    DOTENV: ClassVar[dict[str, dict[str, str]]] = {
        "main": {
            "INFINITO_DISTRO": "debian",
            "INFINITO_CONTAINER": "infinito_nexus_debian",
            "INFINITO_RUNNER_PREFIX": "infinito",
            "INFINITO_STACK_NAME": "",
        },
        "worktree": {
            "INFINITO_DISTRO": "debian",
            "INFINITO_CONTAINER": "infinito_nexus_feature_iam_reqs_x",
            "INFINITO_RUNNER_PREFIX": "infinito-feature-iam-reqs-x",
            "INFINITO_STACK_NAME": "",
        },
    }

    def load(self, dotenv: dict[str, str], steps: str) -> dict[str, str]:
        checkout = scratch_dir(self)
        loader = checkout / "scripts" / "meta" / "env"
        loader.mkdir(parents=True)
        for name in ("load.sh", "python.sh"):
            shutil.copy(ROOT / "scripts" / "meta" / "env" / name, loader)
        (checkout / ".env").write_text(
            "".join(f"{k}={v}\n" for k, v in dotenv.items()), encoding="utf-8"
        )
        show = "printf '%s\\n' " + " ".join(f'"{k}=${{{k}:-}}"' for k in SHOWN)
        proc = subprocess.run(
            [
                "bash",
                "-c",
                f"load() {{ source scripts/meta/env/load.sh; }}\n{steps}\n{show}",
            ],
            env=clean_env(),
            cwd=checkout,
            capture_output=True,
            text=True,
            check=True,
        )
        return dict(line.split("=", 1) for line in proc.stdout.splitlines())

    def test_unnamed_main_checkout_keeps_the_dotenv_names(self):
        self.assertEqual(self.load(self.DOTENV["main"], "load"), self.DOTENV["main"])

    def test_unnamed_worktree_keeps_its_pinned_names(self):
        shown = self.load(self.DOTENV["worktree"], "load\nload")
        self.assertEqual(shown, self.DOTENV["worktree"])

    def test_a_named_stack_derives_its_container_names(self):
        shown = self.load(
            self.DOTENV["worktree"], "export INFINITO_STACK_NAME=demo-1\nload"
        )
        self.assertEqual(shown["INFINITO_CONTAINER"], "infinito_nexus_demo_1")
        self.assertEqual(shown["INFINITO_RUNNER_PREFIX"], "infinito-demo-1")

    def test_naming_a_stack_after_the_first_load_derives_its_names(self):
        shown = self.load(
            self.DOTENV["main"], "load\nexport INFINITO_STACK_NAME=demo\nload"
        )
        self.assertEqual(shown["INFINITO_CONTAINER"], "infinito_nexus_demo")

    def test_dropping_the_name_restores_the_dotenv_names(self):
        shown = self.load(
            self.DOTENV["worktree"],
            "export INFINITO_STACK_NAME=demo\nload\nexport INFINITO_STACK_NAME=\nload",
        )
        self.assertEqual(shown, self.DOTENV["worktree"])


class SlotRegistryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.base = scratch_dir(self)
        self.root = self.base / "registry"

    def checkout(self, *parts: str) -> Path:
        path = self.base.joinpath("checkouts", *parts)
        path.mkdir(parents=True)
        return path

    def pinned(self, *parts: str, **files: int) -> Path:
        path = self.checkout(*parts)
        for name, slot in files.items():
            (path / name).write_text(f"INFINITO_INSTANCE={slot}\n", encoding="utf-8")
        return path

    def allocate(
        self,
        stack: str,
        checkout: Path,
        known: tuple[Path, ...] = (),
        taken: tuple[int, ...] = (),
        last: int = LAST,
    ) -> int:
        return allocate(self.root, stack, checkout, known, taken, last)

    def slots(self) -> dict[str, int]:
        return {stack: entry.slot for stack, entry in entries(self.root).items()}


class TestSlotAllocation(SlotRegistryCase):
    def test_the_registry_sits_below_the_cache_base_outside_every_cache_folder(
        self,
    ):
        root = registry_root()
        self.assertEqual(root.parent, machine())
        self.assertNotIn(root.name, {legs[0] for _, legs, _ in ENTRIES})

    def test_worktree_up_records_the_slot_under_the_default_stack_name(self):
        checkout = self.checkout("feature", "Store.I18n")
        out, err = io.StringIO(), io.StringIO()
        argv = ["allocate", str(checkout), "--last", str(LAST), "--known", "--taken"]
        self.assertEqual(run(argv, self.root, out, err), 0, err.getvalue())
        self.assertEqual(out.getvalue(), "1\n")
        self.assertEqual(default_stack(checkout), stack_name(checkout, {}))
        self.assertEqual(
            entries(self.root),
            {"storei18n": Entry("storei18n", 1, str(checkout.resolve()))},
        )

    def test_two_stack_names_from_one_checkout_get_two_slots(self):
        checkout = self.checkout("alpha")
        self.assertEqual(self.allocate("alpha", checkout), 1)
        self.assertEqual(self.allocate("demo", checkout), 2)
        self.assertEqual(self.slots(), {"alpha": 1, "demo": 2})

    def test_the_lowest_slot_no_entry_and_no_network_holds_is_allocated(self):
        self.allocate("one", self.checkout("one"))
        self.allocate("two", self.checkout("two"))
        self.assertEqual(self.allocate("four", self.checkout("four"), taken=(3,)), 4)

    def test_a_full_range_is_refused_and_records_nothing(self):
        with self.assertRaisesRegex(SlotError, "no free slot"):
            self.allocate("one", self.checkout("one"), taken=(1, 2), last=2)
        self.assertEqual(self.slots(), {})

    def test_the_cli_reports_a_refusal_without_a_slot(self):
        out, err = io.StringIO(), io.StringIO()
        argv = ["allocate", str(self.checkout("one")), "--last", "1"]
        argv += ["--known", "--taken", "1"]
        self.assertEqual(run(argv, self.root, out, err), 1)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("FAILURE: no free slot left in 1..1", err.getvalue())

    def test_a_name_that_is_no_compose_project_is_refused(self):
        with self.assertRaises(SlotError):
            self.allocate("../escape", self.checkout("one"))
        self.assertFalse(self.root.exists())

    def test_a_missing_checkout_gets_no_slot(self):
        with self.assertRaisesRegex(SlotError, "does not exist"):
            self.allocate("ghost", self.base / "ghost")
        self.assertEqual(self.slots(), {})

    def test_a_stack_another_existing_checkout_holds_is_refused(self):
        first = self.checkout("feature", "x")
        self.allocate("x", first)
        with self.assertRaises(SlotError) as refusal:
            self.allocate("x", self.checkout("fix", "x"))
        self.assertIn(str(first.resolve()), str(refusal.exception))
        self.assertEqual(entries(self.root)["x"].checkout, str(first.resolve()))

    @unprivileged
    def test_an_unwritable_registry_is_refused_without_a_traceback(self):
        self.root.mkdir()
        self.root.chmod(0o500)
        self.addCleanup(self.root.chmod, 0o700)
        checkout = str(self.checkout("one"))
        commands = (
            ["allocate", checkout, "--last", str(LAST), "--known", "--taken"],
            ["release", checkout],
        )
        for argv in commands:
            with self.subTest(command=argv[0]):
                out, err = io.StringIO(), io.StringIO()
                self.assertEqual(run(argv, self.root, out, err), 1)
                self.assertEqual(out.getvalue(), "")
                self.assertIn(
                    f"FAILURE: this user cannot write the slot registry {self.root}",
                    err.getvalue(),
                )
                self.assertIn('sudo chown -R "$USER"', err.getvalue())


class TestSlotReuse(SlotRegistryCase):
    def test_a_stack_keeps_its_slot_across_a_down_and_an_up(self):
        alpha = self.checkout("alpha")
        first = self.allocate("alpha", alpha)
        self.allocate("beta", self.checkout("beta"))
        self.assertEqual(self.allocate("alpha", alpha, taken=(first,)), first)
        self.assertEqual(self.slots(), {"alpha": 1, "beta": 2})

    def test_a_removed_checkout_frees_its_slot_at_the_next_allocation(self):
        alpha = self.checkout("alpha")
        self.allocate("alpha", alpha)
        shutil.rmtree(alpha)
        self.assertEqual(self.allocate("beta", self.checkout("beta")), 1)
        self.assertEqual(self.slots(), {"beta": 1})

    def test_a_checkout_recreated_at_its_path_keeps_its_slot(self):
        self.allocate("one", self.checkout("one"))
        alpha = self.checkout("alpha")
        slot = self.allocate("alpha", alpha)
        shutil.rmtree(alpha)
        alpha.mkdir()
        self.assertEqual(self.allocate("alpha", alpha), slot)

    def test_a_recorded_slot_another_worktree_now_pins_moves_the_stack(self):
        alpha = self.checkout("alpha")
        self.assertEqual(self.allocate("alpha", alpha), 1)
        hand = self.pinned("hand", **{"custom.env": 1})
        self.assertEqual(self.allocate("alpha", alpha, known=(alpha, hand)), 2)
        self.assertEqual(self.slots(), {"alpha": 2, "hand": 1})

    def test_a_checkout_pinning_its_own_recorded_slot_keeps_it(self):
        alpha = self.checkout("alpha")
        slot = self.allocate("alpha", alpha)
        (alpha / "custom.env").write_text(
            f"INFINITO_INSTANCE={slot}\n", encoding="utf-8"
        )
        self.assertEqual(self.allocate("alpha", alpha, known=(alpha,)), slot)
        self.assertEqual(self.slots(), {"alpha": slot})

    def test_a_listed_checkout_keeps_its_slot_while_its_directory_is_unreachable(
        self,
    ):
        alpha = self.checkout("alpha")
        self.allocate("alpha", alpha)
        shutil.rmtree(alpha)
        beta = self.checkout("beta")
        self.assertEqual(self.allocate("beta", beta, known=(alpha,)), 2)
        self.assertEqual(self.slots(), {"alpha": 1, "beta": 2})

    def test_a_listed_unreachable_checkout_keeps_its_stack_name(self):
        holder = self.checkout("feature", "x")
        self.allocate("x", holder)
        shutil.rmtree(holder)
        with self.assertRaises(SlotError):
            self.allocate("x", self.checkout("fix", "x"), known=(holder,))
        self.assertEqual(entries(self.root)["x"].checkout, str(holder.resolve()))


class TestDamagedEntries(SlotRegistryCase):
    def damage(self, name: str, content: str) -> None:
        self.root.mkdir(exist_ok=True)
        (self.root / f"{name}.json").write_text(content, encoding="utf-8")

    def test_a_damaged_entry_is_reported_and_counts_as_absent(self):
        damaged = {
            "torn": '{"stack": "torn", "slot"',
            "alien": '{"stack": "alien"}',
            "moved": '{"stack": "other", "slot": 1, "checkout": "/x"}',
            "text": '{"stack": "text", "slot": "1", "checkout": "/x"}',
        }
        for name, content in damaged.items():
            self.damage(name, content)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(self.slots(), {})
        for name in damaged:
            self.assertIn(
                f"damaged slot registry entry {self.root / name}.json",
                stderr.getvalue(),
            )

    def test_allocate_and_release_go_on_past_a_damaged_entry(self):
        self.damage("torn", "{")
        alpha = self.checkout("alpha")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.allocate("alpha", alpha), 1)
            freed = release(self.root, alpha)
        self.assertEqual([entry.stack for entry in freed], ["alpha"])

    def test_writing_the_stack_again_repairs_its_entry(self):
        self.damage("alpha", "{")
        alpha = self.checkout("alpha")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.allocate("alpha", alpha), 1)
        self.assertEqual(self.slots(), {"alpha": 1})


class TestLegacyPin(SlotRegistryCase):
    def test_the_last_numeric_pin_line_wins(self):
        checkout = self.pinned("w")
        (checkout / "custom.env").write_text(
            "INFINITO_INSTANCE=4\nINFINITO_INSTANCE=7\n", encoding="utf-8"
        )
        self.assertEqual(legacy_slot(checkout), 7)

    def test_a_file_the_env_parser_rejects_still_yields_its_pin(self):
        checkout = self.pinned("w")
        (checkout / ".env").write_bytes(
            b"no key value here\n\xff\xfe\nINFINITO_INSTANCE=5\n"
        )
        self.assertEqual(legacy_slot(checkout), 5)

    def test_an_unreadable_file_pins_nothing_and_the_next_one_counts(self):
        checkout = self.pinned("w", **{".env": 6})
        (checkout / "custom.env").mkdir()
        self.assertEqual(legacy_slot(checkout), 6)

    def test_a_non_numeric_pin_pins_nothing(self):
        checkout = self.pinned("w")
        (checkout / "custom.env").write_text(
            "INFINITO_INSTANCE=abc\n", encoding="utf-8"
        )
        self.assertIsNone(legacy_slot(checkout))


class TestSlotRelease(SlotRegistryCase):
    def test_release_frees_every_stack_of_the_checkout(self):
        alpha = self.checkout("alpha")
        self.allocate("alpha", alpha)
        self.allocate("demo", alpha)
        self.allocate("beta", self.checkout("beta"))
        freed = release(self.root, alpha)
        self.assertEqual(
            sorted((entry.stack, entry.slot) for entry in freed),
            [("alpha", 1), ("demo", 2)],
        )
        self.assertEqual(self.slots(), {"beta": 3})
        self.assertEqual(self.allocate("gamma", self.checkout("gamma")), 1)

    def test_the_cli_releases_a_removed_checkout_by_its_path(self):
        alpha = self.checkout("alpha")
        self.allocate("alpha", alpha)
        shutil.rmtree(alpha)
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(run(["release", str(alpha)], self.root, out, err), 0)
        self.assertEqual(out.getvalue(), "Slot 1 of stack alpha released.\n")
        self.assertEqual(self.slots(), {})

    def test_releasing_a_checkout_without_a_slot_says_so(self):
        beta = self.checkout("beta")
        self.allocate("alpha", self.checkout("alpha"))
        out = io.StringIO()
        self.assertEqual(run(["release", str(beta)], self.root, out, io.StringIO()), 0)
        self.assertEqual(out.getvalue(), f"No slot recorded for {beta.resolve()}.\n")
        self.assertEqual(self.slots(), {"alpha": 1})


class TestSlotMigration(SlotRegistryCase):
    def test_every_existing_worktree_keeps_its_pinned_slot(self):
        known = (
            self.pinned("core", **{".env": 0}),
            self.pinned("feature", "three", **{"custom.env": 3}),
            self.pinned("fix", "one", **{".env": 1}),
            self.checkout("feature", "fresh"),
        )
        self.assertEqual(self.allocate("fresh", known[3], known=known), 2)
        self.assertEqual(self.slots(), {"three": 3, "one": 1, "fresh": 2})

    def test_custom_env_wins_over_the_generated_dotenv(self):
        both = self.pinned("both", **{"custom.env": 4, ".env": 6})
        self.allocate("fresh", self.checkout("fresh"), known=(both,))
        self.assertEqual(self.slots()["both"], 4)

    def test_a_hand_repinned_worktree_keeps_its_new_pin_out_of_reach(self):
        three = self.pinned("three", **{"custom.env": 3})
        self.assertEqual(self.allocate("a", self.checkout("a"), known=(three,)), 1)
        (three / "custom.env").write_text("INFINITO_INSTANCE=2\n", encoding="utf-8")
        self.assertEqual(self.allocate("b", self.checkout("b"), known=(three,)), 4)
        self.assertEqual(self.slots(), {"three": 3, "a": 1, "b": 4})

    def test_a_malformed_file_in_a_listed_worktree_aborts_no_allocation(self):
        broken = self.checkout("broken")
        (broken / ".env").write_bytes(b"no key value here\nINFINITO_INSTANCE=5\n")
        fresh = self.checkout("fresh")
        self.assertEqual(self.allocate("fresh", fresh, known=(broken,)), 1)
        self.assertEqual(self.slots(), {"broken": 5, "fresh": 1})

    def test_an_existing_worktree_asking_itself_gets_its_pinned_slot(self):
        three = self.pinned("three", **{"custom.env": 3})
        self.assertEqual(self.allocate("three", three, known=(three,)), 3)

    def test_a_pin_under_a_name_another_checkout_holds_is_never_handed_out(self):
        holder = self.checkout("feature", "x")
        self.allocate("x", holder)
        twin = self.pinned("fix", "x", **{"custom.env": 2})
        self.assertEqual(self.allocate("y", self.checkout("y"), known=(twin,)), 3)
        self.assertEqual(self.slots(), {"x": 1, "y": 3})


class TestConcurrentAllocation(SlotRegistryCase):
    def race(self, count: int) -> list[int]:
        start = threading.Barrier(count)
        slots: list[int] = []
        errors: list[BaseException] = []
        checkouts = [self.checkout(f"c{index}") for index in range(count)]

        def worker(checkout: Path) -> None:
            start.wait(timeout=10)
            try:
                slots.append(self.allocate(checkout.name, checkout))
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(c,)) for c in checkouts]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(errors, [])
        return sorted(slots)

    def test_concurrent_allocations_get_distinct_slots(self):
        def slow(root: Path) -> dict[str, Entry]:
            found = entries(root)
            time.sleep(0.05)
            return found

        with mock.patch(f"{SLOTS}.entries", side_effect=slow):
            self.assertEqual(self.race(4), [1, 2, 3, 4])

    def test_without_the_lock_the_same_race_hands_one_slot_out_twice(self):
        count = 3
        meet = threading.Barrier(count)

        def meeting(root: Path) -> dict[str, Entry]:
            found = entries(root)
            meet.wait(timeout=10)
            return found

        self.root.mkdir()
        with (
            mock.patch(
                f"{SLOTS}.hold", side_effect=lambda *_: contextlib.nullcontext()
            ),
            mock.patch(f"{SLOTS}.entries", side_effect=meeting),
        ):
            self.assertEqual(self.race(count), [1] * count)


if __name__ == "__main__":
    unittest.main()
