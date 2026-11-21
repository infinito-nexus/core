import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/dsk-code/files/shell/protect-code-oss.sh"
APPS = "user.slice/user-1000.slice/user@1000.service/app.slice"
STUB = '#!/bin/sh\nprintf "%s\\n" "$@" > "$0.args"\n'


class ProtectCodeOssTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cgroups = self.root / "cgroup"
        self.proc = self.root / "proc"
        self.library = self.root / "lib"
        self.stubs = self.root / "bin"
        self.electron = self.binary(self.library / "electron42/electron")
        self.shell = self.binary(self.root / "other/bash")
        self.ripgrep = self.binary(self.root / "other/rg")
        for name in ("renice", "ionice"):
            stub = self.stubs / name
            self.binary(stub).write_text(STUB)
            stub.chmod(0o755)

    def binary(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path

    def scope(self, name, *pids):
        procs = self.cgroups / APPS / name / "cgroup.procs"
        procs.parent.mkdir(parents=True, exist_ok=True)
        procs.write_text("".join(f"{pid}\n" for pid in pids))

    def process(self, pid, exe, comm, score, *argv):
        directory = self.proc / str(pid)
        directory.mkdir(parents=True)
        (directory / "exe").symlink_to(exe)
        (directory / "comm").write_text(f"{comm}\n")
        (directory / "cmdline").write_bytes(
            b"".join(arg.encode() + b"\0" for arg in (str(exe), *argv))
        )
        (directory / "oom_score_adj").write_text(f"{score}\n")
        return pid

    def run_script(self):
        subprocess.run(
            ["bash", str(SCRIPT), str(self.cgroups), str(self.proc), str(self.library)],
            check=True,
            capture_output=True,
            env={"PATH": f"{self.stubs}:{os.environ['PATH']}"},
        )

    def score(self, pid):
        path = self.proc / str(pid) / "oom_score_adj"
        return int(path.read_text())  # nocheck: cache-read

    def stub_args(self, name):
        return (self.stubs / f"{name}.args").read_text().split()  # nocheck: cache-read

    def test_only_the_editor_main_and_renderer_processes_are_shielded(self):
        main = self.process(101, self.electron, "code-oss", 0, "/usr/lib/code/code.mjs")
        renderer = self.process(102, self.electron, "electron", 300, "--type=renderer")
        self.scope("app-code-oss-1.scope", main, renderer)
        self.run_script()
        self.assertEqual(self.score(main), -900)
        self.assertEqual(self.score(renderer), -900)

    def test_a_renderer_with_a_rewritten_process_title_is_shielded(self):
        renderer = self.process(109, self.electron, "electron", 300)
        (self.proc / "109" / "cmdline").write_bytes(
            f"{self.electron} --type=renderer --enable-crash-reporter\0".encode()
        )
        self.scope("app-code-oss-1.scope", renderer)
        self.run_script()
        self.assertEqual(self.score(renderer), -900)

    def test_children_that_inherited_the_shield_are_reset_to_zero(self):
        pty_host = self.process(
            103,
            self.electron,
            "electron",
            -900,
            "--type=utility",
            "--utility-sub-type=node.mojom.NodeService",
        )
        language_server = self.process(
            104, self.electron, "electron", -900, "/usr/lib/code/server.js"
        )
        disguised = self.process(
            105, self.electron, "electron", -900, "--flag=--type=renderer"
        )
        shell = self.process(106, self.shell, "bash", -900)
        self.scope("app-code-oss-1.scope", pty_host, language_server, disguised, shell)
        self.run_script()
        for pid in (pty_host, language_server, disguised, shell):
            with self.subTest(pid=pid):
                self.assertEqual(self.score(pid), 0)

    def test_a_score_the_process_chose_itself_is_kept(self):
        build = self.process(107, self.shell, "make", 200)
        self.scope("app-code-oss-1.scope", build)
        self.run_script()
        self.assertEqual(self.score(build), 200)

    def test_a_user_named_scope_without_the_editor_binary_gets_no_shield(self):
        impostor = self.process(201, self.shell, "code-oss", 0)
        self.scope("app-x-code-oss-2.scope", impostor)
        self.run_script()
        self.assertEqual(self.score(impostor), 0)

    def test_processes_outside_the_editor_scopes_are_untouched(self):
        other = self.process(301, self.shell, "bash", -900)
        self.scope("app-firefox-3.scope", other)
        self.run_script()
        self.assertEqual(self.score(other), -900)

    def test_every_ripgrep_thread_is_idled_tolerating_vanished_pids(self):
        ripgrep = self.process(108, self.ripgrep, "rg", 0)
        for tid in (108, 110, 111):
            (self.proc / "108" / "task" / str(tid)).mkdir(parents=True)
        self.scope("app-code-oss-1.scope", 999, ripgrep)
        self.run_script()
        tids = ["108", "110", "111"]
        self.assertEqual(self.stub_args("renice"), ["-n", "19", "-p", *tids])
        self.assertEqual(self.stub_args("ionice"), ["-c", "3", "-t", "-p", *tids])

    def test_an_editor_running_a_replaced_electron_binary_keeps_the_shield(self):
        main = self.process(
            112,
            f"{self.electron} (deleted)",
            "code-oss",
            -900,
            "/usr/lib/code/code.mjs",
        )
        self.scope("app-code-oss-1.scope", main)
        self.run_script()
        self.assertEqual(self.score(main), -900)


if __name__ == "__main__":
    unittest.main()
