from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from ._spec_secrets_fakes import (
    MASKER,
    RAW,
    TOUCH,
    VALUE,
    exec_tool,
    failed_scrub_run,
    install,
    leaks,
    load_masker,
    make_run,
    masked_run,
    scratch_text,
)
from ._spec_secrets_tool import detached_run, late_cid_run, ready, stopped_run

RUN_CODE = 3
FRAGMENT = "\N{LATIN SMALL LETTER E WITH ACUTE} \U0001f600 "
HALF_LINE = (
    "import sys, time; sys.stdout.write('sta'); sys.stdout.flush(); time.sleep(30)"
)
HALF_LINE_BOUND = 10
NAME_CHECK = "if named(str(Path(here, name)), masks):"
PROOF = "found.returncode and MISSING.search(found.stderr)"
HIDDEN = (
    "return UNSETTLED if scrubbed or unrelayed else (code if code >= 0 else 128 - code)",
    "return code if code >= 0 else 128 - code",
)
EMPTIED = (
    "swap(into, name, PUBLISHED_FILE, copy)",
    "swap(into, name, PUBLISHED_FILE, lambda _target: None)",
)
STDERR_DROPPED = (
    "((child.stdout, sys.stdout), (child.stderr, sys.stderr))",
    "((child.stdout, sys.stdout),)",
)
FAILED_RELAY = """\
import sys
sys.path.insert(0, sys.argv[1])
import spec_secrets_mask as masker
def relay(source, target, masks):
    raise RuntimeError
masker.relay = relay
sys.exit(masker.main(["spec_secrets_mask.py", "mask", *sys.argv[2:]]))
"""
QUIET = "print('done')"
FLOOD = "import sys; sys.stdout.write('x' * (1 << 20)); sys.stdout.flush()"
RELAY_BOUND = 30
WRITE_ARGV = "import json, pathlib, sys; pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))"
UNCHECKED = (
    "[*container, *spec_secrets.playwright(arguments)]",
    "[*container, *spec_secrets.RUNNER, *arguments]",
)
COPIED_MODE = (
    "swap(into, name, PUBLISHED_FILE, copy)",
    "swap(into, name, stat.S_IMODE(os.fstat(handle.fileno()).st_mode), copy)",
)
INHERITED_DIR_MODE = (
    "        os.fchmod(descriptor, PUBLISHED_DIR)\n",
    "        pass\n",
)


def published_names(module) -> tuple[int, list[str]]:
    """Publish staged reports, two of whose paths hold a piece of the value.

    Args:
        module: the loaded masker.

    Returns:
        The number ``publish`` refused and the names in the reports dir.
    """
    with tempfile.TemporaryDirectory() as tmp:
        staged, reports = Path(tmp) / "staged", Path(tmp) / "reports"
        (staged / VALUE[-20:]).mkdir(parents=True)
        (staged / VALUE[-20:] / "report.xml").write_text("ok")
        (staged / f"{VALUE[19:38]}.png").write_text("ok")
        (staged / "playwright-junit.xml").write_text("ok")
        refused = module.publish(staged, reports, module.windows([RAW]))
        return refused, sorted(os.listdir(reports))


def published_modes(module) -> dict[str, int]:
    """Publish a setuid and a setgid report from a setgid, sticky directory.

    Args:
        module: the loaded masker.

    Returns:
        The mode bits of each published path by its name below the reports
        dir, which ``publish`` creates in a setgid parent, ``.`` included.
    """
    with tempfile.TemporaryDirectory() as tmp:
        staged, reports = Path(tmp) / "staged", Path(tmp) / "setgid" / "reports"
        reports.parent.mkdir()
        reports.parent.chmod(0o2777)
        (staged / "sub").mkdir(parents=True)
        for path, mode in (
            (staged / "top.xml", 0o4755),
            (staged / "sub" / "a.png", 0o2777),
        ):
            path.write_text("ok")
            path.chmod(mode)
        (staged / "sub").chmod(0o3777)
        module.publish(staged, reports, module.windows([RAW]))
        return {
            name: stat.S_IMODE((reports / name).lstat().st_mode)
            for name in (".", "top.xml", "sub", "sub/a.png")
        }


