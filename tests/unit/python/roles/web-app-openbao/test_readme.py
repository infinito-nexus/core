from __future__ import annotations

import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

README = PROJECT_ROOT / "roles/web-app-openbao/README.md"
WORKSPACE_PATHS = (
    "auth/jwt",
    "jwks_url",
    "bound_issuer",
    "jwks_ca_pem",
    "`ws-<id>`",
    "`ws-<id>-provision`",
    "`tenant`",
    "`role` metadata",
    "`platform`",
    "transit/keys/ws-<id>-provision",
    "raft snapshot",
    "`workspace destroy`",
    "tenant/data/ws-<id>/",
    "tenant/data/ws-<id>-provision/",
    "The store AppRole",
    "Reach of a leaked store credential",
    "platform/data/store/hostkeys/ws-<id>/<host>/<port>",
    "`line`",
    "rotate store credentials",
    "platform/data/store/semaphore",
    "platform/data/store/gitea",
    "`token`",
    "`expires_at`",
    "auth/jwt-export",
    "tenant-export",
)


class TestTheReadme(unittest.TestCase):
    def test_the_readme_names_the_workspace_paths(self) -> None:
        text = read_text(str(README))
        self.assertEqual([path for path in WORKSPACE_PATHS if path not in text], [])

    def test_the_workspace_section_carries_no_em_dash(self) -> None:
        text = read_text(str(README))
        section = text.split("### Workspaces", 1)[1].split("### ", 1)[0]
        self.assertNotIn("—", section)


if __name__ == "__main__":
    unittest.main()
