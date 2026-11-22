from __future__ import annotations

import importlib.util
import io
import os
import stat
import tempfile
import time
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout, suppress
from pathlib import Path

from utils.cache.files import read_text

from . import ROLE

HELPER = ROLE / "files" / "spec_secrets.py"
SENTINEL = "Sentinel-Value-9f3c"
BREAK_CHARS = (
    "\r",
    "\x0b",
    "\x0c",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    "\N{LINE SEPARATOR}",
    "\N{PARAGRAPH SEPARATOR}",
)
CONTROL_CHARS = ("\x01", "\t", "\x1f", "\x7f", "\x80", "\x9f")
SHORT = "short12"
TWO_DAYS = 2 * 86400
OWNER_GATE = "if os.geteuid() not in (0, uid):"


def load_helper(*replacements: tuple[str, str]):
    """Load ``spec_secrets.py``, which the role ships as a plain file.

    Args:
        *replacements: pairs of text the helper must hold exactly once and its
            replacement, for a negative control.

    Returns:
        A fresh module, so a test may change its constants.
    """
    source = read_text(str(HELPER))
    for old, new in replacements:
        if source.count(old) != 1:
            raise AssertionError(f"the helper no longer holds {old!r} once")
        source = source.replace(old, new)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / HELPER.name
        path.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("playwright_spec_secrets", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def run_helper(module, *args: str) -> tuple[int, str]:
    """Run one helper command and capture everything it prints.

    Args:
        module: the loaded helper.
        *args: the command and its arguments.

    Returns:
        The exit code and the joined stdout and stderr.
    """
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = module.main(["spec_secrets.py", *args])
    return code, out.getvalue() + err.getvalue()


def mine(module) -> Path:
    """Name the parent of this user's run directories.

    Args:
        module: the loaded helper, its ``PARENT`` moved to a scratch dir.

    Returns:
        ``PARENT-<uid>`` for this process's uid.
    """
    return module.parent(os.geteuid())


def split_bytes(module, directory: Path, rendered: bytes) -> tuple[int, str]:
    """Hand a rendered template to a run directory as the runner does and split it.

    Args:
        module: the loaded helper.
        directory: the run directory.
        rendered: the rendered template.

    Returns:
        The exit code and everything printed.
    """
    (directory / module.RENDERED).write_bytes(rendered)
    return run_helper(module, "split", str(directory))


def split_rendered(module, text: str) -> tuple[Path, int, str]:
    """Create a run directory and split a rendered template into it.

    Args:
        module: the loaded helper, its ``PARENT`` already moved to a scratch dir.
        text: the rendered template.

    Returns:
        The run directory, the exit code and everything printed.
    """
    directory = module.create()
    code, printed = split_bytes(module, directory, text.encode("utf-8"))
    return directory, code, printed


def aged(*paths: Path) -> None:
    """Date directories back two days, as a killed run leaves them.

    Args:
        *paths: the directories.
    """
    then = time.time() - TWO_DAYS
    for path in paths:
        os.utime(path, (then, then))


def parse_leak_violations(module) -> list[str]:
    """Hide a key-shaped fragment behind each line break other than LF.

    Args:
        module: the loaded helper.

    Returns:
        One message per break that splits a value, writes a file or prints text.
    """
    problems = []
    for char in BREAK_CHARS:
        for fragment in ("SEED_FRAGMENT", "seed_fragment"):
            with tempfile.TemporaryDirectory() as tmp:
                module.PARENT = Path(tmp) / "spec-secrets"
                rendered = f"#salt\nA_KEY={SENTINEL}{char}{fragment}=tail-long\n"
                directory, code, printed = split_rendered(module, rendered)
                shown = [t for t in (SENTINEL, fragment, "tail") if t in printed]
                written = sorted(path.name for path in directory.iterdir())
                if code != 1 or shown or written:
                    problems.append(f"{char!r}: rc {code}, printed {shown}, {written}")
    return problems


def control_violations(module) -> list[str]:
    """Split a value holding each C0 or C1 control character or DEL.

    Args:
        module: the loaded helper.

    Returns:
        One message per character that is accepted, writes a file, prints a
        piece of the value or fails without naming the key.
    """
    problems = []
    for char in CONTROL_CHARS:
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            rendered = f"A_KEY={SENTINEL}{char}tail-long\n"
            directory, code, printed = split_rendered(module, rendered)
            shown = [t for t in (SENTINEL, "tail") if t in printed]
            written = sorted(os.listdir(directory))
            if code != 1 or "A_KEY" not in printed or shown or written:
                problems.append(f"{char!r}: rc {code}, printed {shown}, {written}")
    return problems


def owned_runs(module) -> list[str]:
    """Open a run directory of this user as each kind of caller.

    Args:
        module: the loaded helper.

    Returns:
        Per case, ``accepted`` or ``refused``: this user, root, another user,
        and root on the run below a parent named after a uid that does not
        own it.
    """

    def opened(euid: int, run: Path) -> str:
        with unittest.mock.patch.object(module.os, "geteuid", return_value=euid):
            try:
                os.close(module.open_run(run))
            except module.SpecSecretsError:
                return "refused"
        return "accepted"

    with tempfile.TemporaryDirectory() as tmp:
        module.PARENT = Path(tmp) / "spec-secrets"
        directory = module.create()
        uid = os.geteuid()
        found = [opened(euid, directory) for euid in (uid, 0, uid + 4242)]
        renamed = module.parent(uid + 1)
        mine(module).rename(renamed)
        return [*found, opened(0, renamed / directory.name)]


def confinement_violations(module) -> list[str]:
    """Point a run entry at a directory outside ``PARENT`` and split and prune it.

    Args:
        module: the loaded helper.

    Returns:
        One message per file the helper touched outside ``PARENT``.
    """
    with tempfile.TemporaryDirectory() as tmp:
        module.PARENT = Path(tmp) / "spec-secrets"
        module.create()
        outside = Path(tmp) / "outside"
        outside.mkdir(mode=0o700)
        (outside / "keep").write_text("")
        link = mine(module) / "run.link"
        link.symlink_to(outside)
        aged(outside)
        code, printed = run_helper(module, "split", str(link))
        with suppress(OSError):
            run_helper(module, "prune")
        left = sorted(path.name for path in outside.iterdir())
        problems = [] if code == 1 and "refused" in printed else [f"split rc {code}"]
        if left != ["keep"]:
            problems.append(f"the helper left {left} outside the parent")
        return problems


def file_violations(directory: Path, expected: dict[str, str]) -> list[str]:
    """Check the written secrets: names, modes, owner and content.

    Args:
        directory: the spec secrets directory.
        expected: every key with the value its file must hold.

    Returns:
        One message per broken expectation, naming keys only.
    """
    problems = []
    if stat.S_IMODE(directory.lstat().st_mode) != 0o700:
        problems.append("the directory is not 0700")
    present = sorted(path.name for path in directory.iterdir())
    if present != sorted(expected):
        problems.append(f"the directory holds {present}")
    for key, value in expected.items():
        path = directory / key
        if not path.exists():
            continue
        info = path.lstat()
        if stat.S_IMODE(info.st_mode) != 0o400:
            problems.append(f"{key} has mode {stat.S_IMODE(info.st_mode):04o}")
        if info.st_uid != os.geteuid():
            problems.append(f"{key} is not owned by the writing user")
        if path.read_bytes().decode("utf-8") != value:  # nocheck: cache-read
            problems.append(f"{key} holds the wrong value")
    return problems


def short_value_split(module) -> tuple[int, str, list[str]]:
    """Split a template whose second value is shorter than the masker hides.

    Args:
        module: the loaded helper.

    Returns:
        The exit code, everything printed and the files left.
    """
    with tempfile.TemporaryDirectory() as tmp:
        module.PARENT = Path(tmp) / "spec-secrets"
        rendered = f"LONG_KEY={SENTINEL}\nSHORT_KEY={SHORT}\n"
        directory, code, printed = split_rendered(module, rendered)
        return code, printed, sorted(path.name for path in directory.iterdir())


def pruned(module) -> list[str]:
    """Prune a parent holding a live, a killed, a foreign and an unrelated dir.

    Args:
        module: the loaded helper.

    Returns:
        The names left below the parent.
    """
    with tempfile.TemporaryDirectory() as tmp:
        module.PARENT = Path(tmp) / "spec-secrets"
        live, _, _ = split_rendered(module, f"A_KEY={SENTINEL}\n")
        killed, _, _ = split_rendered(module, f"A_KEY={SENTINEL}\n")
        (mine(module) / "keep").mkdir(mode=0o700)
        (mine(module) / "run.foreign").mkdir(mode=0o755)
        aged(killed, mine(module) / "keep", mine(module) / "run.foreign")
        with suppress(OSError):
            run_helper(module, "prune")
        names = {live.name: "live", killed.name: "killed"}
        return sorted(names.get(name, name) for name in os.listdir(mine(module)))


class TestSpecSecretsHelper(unittest.TestCase):
    def test_each_uid_opens_its_own_runs_and_root_those_of_any_uid(self) -> None:
        module = load_helper()
        self.assertEqual(
            owned_runs(module), ["accepted", "accepted", "refused", "refused"]
        )
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            module.create()
            login = os.geteuid()
            with unittest.mock.patch.object(module.os, "geteuid", return_value=0):
                self.assertEqual(module.users(), sorted({0, login}))

    def test_a_value_holding_a_control_character_is_refused_by_its_key(
        self,
    ) -> None:
        self.assertEqual(control_violations(load_helper()), [])

    def test_the_helper_writes_0400_files_and_prints_a_count_only(self) -> None:
        module = load_helper()
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            directory, code, printed = split_rendered(
                module,
                f"#salt\n\nE2E_PASSWORD={SENTINEL}\nCLIENT_KEY={SENTINEL}=tail \n",
            )
            self.assertEqual((code, printed), (0, "spec secrets files written: 2\n"))
            expected = {"E2E_PASSWORD": SENTINEL, "CLIENT_KEY": f"{SENTINEL}=tail "}
            self.assertEqual(file_violations(directory, expected), [])

    def test_the_helper_names_a_bad_line_by_number_only(self) -> None:
        module = load_helper()
        cases = (
            (
                f"A_KEY={SENTINEL}\nA_KEY=other-value\n".encode(),
                "line 2 repeats an earlier key",
            ),
            (f"lower_key={SENTINEL}\n".encode(), "line 1 is not KEY=VALUE"),
            (f"A_KEY={SENTINEL}\n{SENTINEL}\n".encode(), "line 2 is not KEY=VALUE"),
            (f"{'K' * 256}={SENTINEL}\n".encode(), "line 1 is not KEY=VALUE"),
            (b"A_KEY=\xff\n", "not UTF-8"),
            (
                f"A_KEY={SENTINEL}\nSHORT_KEY={SHORT}\n".encode(),
                "line 2 holds a value of fewer than 8 bytes",
            ),
        )
        for rendered, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                module.PARENT = Path(tmp) / "spec-secrets"
                directory = module.create()
                code, printed = split_bytes(module, directory, rendered)
                self.assertEqual(code, 1)
                self.assertIn(message, printed)
                for text in (SENTINEL, SHORT, "A_KEY", "lower_key", "other", "K" * 20):
                    self.assertNotIn(text, printed)
                self.assertEqual(list(directory.iterdir()), [])

    def test_no_line_break_but_lf_splits_a_value(self) -> None:
        self.assertEqual(parse_leak_violations(load_helper()), [])

    def test_a_refused_run_directory_is_never_touched(self) -> None:
        module = load_helper()
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            directory = module.create()
            directory.chmod(0o755)
            code, printed = split_bytes(
                module, directory, f"A_KEY={SENTINEL}\n".encode()
            )
            self.assertEqual(code, 1)
            self.assertIn("expected 0700", printed)
            self.assertEqual([p.name for p in directory.iterdir()], [module.RENDERED])
        self.assertEqual(confinement_violations(load_helper()), [])

    def test_create_makes_a_0700_run_directory_and_takes_no_arguments(self) -> None:
        module = load_helper()
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            code, printed = run_helper(module, "create")
            directory = Path(printed.strip())
            self.assertEqual((code, directory.parent), (0, mine(module)))
            self.assertEqual(mine(module).name, f"spec-secrets-{os.geteuid()}")
            self.assertTrue(directory.name.startswith(module.PREFIX))
            for path in (mine(module), directory):
                self.assertEqual(stat.S_IMODE(path.lstat().st_mode), 0o700)
            self.assertEqual(run_helper(module, "create", "1", "0")[0], 2)

    def test_prune_removes_only_a_killed_run_and_leaves_a_live_one(self) -> None:
        module = load_helper()
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            self.assertEqual(run_helper(module, "prune"), (0, "nothing to prune\n"))
        self.assertEqual(pruned(module), ["keep", "live", "run.foreign"])

    def test_a_foreign_parent_or_location_is_never_touched(self) -> None:
        module = load_helper()
        for kind in ("planted", "link"):
            with self.subTest(parent=kind), tempfile.TemporaryDirectory() as tmp:
                module.PARENT = Path(tmp) / "spec-secrets"
                target = Path(tmp) / "target"
                target.mkdir()
                target.chmod(0o755 if kind == "planted" else 0o700)
                (target / "run.keep").mkdir(mode=0o700)
                aged(target / "run.keep")
                if kind == "planted":
                    target.rename(mine(module))
                    target = mine(module)
                else:
                    mine(module).symlink_to(target)
                code, printed = run_helper(module, "prune")
                self.assertEqual(code, 0)
                self.assertIn("prune skipped", printed)
                code, printed = run_helper(module, "create")
                self.assertEqual(code, 1)
                self.assertIn(f"rm -rf -- {mine(module)} so the next run", printed)
                self.assertEqual(run_helper(module, "prune", str(target))[0], 2)
                code, printed = run_helper(module, "split", str(target))
                self.assertEqual(code, 1)
                self.assertIn("not a run directory", printed)
                self.assertEqual(os.listdir(target), ["run.keep"])


class TestSpecSecretsHelperNegativeControls(unittest.TestCase):
    def test_a_helper_that_opens_another_users_run_is_caught(self) -> None:
        trusting = load_helper((OWNER_GATE, "if False:"))
        self.assertEqual(owned_runs(trusting)[2], "accepted")

    def test_a_split_that_takes_a_control_character_is_caught(self) -> None:
        accepting = load_helper(("if CONTROL.search(value):", "if False:"))
        self.assertEqual(len(control_violations(accepting)), len(CONTROL_CHARS))

    def test_the_old_line_split_is_caught_leaking_a_value(self) -> None:
        module = load_helper(('text.split("\\n")', "text.splitlines()"))
        self.assertEqual(len(parse_leak_violations(module)), len(BREAK_CHARS))

    def test_a_value_too_short_to_mask_that_is_accepted_is_caught(self) -> None:
        code, printed, written = short_value_split(load_helper())
        self.assertEqual((code, written), (1, []))
        self.assertNotIn(SHORT, printed)
        accepting = load_helper(
            ('if len(normalized(value.encode("utf-8"))) < MASK_MIN:', "if False:")
        )
        self.assertEqual(
            short_value_split(accepting)[::2], (0, ["LONG_KEY", "SHORT_KEY"])
        )

    def test_a_split_that_follows_a_link_out_of_the_parent_is_caught(self) -> None:
        module = load_helper(
            (
                "OPEN_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW",
                "OPEN_DIR = os.O_RDONLY | os.O_DIRECTORY",
            )
        )
        self.assertNotEqual(confinement_violations(module), [])

    def test_a_prune_that_takes_a_live_or_a_foreign_run_is_caught(self) -> None:
        ageless = load_helper(
            ("if time.time() - changed < STALE_SECONDS:", "if False:")
        )
        self.assertEqual(pruned(ageless), ["keep", "run.foreign"])
        ownerless = load_helper(
            (
                "run = open_owned(name, dir_fd=top, uid=uid)",
                "run = os.open(name, os.O_RDONLY, dir_fd=top)",
            )
        )
        self.assertEqual(pruned(ownerless), ["keep", "live"])

    def test_a_split_that_keeps_the_handed_template_is_caught(self) -> None:
        module = load_helper(("os.unlink(RENDERED, dir_fd=run)", "None"))
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            directory, code, _ = split_rendered(module, f"A_KEY={SENTINEL}\n")
            self.assertEqual(code, 0)
            self.assertNotEqual(file_violations(directory, {"A_KEY": SENTINEL}), [])

    def test_a_readable_file_mode_is_caught(self) -> None:
        module = load_helper()
        module.FILE_MODE = 0o644
        with tempfile.TemporaryDirectory() as tmp:
            module.PARENT = Path(tmp) / "spec-secrets"
            directory, code, _ = split_rendered(module, f"A_KEY={SENTINEL}\n")
            self.assertEqual(code, 0)
            self.assertEqual(
                file_violations(directory, {"A_KEY": SENTINEL}),
                ["A_KEY has mode 0644"],
            )


if __name__ == "__main__":
    unittest.main()
