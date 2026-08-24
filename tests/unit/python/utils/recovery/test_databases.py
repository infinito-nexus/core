#!/usr/bin/env python3
import json
import tempfile
from pathlib import Path
from unittest import TestCase, main, mock

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

    def test_cluster_argv_matches_the_baudolo_contract(self):
        cluster = databases.Cluster("postgres", "central-postgres", Path("/x"))
        argv = databases.cluster_argv(
            cluster,
            databases.generation_of(self.generation),
            "postgres-1",
            "postgres",
            "s3cret",
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
            "s3cret",
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

        def fake_run(argv, secret=""):
            calls.append(argv)
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
            mock.patch.object(recovery_docker, "_run", lambda argv, secret="": ""),
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
            mock.patch.object(recovery_docker, "_run", lambda argv, secret="": ""),
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
                lambda argv, secret="": "bigbluebutton\n" if "inspect" in argv else "",
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
            mock.patch.object(recovery_docker, "_run", lambda argv, secret="": ""),
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


if __name__ == "__main__":
    main()