def argv_run(arguments: list[str], *replacements) -> tuple[int, list[str] | None, bool]:
    """Mask a command that records its argv, with Playwright arguments behind it.

    Args:
        arguments: the arguments after the second ``--``.
        *replacements: changes to the masker or matcher, for a negative control.

    Returns:
        The masker's exit code, the argv the command got after its probe
        path or None when it never ran, and whether the run was marked
        unsettled.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = install(root / "bin", root, *replacements)
        directory = make_run(helper, f"LONG_KEY={VALUE}\n")
        probe = root / "argv.json"
        container, env = exec_tool(
            root, directory, [sys.executable, "-c", WRITE_ARGV, str(probe)]
        )
        masker = [sys.executable, str(root / "bin" / MASKER.name), "mask"]
        result = subprocess.run(
            [
                *masker,
                str(directory),
                str(root / "reports"),
                "--",
                *container,
                "--",
                *arguments,
            ],
            capture_output=True,
            check=False,
            env=env,
        )
        seen = json.loads(scratch_text(probe)) if probe.exists() else None
        return result.returncode, seen, (directory / ".unsettled").exists()


def failed_relay_run(child: str) -> int | str:
    """Mask a command whose output relays raise before they read a byte.

    Args:
        child: the Python source the fake container runs.

    Returns:
        The masker's exit code, or ``hung`` when it did not end within
        ``RELAY_BOUND`` seconds.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = install(root / "bin", root)
        directory = make_run(helper, f"LONG_KEY={VALUE}\n")
        container, env = exec_tool(root, directory, [sys.executable, "-c", child])
        patched = [sys.executable, "-c", FAILED_RELAY, str(root / "bin")]
        paths = [str(directory), str(root / "reports")]
        try:
            result = subprocess.run(
                [*patched, *paths, "--", *container, "--"],
                capture_output=True,
                check=False,
                env=env,
                timeout=RELAY_BOUND,
            )
        except subprocess.TimeoutExpired:
            return "hung"
        return result.returncode


