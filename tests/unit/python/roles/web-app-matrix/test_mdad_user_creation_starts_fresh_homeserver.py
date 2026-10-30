from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES

ROLE = PROJECT_ROOT / "roles" / "web-app-matrix"
BOOTSTRAP = ROLE / "files" / "flavor" / "ansible" / "runner" / "bootstrap.sh"
SERVICES = ROLE / ROLE_FILE_META_SERVICES
USER_CREATION_TAG = "ensure-matrix-users-created"
PLAYBOOK = re.compile(r"^\s*\S*ansible-playbook\s")
STOP_HOMESERVER = re.compile(r"\bsystemctl\s+stop\s+matrix-synapse\.service\b")


class TestMdadUserCreationStartsFreshHomeserver(unittest.TestCase):
    def test_the_homeserver_is_stopped_before_the_playbook_creates_users(
        self,
    ) -> None:
        tags = load_yaml_str(read_text(str(SERVICES)))["matrix"]["playbook_tags"]
        self.assertIn(USER_CREATION_TAG, tags.split(","))
        lines = read_text(str(BOOTSTRAP)).splitlines()
        playbook = next(
            index for index, line in enumerate(lines) if PLAYBOOK.match(line)
        )
        self.assertTrue(
            any(STOP_HOMESERVER.search(line) for line in lines[:playbook]),
            "a reconfigure reboots matrix-mdad, systemd auto-starts "
            "matrix-synapse on the homeserver.yaml the previous run rendered, "
            "and after a credential rotation it crash-loops on the old database "
            f"password; {USER_CREATION_TAG} runs before 'start', its "
            "'state: started' sees the unit activating, skips its wait, and "
            "register_new_matrix_user dies with 'No such container: "
            "matrix-synapse', so bootstrap.sh must stop the homeserver before "
            "the playbook renders the new configuration",
        )


if __name__ == "__main__":
    unittest.main()
