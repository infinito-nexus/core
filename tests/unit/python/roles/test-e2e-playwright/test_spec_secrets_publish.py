from __future__ import annotations

import fcntl
import io
import os
import stat
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, suppress
from pathlib import Path

from ._spec_secrets_fakes import RAW, load_masker, scratch_text

FOLLOWING = (
    "    descriptor = os.open(name, spec_secrets.OPEN_DIR, dir_fd=at)",
    "    descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=at)",
)
KEPT_MODE = ("        os.fchmod(descriptor, PUBLISHED_DIR)\n", "        pass\n")
OPENING = (
    "swap(into, name, PUBLISHED_FILE, copy)",
    'copy(os.fdopen(os.open(name, os.O_WRONLY | os.O_NONBLOCK, dir_fd=into), "wb"))',
)
CONTAINER_ID = "c0ffee1d"
UNNAMED = ("{container_named(directory, name)}", "{name or 'unnamed'}")
LINKED_VALUE = "Sentinel9f3cLinkedValue"
UNDELETED = '        print("spec secrets: the staged reports were not deleted"'
UNCHECKED_DELETION = (
    f"    if os.path.lexists(staged):\n{UNDELETED}",
    f"    if False:\n{UNDELETED}",
)
UNLOCKED = ("        fcntl.flock(descriptor, fcntl.LOCK_EX)\n", "")
LOCK_WAIT = 1.0


def contended_publish(module) -> tuple[bool, list[str]]:
    """Publish while another masker holds the reports dir, its ``TEMP`` file not yet renamed.

    Args:
        module: the loaded masker.

    Returns:
        Whether ``publish`` still waited after ``LOCK_WAIT`` seconds, and the
        names in the reports dir once the other masker renamed its file and
        let go of the dir.
    """
    with tempfile.TemporaryDirectory() as tmp:
        staged, reports = Path(tmp) / "staged", Path(tmp) / "reports"
        staged.mkdir()
        reports.mkdir()
        (staged / "mine.xml").write_text("mine")
        temp = reports / f"{module.TEMP}other"
        temp.write_text("other")
        held = os.open(reports, os.O_RDONLY | os.O_DIRECTORY)
        fcntl.flock(held, fcntl.LOCK_EX)
        publishing = threading.Thread(
            target=module.publish, args=(staged, reports, module.windows([RAW]))
        )
        publishing.start()
        try:
            publishing.join(LOCK_WAIT)
            waited = publishing.is_alive()
            with suppress(FileNotFoundError):
                temp.replace(reports / "other.xml")
        finally:
            os.close(held)
            publishing.join()
        return waited, sorted(os.listdir(reports))


def attempt(module, staged: Path, reports: Path) -> str:
    """Publish once and name the outcome.

    Args:
        module: the loaded masker.
        staged: the masked staged reports.
        reports: the reports dir.

    Returns:
        ``refused`` when ``publish`` raised, else ``published``.
    """
    try:
        module.publish(staged, reports, module.windows([RAW]))
    except (OSError, module.spec_secrets.SpecSecretsError):
        return "refused"
    return "published"


def fifo_publish(module) -> tuple[str, str, bytes]:
    """Publish a report onto a FIFO an earlier run left in the reports dir, a reader on it.

    Args:
        module: the loaded masker.

    Returns:
        What ``attempt`` returns, ``fifo`` or the published text for what the
        name holds afterwards, and what the reader got through the FIFO.
    """
    with tempfile.TemporaryDirectory() as tmp:
        staged, reports = Path(tmp) / "staged", Path(tmp) / "reports"
        staged.mkdir()
        reports.mkdir()
        (staged / "report.xml").write_text("ok")
        os.mkfifo(reports / "report.xml")
        reader = os.open(reports / "report.xml", os.O_RDONLY | os.O_NONBLOCK)
        try:
            outcome = attempt(module, staged, reports)
            try:
                got = os.read(reader, 64)
            except BlockingIOError:
                got = b""
        finally:
            os.close(reader)
        held = reports / "report.xml"
        kind = "fifo" if stat.S_ISFIFO(held.lstat().st_mode) else scratch_text(held)
        return outcome, kind, got