class TestSpecSecretsMasking(unittest.TestCase):
    def test_the_runner_masks_output_and_every_report_but_never_a_link(self) -> None:
        self.assertEqual(masked_run(code=RUN_CODE), [])
        self.assertEqual(masked_run(owner_gone=True, code=RUN_CODE), [])

    @unittest.skipIf(os.geteuid() == 0, "root writes into a read-only dir")
    def test_a_report_that_cannot_be_rewritten_fails_the_scrub(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            module = load_masker()
            locked = Path(tmp) / "locked"
            locked.mkdir()
            (locked / "report.xml").write_text(VALUE)
            locked.chmod(0o555)
            try:
                self.assertEqual(module.scrub(Path(tmp), module.windows([RAW])), 1)
            finally:
                locked.chmod(0o755)

    def test_reports_that_cannot_be_masked_fail_the_run_and_are_never_published(
        self,
    ) -> None:
        self.assertEqual(failed_scrub_run(), (70, [], False, 1))

    def test_a_reports_dir_that_is_a_link_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            helper = install(root / "bin", root)
            directory = make_run(helper, f"LONG_KEY={VALUE}\n")
            (root / "target").mkdir()
            (root / "target" / "report.xml").write_text(VALUE)
            (root / "reports").symlink_to(root / "target")
            marker = root / "ran"
            touch = [sys.executable, "-c", TOUCH, str(marker)]
            container, env = exec_tool(root, directory, touch)
            masker = [sys.executable, str(root / "bin" / MASKER.name), "mask"]
            links = [str(directory), str(root / "reports")]
            result = subprocess.run(
                [*masker, *links, "--", *container, "--"],
                capture_output=True,
                check=False,
                env=env,
            )
            self.assertEqual((result.returncode, marker.exists()), (70, False))
            self.assertTrue((directory / ".unsettled").exists())
            module = load_masker()
            self.assertEqual(module.scrub(root / "reports", module.windows([RAW])), 1)
            self.assertEqual(scratch_text(root / "target" / "report.xml"), VALUE)

    def test_a_directory_swapped_for_a_link_mid_walk_is_never_followed(self) -> None:
        module = load_masker()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "reports" / "sub").mkdir(parents=True)
            (root / "reports" / "sub" / "report.xml").write_text(VALUE)
            (root / "outside").mkdir()
            (root / "outside" / "report.xml").write_text(VALUE)
            walk = module.walk

            def swapping(directory, failed):
                for item in walk(directory, failed):
                    (root / "reports" / "sub").rename(root / "reports" / "old")
                    (root / "reports" / "sub").symlink_to(root / "outside")
                    yield item

            module.walk = swapping
            self.assertEqual(module.scrub(root / "reports", module.windows([RAW])), 0)
            self.assertEqual(scratch_text(root / "outside" / "report.xml"), VALUE)
            self.assertFalse(
                leaks(scratch_text(root / "reports" / "old" / "report.xml"), VALUE)
            )

    def test_term_and_kill_end_with_the_container_removed_and_reports_masked(
        self,
    ) -> None:
        self.assertEqual(
            stopped_run(signal.SIGTERM),
            [
                "masker 137",
                "published masked",
                "scrub 0",
                "container alive False",
                "published masked",
                "masker removals 1",
            ],
        )
        self.assertEqual(
            stopped_run(signal.SIGKILL),
            [
                "masker -9",
                "published none",
                "scrub 0",
                "container alive False",
                "published masked",
                "masker removals 0",
            ],
        )

    def test_a_scrub_whose_tool_cannot_remove_the_container_publishes_nothing(
        self,
    ) -> None:
        self.assertEqual(
            stopped_run(signal.SIGKILL, True),
            [
                "masker -9",
                "published none",
                "scrub 1",
                "container alive True",
                "published none",
                "masker removals 0",
            ],
        )

    def test_a_container_that_outlives_its_tool_is_removed_before_publishing(
        self,
    ) -> None:
        self.assertEqual(
            detached_run(False),
            ["masker 0", "published masked", "container alive False"],
        )
        self.assertEqual(
            detached_run(True),
            ["masker 70", "published none", "container alive True"],
        )

    def test_a_term_before_the_container_id_still_removes_the_container(self) -> None:
        self.assertEqual(late_cid_run(), ["masker 0", "container alive False"])

    def test_an_output_relay_that_fails_leaves_the_run_unsettled(self) -> None:
        self.assertEqual(failed_relay_run(QUIET), 70)
        self.assertEqual(failed_relay_run(FLOOD), 70)

    def test_a_removal_that_takes_seconds_still_publishes_the_masked_reports(
        self,
    ) -> None:
        self.assertEqual(
            detached_run(False, slow=True),
            ["masker 0", "published masked", "container alive False"],
        )

    def test_a_report_whose_path_holds_a_value_is_never_published(self) -> None:
        self.assertEqual(published_names(load_masker()), (2, ["playwright-junit.xml"]))

    def test_reports_are_published_with_fixed_modes_whatever_the_container_set(
        self,
    ) -> None:
        self.assertEqual(
            published_modes(load_masker()),
            {".": 0o755, "top.xml": 0o644, "sub": 0o755, "sub/a.png": 0o644},
        )

    def test_the_masker_appends_the_only_command_and_checks_its_arguments(
        self,
    ) -> None:
        runner = list(load_masker().spec_secrets.RUNNER)
        arguments = ["--grep", "login flow", "--max-failures=2", "tests/a.spec.js"]
        self.assertEqual(argv_run(arguments), (0, [*runner, *arguments], False))
        for refused in (["--reporter=html"], ["--trace=on"], ["-c", "x.js"], ["--ui"]):
            with self.subTest(arguments=refused):
                self.assertEqual(argv_run(refused), (70, None, True))

    def test_the_leak_check_counts_bytes_not_characters(self) -> None:
        self.assertTrue(leaks(f"<{FRAGMENT}>", VALUE))

    def test_a_child_that_prints_half_a_line_does_not_hold_the_wait(self) -> None:
        child = subprocess.Popen(
            [sys.executable, "-c", HALF_LINE], stdout=subprocess.PIPE
        )
        try:
            started = time.monotonic()
            self.assertFalse(ready(child, 1))
            self.assertLess(time.monotonic() - started, HALF_LINE_BOUND)
        finally:
            child.kill()
            child.wait()
            child.stdout.close()

    def test_bad_usage_and_a_foreign_run_directory_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for argv, code in (
                (["scrub", tmp], 2),
                (["scrub", tmp, tmp], 2),
                (["scrub", tmp, tmp, "docker", "name", "extra"], 2),
                (["mask", tmp, tmp, "true"], 2),
                (["mask", tmp, tmp, "--", "true"], 2),
                (["baseline", tmp], 2),
                (["scrub", tmp, tmp, "docker"], 1),
                (["scrub", tmp, tmp, "docker", "name"], 1),
                (["mask", tmp, tmp, "--", "true", "--"], 70),
            ):
                with self.subTest(argv=argv):
                    result = subprocess.run(
                        [sys.executable, "-B", str(MASKER), *argv],
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, code)


