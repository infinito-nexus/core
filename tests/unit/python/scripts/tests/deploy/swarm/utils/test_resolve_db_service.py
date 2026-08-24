"""Which swarm service the converge gate accepts as a role's database.

``resolve_db_service`` in ``scripts/tests/deploy/swarm/utils/_context.sh`` picks
between two naming schemes that ``plugins/lookup/database.py`` keeps apart: a
role pinning its own engine runs it as ``<entity>_database`` inside its own
stack, a central provider as ``<dep>_<dep>`` in its own. Guessing one of them
cost run 32630684501 a job - ``mariadb_mariadb`` never existed for Magento - and
the same guess passed vacuously in the all-bonds variant, where an unrelated
role had dragged the central provider in. Pinned here: the local engine wins
when both are deployed, the central name is still used when only it exists, and
a name that is deployed for nobody yields nothing instead of a false match.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

CONTEXT = (
    PROJECT_ROOT / "scripts" / "tests" / "deploy" / "swarm" / "utils" / "_context.sh"
)
PINNED_ENGINE_APP = "web-app-magento"
NO_DB_APP = "web-svc-html"
LOCAL_SERVICE = "magento_database"
CENTRAL_SERVICE = "mariadb_mariadb"


class TestResolveDbService(unittest.TestCase):
    def _resolve(self, app_id: str, deployed: tuple[str, ...]) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            stub_bin = Path(tmp) / "bin"
            stub_bin.mkdir()
            docker = stub_bin / "docker"
            docker.write_text(
                "#!/usr/bin/env bash\nprintf '%s\\n' {}\n".format(
                    " ".join(f"'{name}'" for name in deployed) or '""'
                )
            )
            docker.chmod(0o755)

            env = dict(os.environ)
            env.update(
                APP_ID=app_id,
                MGR="stub-manager",
                PATH=f"{stub_bin}:{env['PATH']}",
                BASH_ENV="",
            )
            proc = subprocess.run(
                ["bash", "-c", f'source "{CONTEXT}"; resolve_db_service'],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            return proc.stdout.strip()

    def test_the_local_engine_wins_when_the_central_one_is_also_deployed(self) -> None:
        self.assertEqual(
            self._resolve(PINNED_ENGINE_APP, (LOCAL_SERVICE, CENTRAL_SERVICE)),
            LOCAL_SERVICE,
        )

    def test_the_local_engine_is_found_when_it_is_the_only_one(self) -> None:
        self.assertEqual(
            self._resolve(PINNED_ENGINE_APP, (LOCAL_SERVICE,)), LOCAL_SERVICE
        )

    def test_the_central_provider_is_used_when_no_local_engine_exists(self) -> None:
        self.assertEqual(
            self._resolve(PINNED_ENGINE_APP, (CENTRAL_SERVICE,)), CENTRAL_SERVICE
        )

    def test_a_substring_of_a_deployed_name_is_not_a_match(self) -> None:
        self.assertEqual(
            self._resolve(PINNED_ENGINE_APP, ("other_mariadb_mariadb_replica",)), ""
        )

    def test_nothing_is_resolved_when_neither_scheme_is_deployed(self) -> None:
        self.assertEqual(self._resolve(PINNED_ENGINE_APP, ("magento_nginx",)), "")

    def test_a_role_without_a_database_dep_resolves_nothing(self) -> None:
        self.assertEqual(self._resolve(NO_DB_APP, (CENTRAL_SERVICE,)), "")


if __name__ == "__main__":
    unittest.main()
