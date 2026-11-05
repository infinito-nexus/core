import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase, main, mock

from . import PROJECT_ROOT


def load_target_module():
    script_path = (
        PROJECT_ROOT
        / "roles"
        / "svc-bkp-volume-2-local"
        / "files"
        / "python"
        / "baudolo"
        / "ha_gate.py"
    )
    spec = importlib.util.spec_from_file_location("baudolo_ha_gate", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


GATE = load_target_module()
PG = {
    "engine": "postgres",
    "service": "postgres_postgres-mgr-01",
    "volume": "postgres_data",
    "probe": ["/usr/bin/primary-probe-postgres", "postgres", "postgres-mgr-01"],
}
LDAP = {
    "engine": "openldap",
    "service": "openldap_openldap-mgr-01",
    "volume": "openldap_data",
    "probe": ["/usr/bin/primary-probe-openldap", "openldap", "openldap-mgr-01"],
}


def done(rc=0, stdout=""):
    return subprocess.CompletedProcess([], rc, stdout=stdout, stderr="")


def runner_for(probe_rc=0):
    calls = []

    def runner(argv):
        calls.append(list(argv))
        return done(probe_rc)

    runner.calls = calls
    return runner


class TestProbe(TestCase):
    def test_primary_when_probe_answers(self):
        self.assertEqual(GATE.probe_role(PG, runner_for(probe_rc=0)), GATE.PRIMARY)

    def test_replica_when_probe_refuses(self):
        self.assertEqual(GATE.probe_role(LDAP, runner_for(probe_rc=1)), GATE.REPLICA)

    def test_unknown_when_probe_cannot_ask(self):
        for rc in (2, 64, 125, 126, 127):
            with self.subTest(rc=rc):
                self.assertEqual(
                    GATE.probe_role(LDAP, runner_for(probe_rc=rc)), GATE.UNKNOWN
                )

    def test_absent_when_the_instance_is_not_deployed(self):
        self.assertEqual(GATE.probe_role(PG, runner_for(probe_rc=3)), GATE.ABSENT)

    def test_runs_the_engine_probe_argv(self):
        runner = runner_for()
        GATE.probe_role(PG, runner)
        self.assertEqual(runner.calls, [PG["probe"]])

    def test_missing_probe_argv_raises(self):
        with self.assertRaises(ValueError):
            GATE.probe_role({**PG, "probe": "patroni"}, runner_for())


class TestPlan(TestCase):
    def test_only_confirmed_primary_dumps(self):
        roles = {PG["service"]: GATE.PRIMARY, LDAP["service"]: GATE.REPLICA}
        self.assertEqual(
            GATE.plan([PG, LDAP], roles), (["postgres_data"], ["openldap_data"])
        )

    def test_file_backed_primary_expects_no_dump(self):
        ldap = {**LDAP, "sql": False}
        roles = {ldap["service"]: GATE.PRIMARY}
        self.assertEqual(GATE.plan([ldap], roles), ([], []))

    def test_unknown_is_skipped(self):
        roles = {PG["service"]: GATE.UNKNOWN}
        self.assertEqual(GATE.plan([PG], roles), ([], ["postgres_data"]))


class TestWithExcluded(TestCase):
    def test_appends_flag(self):
        self.assertEqual(
            GATE.with_excluded(["baudolo", "--only-sql"], ["a"]),
            ["baudolo", "--only-sql", GATE.EXCLUDE_FLAG, "a"],
        )

    def test_merges_into_existing_flag(self):
        argv = ["baudolo", GATE.EXCLUDE_FLAG, "x", "--only-sql"]
        self.assertEqual(
            GATE.with_excluded(argv, ["a", "x"]),
            ["baudolo", GATE.EXCLUDE_FLAG, "x", "a", "--only-sql"],
        )

    def test_no_volumes_unchanged(self):
        self.assertEqual(GATE.with_excluded(["baudolo"], []), ["baudolo"])


class TestMissingDumps(TestCase):
    def _generation(self, volumes):
        root = Path(tempfile.mkdtemp())
        gen = root / "hash" / "repo" / "20261008"
        gen.mkdir(parents=True)
        (gen / GATE.MANIFEST_FILE).write_text(json.dumps({"volumes": volumes}))
        return root, gen

    def test_dumped_volume_passes(self):
        _, gen = self._generation({"postgres_data": {"database": True, "dumped": True}})
        self.assertEqual(GATE.missing_dumps(gen, ["postgres_data"]), [])

    def test_undumped_volume_fails(self):
        _, gen = self._generation(
            {"postgres_data": {"database": True, "dumped": False}}
        )
        self.assertEqual(GATE.missing_dumps(gen, ["postgres_data"]), ["postgres_data"])

    def test_absent_generation_fails(self):
        self.assertEqual(GATE.missing_dumps(None, ["v"]), ["v"])

    def test_nothing_expected_passes(self):
        self.assertEqual(GATE.missing_dumps(None, []), [])

    def test_newest_generation_and_purge(self):
        root, gen = self._generation({})
        files = gen / "postgres_data" / "files"
        files.mkdir(parents=True)
        self.assertEqual(GATE.newest_generation(root, "hash", "repo"), gen)
        GATE.purge_file_copies(gen, ["postgres_data"])
        self.assertFalse(files.exists())


class TestMachineScope(TestCase):
    def test_a_newer_generation_of_another_machine_is_ignored(self):
        root = Path(tempfile.mkdtemp())
        own = root / "own" / "repo" / "20261008"
        own.mkdir(parents=True)
        pulled = root / "other" / "repo" / "20261009"
        pulled.mkdir(parents=True)
        os.utime(own, (1, 1))
        self.assertEqual(GATE.newest_generation(root, "own", "repo"), own)

    def test_machine_hash_matches_sha256sum_of_the_file(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as handle:
            handle.write(b"0123456789abcdef0123456789abcdef\n")
        self.assertEqual(
            GATE.machine_hash(Path(handle.name)),
            hashlib.sha256(b"0123456789abcdef0123456789abcdef\n").hexdigest(),
        )


class TestMain(TestCase):
    def setUp(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write("0123456789abcdef0123456789abcdef\n")
        patcher = mock.patch.object(GATE, "MACHINE_ID_FILE", Path(handle.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _config(self, instances):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({"instances": instances}, handle)
        return handle.name

    def test_usage_without_separator(self):
        self.assertEqual(GATE.main(["--config", "x"]), GATE.USAGE)

    def test_missing_dump_fails_loudly(self):
        backups = tempfile.mkdtemp()
        argv = [
            "--config",
            self._config([PG]),
            "--backups-dir",
            backups,
            "--repo-name",
            "repo",
            "--",
            "baudolo",
        ]
        with mock.patch.object(GATE.subprocess, "run", return_value=done(0)) as run:
            self.assertEqual(GATE.main(argv, runner_for(probe_rc=0)), GATE.MISSING_DUMP)
        self.assertEqual(run.call_args.args[0], ["baudolo"])

    def test_replica_host_excludes_volume_and_succeeds(self):
        backups = tempfile.mkdtemp()
        argv = [
            "--config",
            self._config([PG]),
            "--backups-dir",
            backups,
            "--repo-name",
            "repo",
            "--",
            "baudolo",
        ]
        with mock.patch.object(GATE.subprocess, "run", return_value=done(0)) as run:
            self.assertEqual(GATE.main(argv, runner_for(probe_rc=1)), 0)
        self.assertEqual(
            run.call_args.args[0], ["baudolo", GATE.EXCLUDE_FLAG, "postgres_data"]
        )

    def test_migrating_host_backs_up_the_standalone_engine(self):
        argv = [
            "--config",
            self._config([PG]),
            "--backups-dir",
            tempfile.mkdtemp(),
            "--repo-name",
            "repo",
            "--",
            "baudolo",
        ]
        with mock.patch.object(GATE.subprocess, "run", return_value=done(0)) as run:
            self.assertEqual(GATE.main(argv, runner_for(probe_rc=3)), 0)
        self.assertEqual(
            run.call_args.args[0], ["baudolo", GATE.EXCLUDE_FLAG, "postgres_data"]
        )

    def test_unknown_probe_fails_without_running_baudolo(self):
        argv = [
            "--config",
            self._config([PG]),
            "--backups-dir",
            tempfile.mkdtemp(),
            "--repo-name",
            "repo",
            "--",
            "baudolo",
        ]
        with mock.patch.object(GATE.subprocess, "run", return_value=done(0)) as run:
            self.assertEqual(GATE.main(argv, runner_for(probe_rc=2)), GATE.PROBE_FAILED)
        run.assert_not_called()

    def test_standalone_host_without_config_runs_unchanged(self):
        argv = [
            "--config",
            "/nonexistent.json",
            "--backups-dir",
            tempfile.mkdtemp(),
            "--repo-name",
            "repo",
            "--",
            "baudolo",
            "--only-sql",
        ]
        with mock.patch.object(GATE.subprocess, "run", return_value=done(0)) as run:
            self.assertEqual(GATE.main(argv, runner_for()), 0)
        self.assertEqual(run.call_args.args[0], ["baudolo", "--only-sql"])

    def test_baudolo_failure_propagates(self):
        argv = [
            "--config",
            "/nonexistent.json",
            "--backups-dir",
            tempfile.mkdtemp(),
            "--repo-name",
            "repo",
            "--",
            "baudolo",
        ]
        with mock.patch.object(GATE.subprocess, "run", return_value=done(5)):
            self.assertEqual(GATE.main(argv, runner_for()), 5)


if __name__ == "__main__":
    main()
