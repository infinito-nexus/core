from __future__ import annotations

import ctypes
import errno
import filecmp
import os
import platform
import signal
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

STAGE = PROJECT_ROOT / "scripts" / "install" / "stage.sh"
TIMEOUT_SECONDS = 60

AUDIT_ARCH = {"x86_64": 0xC000003E, "aarch64": 0xC00000B7}
SIGNAL_SYSCALLS = {
    "x86_64": (62, 200, 234, 129, 297, 424),
    "aarch64": (129, 130, 131, 138, 240, 424),
}


class _SockFilter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint),
    ]


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(_SockFilter))]


def _signal_ban_program(machine: str) -> list[_SockFilter]:
    ld_abs, jeq, ret = 0x20, 0x15, 0x06
    allow, deny = 0x7FFF0000, 0x00050000 | errno.EACCES
    numbers = SIGNAL_SYSCALLS[machine]
    program = [
        _SockFilter(ld_abs, 0, 0, 4),
        _SockFilter(jeq, 1, 0, AUDIT_ARCH[machine]),
        _SockFilter(ret, 0, 0, allow),
        _SockFilter(ld_abs, 0, 0, 0),
    ]
    for index, number in enumerate(numbers):
        program.append(_SockFilter(jeq, len(numbers) - index, 0, number))
    program.append(_SockFilter(ret, 0, 0, allow))
    program.append(_SockFilter(ret, 0, 0, deny))
    return program


def _ban_signals() -> None:
    program = _signal_ban_program(platform.machine())
    filters = (_SockFilter * len(program))(*program)
    fprog = _SockFprog(len(program), filters)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS failed")
    if libc.prctl(22, 2, ctypes.addressof(fprog), 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_SECCOMP failed")


def _run_without_signals(argv: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=_ban_signals,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)


def _tree(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def _stage(src: Path, dest: Path, *excludes: str) -> subprocess.CompletedProcess:
    return _run_without_signals(["bash", str(STAGE), str(src), str(dest), *excludes])


@unittest.skipUnless(
    platform.machine() in AUDIT_ARCH, "seccomp table covers x86_64 and aarch64"
)
class StageWithoutSignalsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.src = Path(self._tmp.name) / "src"
        self.dest = Path(self._tmp.name) / "dest"
        _tree(self.src, {"README.md": "readme\n", "pkg/a/data.yml": "- x\n"})

    def test_the_harness_refuses_every_signal(self):
        result = _run_without_signals(["bash", "-c", "kill -0 $$"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Permission denied", result.stderr)

    def test_staging_finishes_while_signals_are_refused(self):
        result = _stage(self.src, self.dest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            filecmp.cmp(
                self.src / "pkg/a/data.yml",
                self.dest / "pkg/a/data.yml",
                shallow=False,
            )
        )

    def test_a_name_pattern_drops_matches_at_every_depth(self):
        _tree(self.src, {".git/HEAD": "ref\n", "pkg/a/.git": "gitdir\n"})
        result = _stage(self.src, self.dest, ".git")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.dest / ".git").exists())
        self.assertFalse((self.dest / "pkg/a/.git").exists())
        self.assertTrue((self.dest / "pkg/a/data.yml").is_file())

    def test_a_path_pattern_drops_only_that_subtree(self):
        _tree(
            self.src,
            {"packaging/debian/control": "c\n", "packaging/arch/PKGBUILD": "p\n"},
        )
        result = _stage(self.src, self.dest, "packaging/debian")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.dest / "packaging/debian").exists())
        self.assertTrue((self.dest / "packaging/arch/PKGBUILD").is_file())

    def test_a_previous_workspace_is_replaced(self):
        _tree(self.dest, {"stale.txt": "old\n"})
        result = _stage(self.src, self.dest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.dest / "stale.txt").exists())

    def test_symlinks_stay_links(self):
        (self.src / "link").symlink_to("README.md")
        result = _stage(self.src, self.dest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.dest / "link").readlink(), Path("README.md"))

    def test_the_executable_bit_survives(self):
        script = self.src / "run.sh"
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
        result = _stage(self.src, self.dest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            stat.S_IMODE((self.dest / "run.sh").stat().st_mode) & stat.S_IXUSR
        )

    def test_a_missing_destination_is_rejected(self):
        result = _run_without_signals(["bash", str(STAGE), str(self.src)])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.dest.exists())


if __name__ == "__main__":
    unittest.main()
