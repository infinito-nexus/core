"""Unit tests for utils/diagnostics/container.py: the best-effort
collectors, the DiD recursion (probe, self-copy, env wiring, tar pull,
cycle cut) and the always-exit-1 contract."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.paths import read_group_path

from . import PROJECT_ROOT

RESCUE = PROJECT_ROOT / "utils" / "diagnostics" / "container.py"
_ENV = mock.patch.dict(
    os.environ,
    {"INFINITO_DNS53_SAMPLER_LOG": read_group_path("FILE_DNS53_SAMPLER_LOG")},
)


def setUpModule():
    _ENV.start()


def tearDownModule():
    _ENV.stop()


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

    def test_source_name_keeps_the_path_readable(self):
        mod = _load()
        self.assertEqual(mod.source_name("/proc/net/udp6"), "proc-net-udp6.txt")
        self.assertEqual(mod.source_name("/etc/resolv.conf"), "etc-resolv-conf.txt")
        self.assertEqual(
            mod.source_name("/proc/net/stat/nf_conntrack"),
            "proc-net-stat-nf-conntrack.txt",
        )

    def test_run_never_raises_on_missing_binary(self):
        mod = _load()
        result = mod.run(["/does/not/exist-xyz"])
        self.assertEqual(result.returncode, 124)

    def test_a_silent_failure_records_its_exit_status(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(mod, "run", return_value=_cp([], rc=2)):
                mod.capture(out, "probe.txt", ["getent", "hosts", "example.org"])
            probe = (
                out / "probe.txt"
            ).read_text()  # nocheck: cache-read - tempdir fixture
            self.assertEqual(probe, "[no output, exit 2]\n")

    def test_a_full_disk_is_announced_on_stderr(self):
        mod = _load()
        err = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as td,
            mock.patch.object(
                Path,
                "write_bytes",
                side_effect=OSError(28, "No space left on device"),
            ),
            contextlib.redirect_stderr(err),
        ):
            mod.write(Path(td) / "x.txt", b"data")
        self.assertIn("No space left on device", err.getvalue())


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

    def test_collect_host_refuses_to_run_without_the_sampler_log_variable(self):
        mod = _load()
        with (
            tempfile.TemporaryDirectory() as td,
            mock.patch.dict(os.environ, {}, clear=False),
            mock.patch.object(mod, "run", return_value=_cp([], stdout=b"h\n")),
        ):
            os.environ.pop("INFINITO_DNS53_SAMPLER_LOG", None)
            with self.assertRaises(KeyError):
                mod.collect_host(Path(td), "app", "ctx", "STAMP")

    def test_each_probed_name_gets_its_own_verdict(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(
                mod, "run", return_value=_cp([], stdout=b"")
            ) as runner:
                mod.collect_host(out, "app", "ctx", "STAMP")
            probes = [
                call.args[0]
                for call in runner.call_args_list
                if call.args[0][:2] == ["getent", "hosts"]
            ]
            self.assertTrue(probes)
            for cmd in probes:
                self.assertEqual(len(cmd), 3, f"one name per probe, not {cmd[2:]}")
            self.assertTrue((out / "resolve-deb-debian-org.txt").is_file())

    def test_every_nameserver_is_asked_directly_where_a_tool_exists(self):
        mod = _load()
        resolv = b"search lan\nnameserver 10.0.0.1\nnameserver 10.0.0.2\n"
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with (
                mock.patch.object(
                    mod.shutil, "which", side_effect=lambda b: b == "dig"
                ),
                mock.patch.object(mod, "run", return_value=_cp([], stdout=resolv)),
            ):
                mod.collect_resolver_probes(out)
            self.assertTrue((out / "resolve-ghcr-io-via-10-0-0-2.txt").is_file())
            self.assertTrue((out / "resolve-ghcr-io.txt").is_file())

    def test_daemon_json_dns_servers_are_probed_and_deduped(self):
        mod = _load()

        def fake_run(cmd, **_kw):
            if cmd == ["cat", "/etc/resolv.conf"]:
                return _cp(cmd, stdout=b"nameserver 127.0.0.1\n")
            if cmd == ["cat", "/etc/docker/daemon.json"]:
                return _cp(cmd, stdout=b'{"dns": ["172.30.0.53", "127.0.0.1"]}')
            return _cp(cmd)

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with (
                mock.patch.object(
                    mod.shutil, "which", side_effect=lambda b: b == "dig"
                ),
                mock.patch.object(mod, "run", side_effect=fake_run) as runner,
            ):
                mod.collect_resolver_probes(out)
            self.assertTrue((out / "resolve-ghcr-io-via-172-30-0-53.txt").is_file())
            loopback_digs = [
                c.args[0]
                for c in runner.call_args_list
                if c.args[0][:1] == ["dig"]
                and "@127.0.0.1" in c.args[0]
                and "ghcr.io" in c.args[0]
            ]
            self.assertEqual(len(loopback_digs), 1, loopback_digs)

    def test_a_broken_daemon_json_adds_no_probes(self):
        mod = _load()
        with mock.patch.object(
            mod, "run", return_value=_cp([], rc=0, stdout=b"not json")
        ):
            self.assertEqual(mod.daemon_json_dns(), [])
        with mock.patch.object(mod, "run", return_value=_cp([], rc=1)):
            self.assertEqual(mod.daemon_json_dns(), [])
        daemon_json = b'{"dns": "1.1.1.1"}'  # nocheck: hardcoded-dns-resolver
        with mock.patch.object(
            mod, "run", return_value=_cp([], rc=0, stdout=daemon_json)
        ):
            self.assertEqual(mod.daemon_json_dns(), [])

    def test_dnsmasq_fd_and_limits_are_captured_per_pid(self):
        mod = _load()

        def fake_run(cmd, **_kw):
            if cmd == ["pidof", "dnsmasq"]:
                return _cp(cmd, stdout=b"41 7\n")
            return _cp(cmd, stdout=b"x\n")

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(mod, "run", side_effect=fake_run):
                mod.collect_dnsmasq_introspection(out)
            for name in (
                "dnsmasq-41-fd.txt",
                "dnsmasq-41-limits.txt",
                "dnsmasq-7-fd.txt",
                "dnsmasq-7-limits.txt",
            ):
                self.assertTrue((out / name).is_file(), name)

    def test_no_dnsmasq_means_no_introspection_files(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(mod, "run", return_value=_cp([], rc=1)):
                mod.collect_dnsmasq_introspection(out)
            self.assertEqual(list(out.iterdir()), [])

    def test_a_distro_without_a_query_tool_still_gets_the_per_name_verdicts(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with (
                mock.patch.object(mod.shutil, "which", return_value=None),
                mock.patch.object(
                    mod, "run", return_value=_cp([], stdout=b"nameserver 10.0.0.1\n")
                ) as runner,
            ):
                mod.collect_resolver_probes(out)
            self.assertTrue((out / "resolve-ghcr-io.txt").is_file())
            self.assertFalse(any("dig" in c.args[0] for c in runner.call_args_list))

    def test_the_firewall_dump_is_not_narrowed_to_one_table(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(
                mod, "run", return_value=_cp([], stdout=b"")
            ) as runner:
                mod.collect_host(out, "app", "ctx", "STAMP")
            saves = [
                call.args[0]
                for call in runner.call_args_list
                if call.args[0][:1] == ["iptables-save"]
            ]
            self.assertEqual(saves, [["iptables-save"]])
            self.assertTrue((out / "firewall-rules.txt").is_file())

    def test_every_network_definition_is_dumped(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(
                mod, "run", return_value=_cp([], stdout=b"bridge\ninfinito_net\n")
            ):
                mod.collect_networks(out, "docker")
            self.assertTrue((out / "networks.txt").is_file())
            self.assertTrue((out / "networks" / "infinito_net.inspect.json").is_file())

    def test_free_space_and_free_inodes_are_separate_questions(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(mod, "run", return_value=_cp([], stdout=b"")):
                mod.collect_host(out, "app", "ctx", "STAMP")
            self.assertTrue((out / "df.txt").is_file())
            self.assertTrue((out / "df-inodes.txt").is_file())

    def test_the_process_table_carries_no_argv(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(
                mod, "run", return_value=_cp([], stdout=b"")
            ) as runner:
                mod.collect_host(out, "app", "ctx", "STAMP")
            listings = [
                call.args[0]
                for call in runner.call_args_list
                if call.args[0][:1] == ["ps"]
            ]
            self.assertTrue(listings)
            for cmd in listings:
                self.assertNotIn("args", cmd[-1].split(","))
            self.assertTrue((out / "processes.txt").is_file())

    def test_every_capture_is_one_file_beside_the_others(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(
                mod, "run", return_value=_cp([], stdout=b"")
            ) as runner:
                mod.collect_host(out, "app", "ctx", "STAMP")
            reads = [
                call.args[0]
                for call in runner.call_args_list
                if call.args[0][:1] == ["cat"]
            ]
            self.assertTrue(reads)
            for cmd in reads:
                self.assertEqual(
                    len(cmd), 2, f"a capture must read one source, not {cmd[1:]}"
                )
            self.assertTrue((out / "proc-net-udp.txt").is_file())
            self.assertTrue((out / "journal.txt").is_file())
            journals = [
                call
                for call in runner.call_args_list
                if call.args[0][:1] == ["journalctl"]
            ]
            self.assertTrue(journals)
            for call in journals:
                self.assertIn("-b", call.args[0])
                self.assertNotIn("--since", call.args[0])
                self.assertNotIn("-n", call.args[0])
                self.assertEqual(call.kwargs.get("timeout"), mod._JOURNAL_TIMEOUT)

    def test_service_state_asks_for_the_main_pid_of_every_service(self):
        mod = _load()
        listing = b"  dnsmasq.service loaded active running dnsmasq\n  tor.service loaded active running tor\n"
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(
                mod, "run", return_value=_cp([], stdout=listing)
            ) as runner:
                mod.collect_service_state(out)
            shown = [
                call.args[0]
                for call in runner.call_args_list
                if call.args[0][:2] == ["systemctl", "show"]
            ]
            self.assertEqual(len(shown), 1)
            self.assertIn("MainPID", shown[0][2])
            self.assertIn("NRestarts", shown[0][2])
            self.assertEqual(shown[0][3:], ["dnsmasq.service", "tor.service"])
            self.assertTrue((out / "service-state.txt").is_file())

    def test_service_state_writes_nothing_without_units(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(mod, "run", return_value=_cp([], stdout=b"")):
                mod.collect_service_state(out)
            self.assertFalse((out / "service-state.txt").exists())

    def test_collect_local_dumps_copies_role_evidence(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out"
            out.mkdir()
            dumps = Path(td) / "dumps"
            (dumps / "pg").mkdir(parents=True)
            (dumps / "pg" / "pg_hba.conf").write_text("evidence")
            with mock.patch.dict(os.environ, {mod._LOCAL_DUMPS_ENV: str(dumps)}):
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
            with mock.patch.dict(os.environ, {mod._LOCAL_DUMPS_ENV: str(src)}):
                mod.collect_local_dumps(out)
            dumps = out / "local-dumps"
            self.assertTrue((dumps / "pg_hba.txt").is_file())
            self.assertFalse((dumps / "app").exists())
            self.assertFalse((dumps / "local-dumps").exists())

    def test_collect_local_dumps_tolerates_missing_dir(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.dict(
                os.environ, {mod._LOCAL_DUMPS_ENV: str(Path(td) / "absent")}
            ):
                mod.collect_local_dumps(out)
            self.assertFalse((out / "local-dumps").exists())

    def test_collect_local_dumps_skips_when_the_dir_is_not_configured(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.dict(os.environ, {mod._LOCAL_DUMPS_ENV: ""}):
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

            with mock.patch.object(mod, "run", side_effect=fake_run) as runner:
                containers, services = mod.collect_runtime(out, "docker")
            execs = [
                call
                for call in runner.call_args_list
                if call.args[0][:2] == ["docker", "exec"]
            ]
            self.assertTrue(execs)
            for call in execs:
                self.assertLessEqual(
                    call.kwargs.get("timeout", mod._EXEC_TIMEOUT),
                    mod._EXEC_TIMEOUT,
                    f"a wedged container must stay inside one exec budget: {call.args[0]}",
                )
            self.assertEqual(containers, ["web/1"])
            self.assertEqual(services, ["svc1"])
            self.assertTrue((out / "containers" / "web_1.log").is_file())
            self.assertTrue((out / "containers" / "web_1.inspect.json").is_file())
            self.assertTrue((out / "services" / "svc1.log").is_file())
            self.assertTrue((out / "runtime-df.txt").is_file())
            self.assertTrue((out / "volumes.txt").is_file())
            self.assertTrue((out / "images.txt").is_file())
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
            for cmd in journalctls:
                self.assertIn("-b", cmd)
                self.assertNotIn("--since", cmd)
                self.assertNotIn("-n", cmd)
            self.assertTrue((out / "journal-kill-markers.txt").is_file())
            self.assertTrue((out / "journal-daemon.txt").is_file())

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
            self.assertFalse(
                (base / "postgres_postgres.1.abc.pg_connections.txt").exists()
            )


class RecurseTests(unittest.TestCase):
    def test_a_container_that_lists_itself_is_not_re_entered(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:

            def fake_run(cmd, **kw):
                if cmd[-1] == "{{.Names}}":
                    return _cp(cmd, stdout=b"runner\n")
                if cmd[-2:-1] == ["{{.Id}}"] or cmd[-1] == "{{.Id}}":
                    return _cp(cmd, stdout=b"cafe1234\n")
                return _cp(cmd, stdout=b"data")

            with mock.patch.object(mod, "run", side_effect=fake_run):
                entered = mod.recurse(
                    Path(td), "docker", "app", "", 0, ["cafe1234"], "S"
                )
            self.assertEqual(entered, 0)

    def test_a_container_without_an_id_is_not_entered(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:

            def fake_run(cmd, **kw):
                if cmd[-1] == "{{.Names}}":
                    return _cp(cmd, stdout=b"nameless\n")
                if "{{.Id}}" in cmd:
                    return _cp(cmd)
                return _cp(cmd, stdout=b"data")

            with mock.patch.object(mod, "run", side_effect=fake_run):
                entered = mod.recurse(Path(td), "docker", "app", "", 0, [], "S")
            self.assertEqual(entered, 0)

    def test_recurse_skips_containers_without_runtime(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as td:

            def fake_run(cmd, **kw):
                if cmd[-1] == "{{.Names}}":
                    return _cp(cmd, stdout=b"plain\n")
                if "{{.Id}}" in cmd:
                    return _cp(cmd, stdout=b"beef5678\n")
                return _cp(cmd, rc=1)

            with mock.patch.object(mod, "run", side_effect=fake_run):
                self.assertEqual(
                    mod.recurse(Path(td), "docker", "app", "", 0, [], "S"), 0
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
                if "{{.Id}}" in cmd:
                    return _cp(cmd, stdout=b"d00d1234\n")
                if cmd[:2] == ["docker", "exec"] and "tar" in cmd:
                    return _cp(cmd, stdout=b"TARBYTES")
                return _cp(cmd)

            with mock.patch.object(mod, "run", side_effect=fake_run):
                nested = mod.recurse(out, "docker", "app", "ctx", 0, [], "S")

            self.assertEqual(nested, 1)
            copy_call = next(c for c in calls if "cat >" in " ".join(c))
            self.assertIn("node1", copy_call)
            nested_exec = next(c for c in calls if "python3" in c)
            env_args = " ".join(nested_exec)
            self.assertIn("RESCUE_DEPTH=1", env_args)
            self.assertIn("RESCUE_SEEN=", env_args)
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
