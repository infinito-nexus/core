"""The AppArmor teardown must keep docker-default loaded.

Run 39332343490 lost 39 swarm jobs: the runner's teardown unloaded every
profile, and BuildKit then failed each node image RUN step with
`apparmor failed to apply profile: write .../attr/apparmor/exec: no such file`.
"""

from __future__ import annotations

import subprocess
import unittest

from utils.cache.files import PROJECT_ROOT

COMMON = PROJECT_ROOT / "scripts" / "system" / "apparmor" / "common.sh"

PROFILES = """wg-quick (enforce)
wg-quick//ip (enforce)
docker-default (enforce)
/usr/bin/man (enforce)
unprivileged_userns (unconfined)
docker-defaults (complain)
"""


class TestRemovableProfiles(unittest.TestCase):
    def test_keeps_docker_default_and_child_profiles(self) -> None:
        result = subprocess.run(
            ["bash", "-c", f'source "{COMMON}"; apparmor_removable_profiles'],
            input=PROFILES,
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(
            [
                "wg-quick",
                "/usr/bin/man",
                "unprivileged_userns",
                "docker-defaults",
            ],
            result.stdout.splitlines(),
        )


if __name__ == "__main__":
    unittest.main()