def hard_linked_publish(module) -> tuple[str, str, str]:
    """Publish a report onto a hard link an earlier run left to a file outside.

    Args:
        module: the loaded masker.

    Returns:
        What ``attempt`` returns, the text of the file outside and the text
        of the published report afterwards.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staged, reports, outside = root / "staged", root / "reports", root / "kept"
        staged.mkdir()
        reports.mkdir()
        (staged / "report.xml").write_text("masked")
        outside.write_text("kept")
        os.link(outside, reports / "report.xml")
        outcome = attempt(module, staged, reports)
        return outcome, scratch_text(outside), scratch_text(reports / "report.xml")


def linked_publish(module) -> tuple[str, list[str]]:
    """Publish a report below a reports subdir an earlier run left as a link.

    Args:
        module: the loaded masker.

    Returns:
        ``refused`` when ``publish`` raised, else ``published``, and the
        names the link's target holds afterwards.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staged, reports, outside = root / "staged", root / "reports", root / "outside"
        (staged / "sub").mkdir(parents=True)
        (staged / "sub" / "report.xml").write_text("ok")
        reports.mkdir()
        outside.mkdir()
        (reports / "sub").symlink_to(outside)
        try:
            module.publish(staged, reports, module.windows([RAW]))
        except OSError:
            outcome = "refused"
        else:
            outcome = "published"
        return outcome, sorted(os.listdir(outside))


def reused_modes(module) -> dict[str, int]:
    """Publish into a reports dir and subdir that already exist with mode 2775.

    Args:
        module: the loaded masker.

    Returns:
        The mode bits of the reports dir and its subdir afterwards.
    """
    with tempfile.TemporaryDirectory() as tmp:
        staged, reports = Path(tmp) / "staged", Path(tmp) / "reports"
        (staged / "sub").mkdir(parents=True)
        (staged / "sub" / "a.xml").write_text("ok")
        (staged / "top.xml").write_text("ok")
        (reports / "sub").mkdir(parents=True)
        for path in (reports, reports / "sub"):
            path.chmod(0o2775)
        module.publish(staged, reports, module.windows([RAW]))
        return {
            name: stat.S_IMODE((reports / name).lstat().st_mode)
            for name in (".", "sub")
        }


def undeletable_settle(module) -> tuple[int, list[str]]:
    """Settle staged reports below a ``0555`` dir, as a container leaves one in a non-root rerun.

    Args:
        module: the loaded masker.

    Returns:
        What ``settle`` returns and the names published below ``locked``.
    """
    with tempfile.TemporaryDirectory() as tmp:
        run, reports = Path(tmp) / "run", Path(tmp) / "reports"
        locked = run / "reports" / "locked"
        locked.mkdir(parents=True)
        (locked / "report.xml").write_text("ok")
        locked.chmod(0o555)
        try:
            code = module.settle(run, reports, module.windows([RAW]), True, "")
        finally:
            locked.chmod(0o755)
        return code, sorted(os.listdir(reports / "locked"))


def unproven_settle(module) -> tuple[int, str]:
    """Settle a run whose container was not proven gone, its ``.cid`` naming ``CONTAINER_ID``.

    Args:
        module: the loaded masker.

    Returns:
        What ``settle`` returns and what it printed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        run, reports = Path(tmp) / "run", Path(tmp) / "reports"
        (run / "reports").mkdir(parents=True)
        (run / ".cid").write_text(f"{CONTAINER_ID}\n")
        printed = io.StringIO()
        with redirect_stderr(printed):
            code = module.settle(run, reports, module.windows([RAW]), False, "")
        return code, printed.getvalue()


def refused_scrub(module, linked: bool) -> tuple[int, str]:
    """Scrub a run directory the helper refuses, its ``.cid`` naming ``CONTAINER_ID``.

    Args:
        module: the loaded masker.
        linked: whether ``.cid`` is instead a link to a file holding
            ``LINKED_VALUE``, a name the container check would accept.

    Returns:
        What ``main`` returns and what it printed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        run, reports = Path(tmp) / "run", Path(tmp) / "reports"
        run.mkdir()
        if linked:
            (Path(tmp) / "value").write_text(LINKED_VALUE)
            (run / ".cid").symlink_to(Path(tmp) / "value")
        else:
            (run / ".cid").write_text(f"{CONTAINER_ID}\n")
        printed = io.StringIO()
        with redirect_stderr(printed):
            code = module.main(
                ["spec_secrets_mask.py", "scrub", str(run), str(reports), "docker"]
            )
        return code, printed.getvalue()


