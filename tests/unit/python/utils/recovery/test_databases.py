#!/usr/bin/env python3
import gzip
import io
import json
import tempfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest import TestCase, main, mock

from baudolo.restore import __main__ as restore_cli
from baudolo.restore.dumpfile import locate
from baudolo.restore.paths import BackupPaths

from utils.recovery import databases
from utils.recovery import docker as recovery_docker
from utils.recovery.layout import MANIFEST_FILE, MANIFEST_SCHEMA

APPLICATIONS = {
    "web-app-zammad": {"services": {"postgres": {"enabled": True}}},
    "web-app-nextcloud": {"services": {"mariadb": {"enabled": True}}},
    "web-app-static": {"services": {"redis": {"enabled": True}}},
}


def generation(root: Path) -> Path:
    path = root / "Backups" / "abc123" / "backup-docker-to-local" / "20260816190906"
    path.mkdir(parents=True)
    return path


class TestEngineResolution(TestCase):
    def setUp(self):
        self.engines = databases.engine_by_key(APPLICATIONS)

    def test_central_instances_are_their_own_engine(self):
        self.assertEqual(self.engines["postgres"], "postgres")
        self.assertEqual(self.engines["mariadb"], "mariadb")

    def test_both_volume_spellings_resolve(self):
        self.assertEqual(self.engines["zammad"], "postgres")
        self.assertEqual(self.engines["zammad_database"], "postgres")
        self.assertEqual(self.engines["nextcloud_database"], "mariadb")

    def test_an_app_without_a_database_contributes_nothing(self):
        self.assertNotIn("static", self.engines)

    def test_engine_of_prefers_the_volume_then_the_database(self):
        dump = databases.Dump("nextcloud_database", "nextcloud", Path("/x"))
        self.assertEqual(databases.engine_of(dump, self.engines), "mariadb")
        by_name = databases.Dump("unknown_volume", "zammad", Path("/x"))
        self.assertEqual(databases.engine_of(by_name, self.engines), "postgres")

    def test_an_unknown_dump_aborts_instead_of_guessing(self):
        dump = databases.Dump("mystery_data", "mystery", Path("/x"))
        with self.assertRaises(databases.RecoveryError):
            databases.engine_of(dump, self.engines)

    def test_the_real_repository_resolves_its_own_apps(self):
        engines = databases.engine_by_key()
        self.assertEqual(engines["postgres"], "postgres")
        self.assertEqual(engines["zammad"], "postgres")


class TestLayoutFollowsBaudolo(TestCase):
    """baudolo writes the generation, so core must read exactly what it writes."""

    def setUp(self):
        self.backups = Path(tempfile.mkdtemp())
        self.paths = BackupPaths(
            "postgres",
            "abc123",
            "20260816190906",
            repo_name="a-repo",
            backups_dir=str(self.backups),
        )
        for written in (self.paths.sql_file("zammad"), self.paths.cluster_file("all")):
            Path(written).parent.mkdir(parents=True, exist_ok=True)
            Path(written).write_text("")
        self.generation = Path(self.paths.root()).parent

    def test_generation_of_recovers_what_backup_paths_composed(self):
        parts = databases.generation_of(self.generation)
        self.assertEqual(parts.backups_dir, str(self.backups))
        self.assertEqual(parts.machine_hash, "abc123")
        self.assertEqual(parts.repo_name, "a-repo")
        self.assertEqual(parts.name, "20260816190906")

    def test_dumps_of_finds_the_files_backup_paths_names(self):
        dumps, clusters = databases.dumps_of(self.generation)
        self.assertEqual(
            [(d.volume, d.database) for d in dumps], [("postgres", "zammad")]
        )
        self.assertEqual(
            [(c.volume, c.instance) for c in clusters], [("postgres", "all")]
        )

    def test_backup_paths_names_the_compressed_dump(self):
        self.assertTrue(self.paths.sql_file("zammad").endswith(".backup.sql.gz"))
        self.assertTrue(
            self.paths.cluster_file("all").endswith(".cluster.backup.sql.gz")
        )

    def assert_core_finds_what_baudolo_replays(self):
        dumps, clusters = databases.dumps_of(self.generation)
        self.assertEqual(len(dumps), 1)
        self.assertEqual(len(clusters), 1)
        for dump in dumps:
            self.assertEqual(locate(self.paths.sql_file(dump.database)), str(dump.path))
        for cluster in clusters:
            self.assertEqual(
                locate(self.paths.cluster_file(cluster.instance)), str(cluster.path)
            )

    def test_a_compressed_dump_is_the_one_baudolo_restore_replays(self):
        self.assert_core_finds_what_baudolo_replays()

    def test_a_dump_from_before_baudolo_8_is_the_one_baudolo_restore_replays(self):
        for written in (self.paths.sql_file("zammad"), self.paths.cluster_file("all")):
            Path(written).rename(written.removesuffix(".gz"))
        self.assert_core_finds_what_baudolo_replays()

    def test_negative_control_a_dump_held_twice_is_refused_like_baudolo_does(self):
        legacy = self.paths.sql_file("zammad").removesuffix(".gz")
        Path(legacy).write_text("")
        with self.assertRaises(FileExistsError):
            locate(self.paths.sql_file("zammad"))
        with self.assertRaises(databases.RecoveryError) as raised:
            databases.dumps_of(self.generation)
        self.assertIn("zammad.backup.sql", str(raised.exception))


