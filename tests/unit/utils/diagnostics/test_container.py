"""Unit tests for utils/diagnostics/container.py: the best-effort
collectors, the DiD recursion (probe, self-copy, env wiring, tar pull,
depth bound) and the always-exit-1 contract."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import PROJECT_ROOT

RESCUE = PROJECT_ROOT / "utils" / "diagnostics" / "container.py"


def _load():
    spec = importlib.util.spec_from_file_location("rescue", RESCUE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cp(cmd, rc=0, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(cmd, rc, stdout, stderr)


class HelperTests(unittest.TestCase):
    def test_sanitize_replaces_unsafe_chars(self):
        mod = _load()
        self.assertEqual(mod.sanitize("a/b:c d"), "a_b_c_d")
        self.assertEqual(mod.sanitize("ok-1.2_x"), "ok-1.2_x")

    def test_list_lines_empty_on_failure(self):
        mod = _load()
        with mock.patch.object(mod, "run", return_value=_cp([], rc=1, stdout=b"x\n")):
            self.assertEqual(mod.list_lines(["c"]), [])
        with mock.patch.object(mod, "run", return_value=_cp([], stdout=b"a\n\nb\n")):
            self.assertEqual(mod.list_lines(["c"]), ["a", "b"])

    def test_run_never_raises_on_missing_binary(self):
        mod = _load()
        result = mod.run(["/does/not/exist-xyz"])
        self.assertEqual(result.returncode, 124)


class CollectTests(unittest.TestCase):
    def test_collect_host_writes_meta(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(
                mod, "run", return_value=_cp([], stdout=b"myhost\n")
            ):
                mod.collect_host(out, "app", "ctx", "STAMP")
            meta = (
                out / "meta.txt"
            ).read_text()  # nocheck: cache-read - tempdir fixture
            self.assertIn("application_id: app", meta)
            self.assertIn("context: ctx", meta)
            self.assertIn("host: myhost", meta)

    def test_collect_local_dumps_copies_role_evidence(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out"
            out.mkdir()
            dumps = Path(td) / "dumps"
            (dumps / "pg").mkdir(parents=True)
            (dumps / "pg" / "pg_hba.conf").write_text("evidence")
            with mock.patch.object(mod, "_LOCAL_DUMPS_DIR", str(dumps)):
                mod.collect_local_dumps(out)
            self.assertEqual(
                (
                    out / "local-dumps" / "pg" / "pg_hba.conf"
                ).read_text(),  # nocheck: cache-read - tempdir fixture
                "evidence",
            )

    def test_collect_local_dumps_skips_own_output_subtree(self):
        """out lives under the dump dir, so the copy must not descend into
        its own growing destination (ENAMETOOLONG regression)."""
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "dumps"
            out = src / "app" / "stamp"
            out.mkdir(parents=True)
            (src / "pg_hba.txt").write_text("evidence")
            (out / "meta.txt").write_text("snapshot")
            with mock.patch.object(mod, "_LOCAL_DUMPS_DIR", str(src)):
                mod.collect_local_dumps(out)
            dumps = out / "local-dumps"
            self.assertTrue((dumps / "pg_hba.txt").is_file())
            self.assertFalse((dumps / "app").exists())
            self.assertFalse((dumps / "local-dumps").exists())

    def test_collect_local_dumps_tolerates_missing_dir(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(mod, "_LOCAL_DUMPS_DIR", str(Path(td) / "absent")):
                mod.collect_local_dumps(out)
            self.assertFalse((out / "local-dumps").exists())

    def test_collect_runtime_captures_per_container_artifacts(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)

            def fake_run(cmd, **kw):
                if cmd[-1] == "{{.Names}}" and "ps" in cmd:
                    return _cp(cmd, stdout=b"web/1\n")
                if cmd[-1] == "{{.Name}}":
                    return _cp(cmd, stdout=b"svc1\n")
                return _cp(cmd, stdout=b"data")

            with mock.patch.object(mod, "run", side_effect=fake_run):
                containers, services = mod.collect_runtime(out, "docker")
            self.assertEqual(containers, ["web/1"])
            self.assertEqual(services, ["svc1"])
            self.assertTrue((out / "containers" / "web_1.log").is_file())
            self.assertTrue((out / "containers" / "web_1.inspect.json").is_file())
            self.assertTrue((out / "services" / "svc1.log").is_file())
            self.assertFalse(
                (out / "containers" / "web_1.pg_stat_activity.txt").is_file()
            )

    def test_collect_runtime_captures_daemon_journal_and_kill_markers(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            calls: list[list[str]] = []

            def fake_run(cmd, **kw):
                calls.append(cmd)
                if cmd and cmd[-1] in ("{{.Names}}", "{{.Name}}"):
                    return _cp(cmd, stdout=b"")
                return _cp(cmd, stdout=b"data")

            with mock.patch.object(mod, "run", side_effect=fake_run):
                mod.collect_runtime(out, "docker")

            journalctls = [c for c in calls if c and c[0] == "journalctl"]
            self.assertTrue(
                any("-t" in c and "infinito-kill" in c for c in journalctls),
                f"kill-marker capture missing: {journalctls}",
            )
            self.assertTrue(
                any("docker" in c and "containerd" in c for c in journalctls),
                f"daemon-journal capture missing: {journalctls}",
            )
            base = out / "containers"
            self.assertTrue((base / "_kill-markers.txt").is_file())
            self.assertTrue((base / "_daemon-journal.txt").is_file())

    def test_collect_runtime_captures_pg_stat_activity_for_postgres(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)

            def fake_run(cmd, **kw):
                if cmd[-1] == "{{.Names}}" and "ps" in cmd:
                    return _cp(cmd, stdout=b"postgres_postgres.1.abc\n")
                if cmd[-1] == "{{.Name}}":
                    return _cp(cmd, stdout=b"")
                return _cp(cmd, stdout=b"data")

            with mock.patch.object(mod, "run", side_effect=fake_run):
                mod.collect_runtime(out, "docker")
            base = out / "containers"
            self.assertTrue(
                (base / "postgres_postgres.1.abc.pg_stat_activity.txt").is_file()
            )
            self.assertTrue(
                (base / "postgres_postgres.1.abc.pg_connections.txt").is_file()
            )


class RecurseTests(unittest.TestCase):
    def test_depth_bound_stops_recursion(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(mod.recurse(Path(td), "docker", "app", "", 3, 3, "S"), 0)

    def test_recurse_skips_containers_without_runtime(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:

            def fake_run(cmd, **kw):
                if cmd[-1] == "{{.Names}}":
                    return _cp(cmd, stdout=b"plain\n")
                return _cp(cmd, rc=1)

            with mock.patch.object(mod, "run", side_effect=fake_run):
                self.assertEqual(
                    mod.recurse(Path(td), "docker", "app", "", 0, 3, "S"), 0
                )

    def test_recurse_copies_self_and_pulls_nested_tar(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            calls: list[list[str]] = []

            def fake_run(cmd, **kw):
                calls.append(cmd)
                if cmd[-1] == "{{.Names}}":
                    return _cp(cmd, stdout=b"node1\n")
                if cmd[:2] == ["docker", "exec"] and "tar" in cmd:
                    return _cp(cmd, stdout=b"TARBYTES")
                return _cp(cmd)

            with mock.patch.object(mod, "run", side_effect=fake_run):
                nested = mod.recurse(out, "docker", "app", "ctx", 0, 3, "S")

            self.assertEqual(nested, 1)
            copy_call = next(c for c in calls if "cat >" in " ".join(c))
            self.assertIn("node1", copy_call)
            nested_exec = next(c for c in calls if "python3" in c)
            env_args = " ".join(nested_exec)
            self.assertIn("RESCUE_DEPTH=1", env_args)
            self.assertIn("RESCUE_MAX_DEPTH=3", env_args)
            self.assertIn("INFINITO_RESCUE_DIAGNOSTICS_DIR=", env_args)
            extract = next(c for c in calls if c[:2] == ["tar", "-C"])
            self.assertIn(str(out / "containers" / "node1" / "nested"), extract)
            self.assertTrue(any("rm" in c for c in calls))


class MainTests(unittest.TestCase):
    def test_main_requires_output_dir(self):
        mod = _load()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INFINITO_RESCUE_DIAGNOSTICS_DIR", None)
            self.assertEqual(mod.main(["rescue.py"]), 1)

    def test_main_always_exits_one_and_writes_snapshot(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            env = {"INFINITO_RESCUE_DIAGNOSTICS_DIR": td}
            with (
                mock.patch.dict(os.environ, env),
                mock.patch.object(mod, "runtime_bin", return_value=None),
                mock.patch.object(mod, "run", return_value=_cp([], stdout=b"h\n")),
            ):
                self.assertEqual(mod.main(["rescue.py", "app", "ctx"]), 1)
            snapshots = list(Path(td).glob("app-*"))
            self.assertEqual(len(snapshots), 1)
            self.assertTrue((snapshots[0] / "meta.txt").is_file())


if __name__ == "__main__":
    unittest.main()