class TestSpecSecretsPublish(unittest.TestCase):
    def test_a_container_that_may_still_run_is_named_by_its_id(self) -> None:
        code, printed = unproven_settle(load_masker())
        self.assertEqual(code, 1)
        self.assertIn(f"container {CONTAINER_ID} may still run", printed)

    def test_a_refused_scrub_names_the_container_never_a_linked_value(self) -> None:
        module = load_masker()
        code, printed = refused_scrub(module, linked=False)
        self.assertEqual(code, 1)
        self.assertIn(f"container {CONTAINER_ID} may still run", printed)
        code, printed = refused_scrub(module, linked=True)
        self.assertEqual((code, LINKED_VALUE in printed), (1, False))
        self.assertIn("container unnamed may still run", printed)

    @unittest.skipIf(os.geteuid() == 0, "root deletes below a 0555 dir")
    def test_staged_reports_that_cannot_be_deleted_fail_the_settlement(self) -> None:
        self.assertEqual(undeletable_settle(load_masker()), (1, ["report.xml"]))

    def test_a_link_below_the_reports_dir_is_refused_and_never_written_through(
        self,
    ) -> None:
        self.assertEqual(linked_publish(load_masker()), ("refused", []))

    def test_reused_report_dirs_get_exactly_0755(self) -> None:
        self.assertEqual(reused_modes(load_masker()), {".": 0o755, "sub": 0o755})

    def test_a_fifo_or_hard_link_in_the_reports_dir_is_replaced_never_opened(
        self,
    ) -> None:
        self.assertEqual(fifo_publish(load_masker()), ("published", "ok", b""))
        self.assertEqual(
            hard_linked_publish(load_masker()), ("published", "kept", "masked")
        )

    def test_a_publish_waits_for_another_masker_publishing_into_the_same_dir(
        self,
    ) -> None:
        self.assertEqual(
            contended_publish(load_masker()), (True, ["mine.xml", "other.xml"])
        )


class TestSpecSecretsPublishNegativeControls(unittest.TestCase):
    def test_a_publish_that_drops_a_live_maskers_temp_file_is_caught(self) -> None:
        self.assertEqual(
            contended_publish(load_masker(UNLOCKED)), (False, ["mine.xml"])
        )

    def test_a_message_that_drops_the_container_id_is_caught(self) -> None:
        _code, printed = unproven_settle(load_masker(UNNAMED))
        self.assertNotIn(CONTAINER_ID, printed)

    @unittest.skipIf(os.geteuid() == 0, "root deletes below a 0555 dir")
    def test_a_settlement_that_ignores_a_failed_deletion_is_caught(self) -> None:
        self.assertEqual(
            undeletable_settle(load_masker(UNCHECKED_DELETION)), (0, ["report.xml"])
        )

    def test_a_publish_that_follows_an_intermediate_link_is_caught(self) -> None:
        self.assertEqual(
            linked_publish(load_masker(FOLLOWING)), ("published", ["report.xml"])
        )

    def test_a_publish_that_keeps_the_mode_of_a_reused_dir_is_caught(self) -> None:
        self.assertEqual(
            reused_modes(load_masker(KEPT_MODE)), {".": 0o2775, "sub": 0o2775}
        )

    def test_a_publish_that_opens_the_entry_under_the_name_is_caught(self) -> None:
        self.assertEqual(
            fifo_publish(load_masker(OPENING)), ("published", "fifo", b"ok")
        )
        self.assertEqual(
            hard_linked_publish(load_masker(OPENING)), ("published", "masked", "masked")
        )


if __name__ == "__main__":
    unittest.main()