class TestSpecSecretsMaskingNegativeControls(unittest.TestCase):
    def test_a_publish_that_copies_a_name_holding_a_value_is_caught(self) -> None:
        self.assertEqual(
            published_names(load_masker((NAME_CHECK, "if False:"))),
            (0, sorted(["playwright-junit.xml", VALUE[-20:], f"{VALUE[19:38]}.png"])),
        )

    def test_a_publish_that_copies_the_container_modes_is_caught(self) -> None:
        self.assertEqual(published_modes(load_masker(COPIED_MODE))["top.xml"], 0o4755)

    def test_a_publish_whose_directories_keep_a_setgid_parent_bit_is_caught(
        self,
    ) -> None:
        modes = published_modes(load_masker(INHERITED_DIR_MODE))
        self.assertTrue(modes["."] & modes["sub"] & stat.S_ISGID)

    def test_a_masker_that_runs_unchecked_arguments_is_caught(self) -> None:
        code, seen, _marked = argv_run(["--reporter=html"], UNCHECKED)
        self.assertEqual((code, (seen or [])[-1:]), (0, ["--reporter=html"]))

    def test_a_masker_that_masks_nothing_or_follows_links_is_caught(self) -> None:
        nothing = masked_run(
            ("if view[at : at + MASK_MIN] in self.masks", "if False"), code=RUN_CODE
        )
        self.assertEqual(
            nothing,
            [
                "stdout shows the value",
                "stderr shows the value",
                "junit shows the value",
                "older report shows the value",
                "stderr lacks its expected text",
                "junit lacks its expected text",
                "older report lacks its expected text",
            ],
        )
        following = masked_run(
            (
                "        if not stat.S_ISREG(os.stat(name, dir_fd=at, follow_symlinks=False).st_mode):\n            return None\n",
                "",
            ),
            (
                "OPEN_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK",
                "OPEN_FILE = os.O_RDONLY",
            ),
            code=RUN_CODE,
        )
        self.assertEqual(following, ["a link was followed"])

    def test_a_masker_that_empties_the_reports_or_drops_stderr_is_caught(
        self,
    ) -> None:
        self.assertEqual(
            masked_run(EMPTIED, code=RUN_CODE),
            ["junit lacks its expected text", "older report lacks its expected text"],
        )
        self.assertEqual(
            masked_run(STDERR_DROPPED, code=RUN_CODE),
            ["stderr lacks its expected text"],
        )

    def test_a_masker_that_hides_a_failed_scrub_or_a_failed_removal_is_caught(
        self,
    ) -> None:
        self.assertEqual(failed_scrub_run(HIDDEN)[::3], (0, 0))
        trusting = (PROOF, "True")
        self.assertEqual(stopped_run(signal.SIGKILL, True, trusting)[2], "scrub 0")

    def test_a_masker_whose_failure_leaves_no_mark_for_the_scrub_is_caught(
        self,
    ) -> None:
        unmarked = ("unsettled(paths[0])", "None")
        self.assertEqual(failed_scrub_run(unmarked)[::3], (70, 0))

    def test_a_removal_bound_by_tries_instead_of_seconds_is_caught(self) -> None:
        hasty = ("REMOVAL_SECONDS = 6.0", "REMOVAL_SECONDS = 1.0")
        self.assertEqual(
            detached_run(False, hasty, slow=True),
            ["masker 70", "published none", "container alive True"],
        )

    def test_a_masker_that_removes_the_container_twice_on_term_is_caught(
        self,
    ) -> None:
        twice = ("        if removals:\n            return removals[0]\n", "")
        self.assertEqual(
            stopped_run(signal.SIGTERM, False, twice)[-1], "masker removals 2"
        )

    def test_a_masker_that_caches_a_removal_before_the_container_id_is_caught(
        self,
    ) -> None:
        caching = (
            "        if known:\n            removals.append(gone)\n",
            "        removals.append(gone)\n",
        )
        self.assertEqual(late_cid_run(caching)[1:], ["container alive True"])

    def test_a_masker_that_settles_before_the_container_is_gone_is_caught(
        self,
    ) -> None:
        settling = ('gone = remove_container(directory, command[0], "")', "gone = True")
        for broken in (settling, (PROOF, "True")):
            with self.subTest(old=broken[0]):
                found = detached_run(True, broken)
                self.assertEqual(found[0], "masker 0")
                self.assertNotEqual(found[1], "published none")

    def test_a_masker_that_publishes_or_keeps_unmasked_reports_is_caught(
        self,
    ) -> None:
        publishing = (
            "    elif scrub(staged, masks):",
            "    elif scrub(staged, masks) and False:",
        )
        self.assertEqual(failed_scrub_run(publishing)[1], ["playwright-junit.xml"])
        keeping = ("    shutil.rmtree(staged, ignore_errors=True)\n", "")
        self.assertTrue(failed_scrub_run(keeping)[2])
        self.assertIn(
            "the staged reports were left behind", masked_run(keeping, code=RUN_CODE)
        )

    def test_a_masker_that_walks_a_linked_reports_dir_is_caught(self) -> None:
        module = load_masker(
            (
                "        return os.open(root, spec_secrets.OPEN_DIR)",
                "        return os.open(root, os.O_RDONLY)",
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "target").mkdir()
            (Path(tmp) / "target" / "report.xml").write_text(VALUE)
            (Path(tmp) / "reports").symlink_to(Path(tmp) / "target")
            self.assertEqual(
                module.scrub(Path(tmp) / "reports", module.windows([RAW])), 0
            )
            self.assertFalse(
                leaks(scratch_text(Path(tmp) / "target" / "report.xml"), VALUE)
            )


if __name__ == "__main__":
    unittest.main()
