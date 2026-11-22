from __future__ import annotations

import os
import stat
import tempfile
import unittest
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


class TestSpecSecretsPublish(unittest.TestCase):
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


class TestSpecSecretsPublishNegativeControls(unittest.TestCase):
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
