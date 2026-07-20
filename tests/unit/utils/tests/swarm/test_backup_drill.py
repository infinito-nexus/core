from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT


BACKUP_SCRIPTS = PROJECT_ROOT / "scripts/tests/deploy/swarm/routine/backup"
ROLE_TEST_SCRIPTS = PROJECT_ROOT / "roles/svc-bkp-volume-2-local/files/test"


class TestDatabaseRestoreHandoff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.test_dir = self.root / "role-test"
        self.test_dir.mkdir()
        (self.test_dir / "test.env").write_text(
            "BKP_TEST_SWARM_DRILL=true\nBKP_TEST_DATABASES_CSV=/unused\n"
        )

    def test_restore_consumes_handoff_only_after_manifest_is_written(self):
        backups = self.root / "backups"
        (backups / "machine" / "repo" / "generation").mkdir(parents=True)
        (self.test_dir / "swarm-restore.pending").write_text(
            "MACHINE_HASH=machine\n"
            "REPO_NAME=repo\n"
            "NEWEST_GENERATION=generation\n"
            "PROBE_PRE_TOKEN=before\n"
            "PROBE_POST_TOKEN=after\n"
        )
        restore = self.test_dir / "db_restore.sh"
        restore.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            ": \"${BKP_TEST_BACKUPS_DIR:?}\" \"${REPO_DIR:?}\"\n"
            "printf 'postgres;postgres_data;app\\n' >\"${BKP_TEST_RESTORED_DATABASES_FILE}\"\n"
        )
        restore.chmod(0o755)

        subprocess.run(
            [
                "bash",
                str(BACKUP_SCRIPTS / "06_restore_databases.sh"),
                str(self.test_dir),
                str(backups),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertFalse((self.test_dir / "swarm-restore.pending").exists())
        self.assertTrue((self.test_dir / "swarm-restore.complete").is_file())
        self.assertTrue((self.test_dir / "swarm-restore.manifest").is_file())

    def test_verify_passes_completed_probe_tokens_to_role_helper(self):
        (self.test_dir / "swarm-restore.complete").write_text(
            "PROBE_PRE_TOKEN=before\nPROBE_POST_TOKEN=after\n"
        )
        manifest = self.test_dir / "swarm-restore.manifest"
        manifest.write_text("postgres;postgres_data;app\n")
        verified = self.root / "probe-verified"
        probe = self.test_dir / "db_probe.sh"
        probe.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "test \"$1\" = verify\n"
            "test \"$2\" = before\n"
            "test \"$3\" = after\n"
            f"test \"$4\" = {manifest}\n"
            "touch \"${PROBE_VERIFIED:?}\"\n"
        )
        probe.chmod(0o755)
        env = os.environ.copy()
        env["PROBE_VERIFIED"] = str(verified)

        subprocess.run(
            [
                "bash",
                str(BACKUP_SCRIPTS / "07_verify_databases.sh"),
                str(self.test_dir),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertTrue(verified.is_file())


class TestDatabaseRestoreProbe(unittest.TestCase):
    def test_seeds_and_verifies_postgres_and_mariadb(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_file = root / "databases.csv"
            csv_file.write_text(
                "instance;database;username;password\n"
                "postgres;app_pg;user_pg;pw_pg\n"
                "mariadb;app_my;user_my;pw_my\n"
            )
            manifest = root / "manifest"
            manifest.write_text(
                "postgres;postgres_data;app_pg\n"
                "mariadb;mariadb_data;app_my\n"
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            container = fake_bin / "container"
            container.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "case \"$1\" in\n"
                "  ps)\n"
                "    case \"$*\" in\n"
                "      *postgres_data*) printf 'postgres.1\\n' ;;\n"
                "      *mariadb_data*) printf 'mariadb.1\\n' ;;\n"
                "    esac\n"
                "    ;;\n"
                "  inspect)\n"
                "    case \"${*: -1}\" in\n"
                "      postgres.1) printf 'postgres_custom\\n' ;;\n"
                "      mariadb.1) printf 'mariadb_custom\\n' ;;\n"
                "    esac\n"
                "    ;;\n"
                "  exec)\n"
                "    case \"$*\" in\n"
                "      *SELECT*before*)\n"
                "        test -f \"${DB_STATE:?}/seeded-${4}\" && printf '1\\n' || printf '0\\n'\n"
                "        ;;\n"
                "      *SELECT*after*) printf '0\\n' ;;\n"
                "      *) touch \"${DB_STATE:?}/seeded-${4}\" ;;\n"
                "    esac\n"
                "    ;;\n"
                "esac\n"
            )
            container.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            env["BKP_TEST_DATABASES_CSV"] = str(csv_file)
            env["DB_STATE"] = str(root)

            subprocess.run(
                ["bash", str(ROLE_TEST_SCRIPTS / "db_probe.sh"), "seed", "before"],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertTrue((root / "seeded-postgres.1").is_file())
            self.assertTrue((root / "seeded-mariadb.1").is_file())

            subprocess.run(
                [
                    "bash",
                    str(ROLE_TEST_SCRIPTS / "db_probe.sh"),
                    "verify",
                    "before",
                    "after",
                    str(manifest),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )


class TestDatabaseWriterQuiesce(unittest.TestCase):
    def test_keeps_only_database_registry_and_stops_discourse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            docker = fake_bin / "docker"
            docker.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "case \"$1 $2\" in\n"
                "  'stack ls') printf 'docker\\npostgres\\nwordpress\\n' ;;\n"
                "  'stack services')\n"
                "    case \"$3\" in\n"
                "      docker) printf 'registry:2\\n' ;;\n"
                "      postgres) printf 'localhost:5000/postgres_custom:17\\n' ;;\n"
                "      wordpress) printf 'wordpress:latest\\n' ;;\n"
                "    esac\n"
                "    ;;\n"
                "  'stack rm') touch \"${DOCKER_STATE:?}/removed-$3\" ;;\n"
                "  'service ls') : ;;\n"
                "  'ps --format')\n"
                "    printf 'db\\tlocalhost:5000/postgres_custom:17\\n'\n"
                "    printf 'registry\\tregistry:2\\n'\n"
                "    printf 'discourse\\tlocal_discourse/discourse:latest\\n'\n"
                "    printf 'wordpress-task\\twordpress:latest\\n'\n"
                "    ;;\n"
                "  'stop discourse')\n"
                "    touch \"${DOCKER_STATE:?}/stopped-$2\" \"${DOCKER_STATE:?}/stopped-$3\"\n"
                "    ;;\n"
                "  *) printf 'unexpected docker call: %s\\n' \"$*\" >&2; exit 1 ;;\n"
                "esac\n"
            )
            docker.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            env["DOCKER_STATE"] = str(root)

            subprocess.run(
                [
                    "bash",
                    str(BACKUP_SCRIPTS / "04_quiesce_database_writers.sh"),
                    "manager",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertTrue((root / "removed-wordpress").is_file())
            self.assertTrue((root / "stopped-discourse").is_file())
            self.assertTrue((root / "stopped-wordpress-task").is_file())
            self.assertFalse((root / "removed-postgres").exists())
            self.assertFalse((root / "removed-docker").exists())
            self.assertFalse((root / "stopped-db").exists())
            self.assertFalse((root / "stopped-registry").exists())


if __name__ == "__main__":
    unittest.main()