class TestGenerationLayout(TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.generation = generation(self.root)
        (self.generation / "postgres/sql").mkdir(parents=True)
        (self.generation / "postgres/sql/zammad.backup.sql").write_text("")
        (self.generation / "postgres/sql/all.cluster.backup.sql").write_text("")
        (self.generation / "openldap_data/files").mkdir(parents=True)

    def test_parts_come_from_the_path(self):
        parts = databases.generation_of(self.generation)
        self.assertEqual(parts.backups_dir, str(self.root / "Backups"))
        self.assertEqual(parts.machine_hash, "abc123")
        self.assertEqual(parts.repo_name, "backup-docker-to-local")
        self.assertEqual(parts.name, "20260816190906")

    def test_each_dump_is_sorted_into_the_subcommand_that_replays_it(self):
        dumps, clusters = databases.dumps_of(self.generation)
        self.assertEqual(
            [(d.volume, d.database) for d in dumps], [("postgres", "zammad")]
        )
        self.assertEqual(
            [(c.volume, c.instance) for c in clusters], [("postgres", "all")]
        )

    def test_compressed_and_plain_dumps_of_one_generation_are_both_found(self):
        (self.generation / "mariadb/sql").mkdir(parents=True)
        (self.generation / "mariadb/sql/nextcloud.backup.sql.gz").write_bytes(b"")
        (self.generation / "mariadb/sql/central.cluster.backup.sql.gz").write_bytes(b"")
        dumps, clusters = databases.dumps_of(self.generation)
        self.assertEqual(
            [(d.volume, d.database) for d in dumps],
            [("mariadb", "nextcloud"), ("postgres", "zammad")],
        )
        self.assertEqual(
            [(c.volume, c.instance) for c in clusters],
            [("mariadb", "central"), ("postgres", "all")],
        )

    def test_negative_control_a_file_that_is_no_dump_is_not_replayed(self):
        for stray in ("zammad.backup.sql.tmp", "zammad.sql.gz", "notes.gz"):
            (self.generation / "postgres/sql" / stray).write_bytes(b"")
        dumps, clusters = databases.dumps_of(self.generation)
        self.assertEqual([d.path.name for d in dumps], ["zammad.backup.sql"])
        self.assertEqual([c.path.name for c in clusters], ["all.cluster.backup.sql"])

    def test_cluster_argv_matches_the_baudolo_contract(self):
        cluster = databases.Cluster("postgres", "central-postgres", Path("/x"))
        argv = databases.cluster_argv(
            cluster,
            databases.generation_of(self.generation),
            "postgres-1",
            "postgres",
        )
        self.assertEqual(
            argv[:5],
            ["baudolo-restore", "cluster", "postgres", "abc123", "20260816190906"],
        )
        self.assertEqual(argv[argv.index("--instance") + 1], "central-postgres")
        self.assertEqual(argv[argv.index("--db-user") + 1], "postgres")
        self.assertIn("--empty", argv)
        self.assertNotIn(
            "--db-name", argv, "a cluster dump names an instance, not a database"
        )

    def test_restore_argv_matches_the_baudolo_contract(self):
        dump = databases.Dump("postgres", "zammad", Path("/x"))
        argv = databases.restore_argv(
            dump,
            databases.generation_of(self.generation),
            "postgres",
            "postgres-1",
            "zammad",
        )
        self.assertEqual(
            argv[:5],
            [
                "baudolo-restore",
                "postgres",
                "postgres",
                "abc123",
                "20260816190906",
            ],
        )
        self.assertIn("--empty", argv)
        self.assertEqual(argv[argv.index("--container") + 1], "postgres-1")
        self.assertEqual(argv[argv.index("--db-name") + 1], "zammad")

    def test_neither_argv_takes_a_password(self):
        generation_parts = databases.generation_of(self.generation)
        for argv in (
            databases.restore_argv(
                databases.Dump("postgres", "zammad", Path("/x")),
                generation_parts,
                "postgres",
                "postgres-1",
                "zammad",
            ),
            databases.cluster_argv(
                databases.Cluster("postgres", "all", Path("/x")),
                generation_parts,
                "postgres-1",
                "postgres",
            ),
        ):
            with self.subTest(subcommand=argv[1]):
                self.assertIn("--db-password-stdin", argv)
                self.assertNotIn("--db-password", argv)


class TestPasswordTransport(TestCase):
    PASSWORD = "s3 cr'et\n"

    def setUp(self):
        self.generation = generation(Path(tempfile.mkdtemp()))
        self.parts = databases.generation_of(self.generation)

    def argvs(self):
        return {
            "postgres": databases.restore_argv(
                databases.Dump("postgres", "zammad", Path("/x")),
                self.parts,
                "postgres",
                "postgres-1",
                "zammad",
            ),
            "cluster": databases.cluster_argv(
                databases.Cluster("postgres", "all", Path("/x")),
                self.parts,
                "postgres-1",
                "postgres",
            ),
        }

    def baudolo_receives(self, argv, stdin):
        seen = {}

        def restore(**kwargs):
            seen.update(kwargs)

        with (
            mock.patch.object(restore_cli, "restore_postgres_sql", restore),
            mock.patch.object(restore_cli, "restore_cluster_sql", restore),
            mock.patch.object(restore_cli, "locate", lambda path: path),
            mock.patch("sys.stdin", io.StringIO(stdin)),
            redirect_stderr(io.StringIO()) as stderr,
        ):
            self.assertEqual(restore_cli.main(argv[1:]), 0)
        self.assertNotIn("WARNING", stderr.getvalue())
        return seen["password"]

    def test_the_password_reaches_baudolo_through_stdin_only(self):
        for subcommand, argv in self.argvs().items():
            with self.subTest(subcommand=subcommand):
                self.assertFalse(any(self.PASSWORD.strip() in part for part in argv))
                sent = {}

                def fake_run(argv, secret="", stdin=None, sent=sent):
                    sent["stdin"] = stdin
                    sent["secret"] = secret
                    return ""

                with mock.patch.object(recovery_docker, "_run", fake_run):
                    databases._restore(argv, self.PASSWORD)
                self.assertEqual(sent["secret"], self.PASSWORD)
                self.assertEqual(
                    self.baudolo_receives(argv, sent["stdin"]), self.PASSWORD
                )

    def test_negative_control_without_stdin_baudolo_gets_no_password(self):
        for subcommand, argv in self.argvs().items():
            with self.subTest(subcommand=subcommand):
                self.assertEqual(self.baudolo_receives(argv, ""), "")


POSTGRES_HEADER = """--
-- PostgreSQL database dump
--

\\restrict BbyzwODc1rWKL3rDyLhEjgCF0Kf2TU5ma7gcTs8eQI7copLtydXkc61zdULsPav

-- Dumped from database version 17.11
-- Dumped by pg_dump version 17.11

SET statement_timeout = 0;
"""

MARIADB_HEADER = """/*M!999999\\- enable the sandbox mode */
-- MariaDB dump 10.19-11.8.8-MariaDB, for debian-linux-gnu (x86_64)
--
-- Host: 127.0.0.1    Database: mysql
-- ------------------------------------------------------
-- Server version\t11.8.8-MariaDB-ubu2404

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
"""


CLUSTER_DUMP = """--
-- PostgreSQL database cluster dump
--

CREATE ROLE greenlight;
ALTER ROLE greenlight WITH LOGIN;

\\connect template1

\\connect postgres

\\connect greenlight

-- Dumped from database version 17.11
CREATE TABLE t (v text);

\\connect keycloak

-- Dumped from database version 17.11
CREATE TABLE t (v text);
"""


class TestClusterDumps(TestCase):
    def cluster(self, text=CLUSTER_DUMP):
        path = Path(tempfile.mkdtemp()) / "central-postgres.cluster.backup.sql"
        path.write_text(text, encoding="utf-8")
        return databases.Cluster("postgres", "central-postgres", path)

    def test_the_connect_lines_are_the_inventory(self):
        self.assertEqual(
            databases.databases_in(self.cluster()), ["greenlight", "keycloak"]
        )

    def test_the_control_databases_are_not_applications(self):
        found = databases.databases_in(self.cluster())
        for control in ("postgres", "template0", "template1"):
            self.assertNotIn(control, found)

    def test_a_database_created_but_never_reconnected_still_counts(self):
        """pg_dumpall names a database twice; a stream that only creates it
        would otherwise leave it unseeded and the drill would pass regardless."""
        cluster = self.cluster('CREATE DATABASE "late" WITH TEMPLATE = template0;\n')
        self.assertEqual(databases.databases_in(cluster), ["late"])

    def test_a_quoted_name_loses_its_quotes(self):
        cluster = self.cluster('\\connect "odd-name"\n')
        self.assertEqual(databases.databases_in(cluster), ["odd-name"])

    def test_a_quoted_name_keeps_its_spaces(self):
        cluster = self.cluster('\\connect "odd name"\n')
        self.assertEqual(databases.databases_in(cluster), ["odd name"])

    def test_psql_options_are_not_mistaken_for_the_database(self):
        cluster = self.cluster("\\connect -reuse-previous=on dbname=appdb\n")
        self.assertEqual(databases.databases_in(cluster), ["appdb"])

    def test_a_database_reconnected_twice_is_listed_once(self):
        cluster = self.cluster("\\connect app\nSELECT 1;\n\\connect app\n")
        self.assertEqual(databases.databases_in(cluster), ["app"])


class TestCredentials(TestCase):
    def write(self, text):
        path = Path(tempfile.mkdtemp()) / "databases.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def test_first_row_per_database_wins(self):
        path = self.write(
            "instance;database;username;password\n"
            "postgres;zammad;zammad;secret\n"
            "postgres;zammad;other;later\n"
            "\n"
        )
        self.assertEqual(
            databases.credentials_of(path), {"zammad": ("zammad", "secret")}
        )

    def test_short_row_aborts(self):
        path = self.write("instance;database;username;password\npostgres;zammad\n")
        with self.assertRaises(databases.RecoveryError):
            databases.credentials_of(path)

    def test_missing_file_aborts(self):
        with self.assertRaises(databases.RecoveryError):
            databases.credentials_of(Path("/nonexistent/databases.csv"))

    def test_a_cluster_row_is_keyed_by_its_instance(self):
        path = self.write(
            "instance;database;username;password\n"
            "central-postgres;*;postgres;super\n"
            "bbb-postgres;*;postgres;other\n"
            "central-postgres;zammad;zammad;secret\n"
        )
        self.assertEqual(
            databases.cluster_credentials_of(path),
            {
                "central-postgres": ("postgres", "super"),
                "bbb-postgres": ("postgres", "other"),
            },
        )

    def test_two_instances_would_collide_under_the_database_key(self):
        path = self.write(
            "instance;database;username;password\n"
            "central-postgres;*;postgres;super\n"
            "bbb-postgres;*;postgres;other\n"
        )
        self.assertEqual(databases.credentials_of(path), {"*": ("postgres", "super")})


class TestReplay(TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.generation = generation(self.root)
        (self.generation / "postgres/sql").mkdir(parents=True)
        (self.generation / "postgres/sql/zammad.backup.sql").write_text(POSTGRES_HEADER)
        self.csv = self.root / "databases.csv"
        self.csv.write_text(
            "instance;database;username;password\npostgres;zammad;zammad;s3cret\n",
            encoding="utf-8",
        )
        self.engines = {"postgres": "postgres"}

    def replay(self, running):
        calls = []
        self.stdins = []

        def fake_run(argv, secret="", stdin=None):
            calls.append(argv)
            self.stdins.append(stdin)
            return ""

        with (
            mock.patch.object(recovery_docker, "_run", fake_run),
            mock.patch.object(
                recovery_docker, "consumers_running", lambda *a, **k: running
            ),
            mock.patch.object(
                recovery_docker, "container_of_volume", lambda *a, **k: "postgres-1"
            ),
        ):
            replayed = databases.replay(self.generation, self.csv, engines=self.engines)
        return replayed, calls

    def test_a_running_consumer_aborts_before_anything_is_restored(self):
        with self.assertRaises(databases.RecoveryError) as raised:
            self.replay(["zammad-railsserver"])
        self.assertIn("zammad-railsserver", str(raised.exception))

    def test_the_engine_itself_does_not_block_its_own_replay(self):
        replayed, _ = self.replay(["postgres-1"])
        self.assertEqual(replayed, 1)

    def test_a_consumer_beside_the_engine_still_aborts(self):
        with self.assertRaises(databases.RecoveryError) as raised:
            self.replay(["postgres-1", "zammad-railsserver"])
        self.assertIn("zammad-railsserver", str(raised.exception))
        self.assertNotIn("postgres-1", str(raised.exception))

    def test_a_quiesced_host_replays_the_dump(self):
        replayed, calls = self.replay([])
        self.assertEqual(replayed, 1)
        restores = [argv for argv in calls if argv[0] == "baudolo-restore"]
        self.assertEqual(len(restores), 1)
        self.assertEqual(restores[0][:2], ["baudolo-restore", "postgres"])

    def test_the_password_goes_in_on_stdin_and_on_no_argv(self):
        _, calls = self.replay([])
        self.assertEqual(
            [argv for argv in calls if any("s3cret" in part for part in argv)], []
        )
        self.assertEqual([stdin for stdin in self.stdins if stdin], ["s3cret\n"])

    def test_a_compressed_dump_is_replayed(self):
        (self.generation / "postgres/sql/zammad.backup.sql").unlink()
        with gzip.open(
            self.generation / "postgres/sql/zammad.backup.sql.gz", "wt"
        ) as out:
            out.write(POSTGRES_HEADER)
        replayed, calls = self.replay([])
        self.assertEqual(replayed, 1)
        restore = next(argv for argv in calls if argv[0] == "baudolo-restore")
        self.assertEqual(restore[restore.index("--db-name") + 1], "zammad")

    def test_negative_control_a_dump_held_twice_replays_nothing(self):
        with gzip.open(
            self.generation / "postgres/sql/zammad.backup.sql.gz", "wt"
        ) as out:
            out.write(POSTGRES_HEADER)
        calls = []
        with (
            mock.patch.object(
                recovery_docker,
                "_run",
                lambda argv, secret="", stdin=None: calls.append(argv) or "",
            ),
            self.assertRaises(databases.RecoveryError) as raised,
        ):
            databases.replay(self.generation, self.csv, engines=self.engines)
        self.assertIn("same dump twice", str(raised.exception))
        self.assertEqual(calls, [])

    def test_the_version_check_is_left_to_baudolo(self):
        _, calls = self.replay([])
        self.assertEqual(
            [argv for argv in calls if "exec" in argv],
            [],
            "the replay must not query the engine version itself",
        )

    def test_a_generation_without_dumps_is_not_an_error(self):
        empty = generation(Path(tempfile.mkdtemp()))
        self.assertEqual(databases.replay(empty, self.csv, engines=self.engines), 0)

    def test_a_missing_generation_aborts(self):
        with self.assertRaises(databases.RecoveryError):
            databases.replay(self.generation / "nope", self.csv, engines=self.engines)

    def test_a_stopped_database_container_says_to_start_it(self):
        with mock.patch.object(
            recovery_docker, "_run", lambda argv, secret="": "postgres\n"
        ):
            self.assertEqual(
                recovery_docker.container_of_volume("postgres"), "postgres"
            )

        def only_ps_all(argv, secret=""):
            return "postgres\n" if "-a" in argv else ""

        with (
            mock.patch.object(recovery_docker, "_run", only_ps_all),
            self.assertRaises(databases.RecoveryError) as raised,
        ):
            recovery_docker.container_of_volume("postgres")
        self.assertIn("is not running", str(raised.exception))

    def test_no_container_at_all_says_to_deploy_first(self):
        with (
            mock.patch.object(
                recovery_docker, "_run", lambda argv, secret="", stdin=None: ""
            ),
            self.assertRaises(databases.RecoveryError) as raised,
        ):
            recovery_docker.container_of_volume("postgres")
        self.assertIn("deploy the stack first", str(raised.exception))

    def test_a_cluster_dump_is_replayed_as_a_whole(self):
        (self.generation / "postgres/sql/bbb-postgres.cluster.backup.sql").write_text(
            CLUSTER_DUMP, encoding="utf-8"
        )
        self.csv.write_text(
            "instance;database;username;password\n"
            "postgres;zammad;zammad;s3cret\n"
            "bbb-postgres;*;postgres;super\n",
            encoding="utf-8",
        )
        replayed, calls = self.replay([])
        self.assertEqual(replayed, 2)
        subcommands = [argv[1] for argv in calls if argv[0] == "baudolo-restore"]
        self.assertEqual(
            subcommands,
            ["cluster", "postgres"],
            "the cluster goes in first; a single-database dump of the same "
            "instance is the more specific statement and must land after it",
        )

    def test_a_cluster_without_a_superuser_row_aborts(self):
        (self.generation / "postgres/sql/bbb-postgres.cluster.backup.sql").write_text(
            CLUSTER_DUMP, encoding="utf-8"
        )
        with self.assertRaises(databases.RecoveryError) as raised:
            self.replay([])
        self.assertIn("bbb-postgres", str(raised.exception))

    def test_a_consumer_of_a_clustered_database_aborts_the_replay(self):
        (self.generation / "postgres/sql/bbb-postgres.cluster.backup.sql").write_text(
            CLUSTER_DUMP, encoding="utf-8"
        )
        self.csv.write_text(
            "instance;database;username;password\n"
            "postgres;zammad;zammad;s3cret\n"
            "bbb-postgres;*;postgres;super\n",
            encoding="utf-8",
        )
        with (
            mock.patch.object(
                recovery_docker, "_run", lambda argv, secret="", stdin=None: ""
            ),
            mock.patch.object(
                recovery_docker,
                "consumers_running",
                lambda project, *a, **k: (
                    ["greenlight-web"] if project == "greenlight" else []
                ),
            ),
            mock.patch.object(
                recovery_docker, "container_of_volume", lambda *a, **k: "postgres-1"
            ),
            self.assertRaises(databases.RecoveryError) as raised,
        ):
            databases.replay(self.generation, self.csv, engines=self.engines)
        self.assertIn("greenlight-web", str(raised.exception))

    def cluster_only(self, running_in_project):
        """A generation holding nothing but one instance's cluster dump."""
        (self.generation / "postgres/sql/zammad.backup.sql").unlink()
        (self.generation / "postgres/sql/bbb-postgres.cluster.backup.sql").write_text(
            CLUSTER_DUMP, encoding="utf-8"
        )
        self.csv.write_text(
            "instance;database;username;password\nbbb-postgres;*;postgres;super\n",
            encoding="utf-8",
        )
        return (
            mock.patch.object(
                recovery_docker,
                "_run",
                lambda argv, secret="", stdin=None: (
                    "bigbluebutton\n" if "inspect" in argv else ""
                ),
            ),
            mock.patch.object(
                recovery_docker,
                "consumers_running",
                lambda project, *a, **k: running_in_project.get(project, []),
            ),
            mock.patch.object(
                recovery_docker, "container_of_volume", lambda *a, **k: "bbb-postgres-1"
            ),
        )

    def test_a_consumer_in_the_engines_own_project_aborts_the_cluster_replay(self):
        patches = self.cluster_only({"bigbluebutton": ["bigbluebutton-etherpad-1"]})
        with (
            patches[0],
            patches[1],
            patches[2],
            self.assertRaises(databases.RecoveryError) as raised,
        ):
            databases.replay(self.generation, self.csv, engines=self.engines)
        self.assertIn("bigbluebutton-etherpad-1", str(raised.exception))

    def test_the_engine_is_not_counted_as_its_own_consumer(self):
        patches = self.cluster_only({"bigbluebutton": ["bbb-postgres-1"]})
        with patches[0], patches[1], patches[2]:
            self.assertEqual(
                databases.replay(self.generation, self.csv, engines=self.engines), 1
            )

    def test_a_dump_only_the_manifest_can_place_is_replayed(self):
        root = Path(tempfile.mkdtemp())
        gen = generation(root)
        (gen / "postgres_data/sql").mkdir(parents=True)
        (gen / "postgres_data/sql/mautrix_meta_bridge.backup.sql").write_text(
            POSTGRES_HEADER
        )
        (gen / MANIFEST_FILE).write_text(
            json.dumps(
                {
                    "schema": MANIFEST_SCHEMA,
                    "volumes": {
                        "postgres_data": {
                            "database": True,
                            "dumped": True,
                            "engine": "postgres",
                        }
                    },
                }
            )
        )
        csv = root / "databases.csv"
        csv.write_text(
            "instance;database;username;password\n"
            "postgres;mautrix_meta_bridge;bridge;pw\n",
            encoding="utf-8",
        )
        with (
            mock.patch.object(
                recovery_docker, "_run", lambda argv, secret="", stdin=None: ""
            ),
            mock.patch.object(recovery_docker, "consumers_running", lambda *a, **k: []),
            mock.patch.object(
                recovery_docker, "container_of_volume", lambda *a, **k: "postgres-1"
            ),
        ):
            self.assertEqual(databases.replay(gen, csv), 1)

    def test_the_password_is_redacted_from_a_failure(self):
        with self.assertRaises(databases.RecoveryError) as raised:
            recovery_docker._run(["false", "--db-password", "s3cret"], secret="s3cret")
        self.assertNotIn("s3cret", str(raised.exception))
        self.assertIn("***", str(raised.exception))

    def test_a_password_echoed_on_stderr_is_redacted_too(self):
        with self.assertRaises(databases.RecoveryError) as raised:
            recovery_docker._run(
                ["sh", "-c", "cat >&2; exit 1"], secret="s3cret", stdin="s3cret\n"
            )
        self.assertNotIn("s3cret", str(raised.exception))
        self.assertIn("***", str(raised.exception))

    def test_negative_control_unredacted_stderr_is_shown(self):
        with self.assertRaises(databases.RecoveryError) as raised:
            recovery_docker._run(["sh", "-c", "cat >&2; exit 1"], stdin="s3cret\n")
        self.assertIn("s3cret", str(raised.exception))

    def test_stdin_reaches_the_command(self):
        self.assertEqual(recovery_docker._run(["cat"], stdin="s3cret\n"), "s3cret\n")


if __name__ == "__main__":
    main()
