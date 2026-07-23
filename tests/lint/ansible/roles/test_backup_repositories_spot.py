"""Lint: ``BACKUP_REPOSITORIES`` is the SPOT for provider backup repo names.

The ssh-wrapper on every provider whitelists discovery AND pull access from
``group_vars/all/05_paths.yml.BACKUP_REPOSITORIES``. Every ``svc-bkp-*`` role
that writes a repo under ``DIR_BACKUPS/<machine-hash>/`` declares its name in
a ``*_REPO_NAME`` var (baudolo's implicit default is
``backup-docker-to-local``). Both sides must match exactly: a producer
missing from the SPOT breaks every remote pull from that host, and a SPOT
entry without a producer is stale.
"""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

_GROUP_VARS_PATHS = "group_vars/all/05_paths.yml"
_BAUDOLO_DEFAULT_REPO = "backup-docker-to-local"


class TestBackupRepositoriesSpot(unittest.TestCase):
    def test_spot_matches_producers(self) -> None:
        spot_path = PROJECT_ROOT / _GROUP_VARS_PATHS
        spot = load_yaml(str(spot_path)).get("BACKUP_REPOSITORIES")
        self.assertIsInstance(
            spot,
            list,
            f"BACKUP_REPOSITORIES missing or not a list in {_GROUP_VARS_PATHS}",
        )

        producers = {_BAUDOLO_DEFAULT_REPO}
        for vars_path in sorted(
            (PROJECT_ROOT / "roles").glob(f"svc-bkp-*/{ROLE_FILE_VARS_MAIN}")
        ):
            data = load_yaml(str(vars_path), default_if_missing={})
            for key, value in data.items():
                if key.endswith("_REPO_NAME") and isinstance(value, str):
                    producers.add(value)

        self.assertEqual(
            sorted(spot),
            sorted(producers),
            "BACKUP_REPOSITORIES and the svc-bkp-* repo names diverge: "
            f"SPOT={sorted(spot)} producers={sorted(producers)}. Add new repo "
            f"names to {_GROUP_VARS_PATHS} (the ssh-wrapper whitelist) and "
            "remove stale entries.",
        )


if __name__ == "__main__":
    unittest.main()
