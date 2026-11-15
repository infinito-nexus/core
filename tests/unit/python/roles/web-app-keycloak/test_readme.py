from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

README = PROJECT_ROOT / "roles/web-app-keycloak/README.md"
SECTION = "## Workspace Organizations"
NAMES = (
    "services.keycloak.organizations.enabled",
    "workspace.id",
    "`Owner` | `task_runner`",
    "`Admin` | `task_runner`",
    "`Operator` | `task_runner`",
    "`Billing` | none",
    "`Viewer` | `guest`",
    "`workspaces`",
    "`workspace_roles`",
    "`organization` claim",
    "services.sso.oidc.clients",
    "consumer_client",
    "login client only",
    "oidc-audience-mapper",
    "KEYCLOAK_CLIENT_SECRET_FILE",
    "`workspace-members`",
    "exactly `manage-organizations` and `manage-users`",
    "| Store operation | Template and action |",
    *(
        f"`members` `{action}`"
        for action in ("add", "invite", "uninvite", "role", "remove", "sync", "list")
    ),
    "`workspace` `apply`",
    "`workspace` `destroy`",
    "`user` `erase`",
    '{"workspace":"<id>","refused":"<reason>"}',
    '{"workspace":"<id>","absent":true}',
    *(
        f"`{reason}`"
        for reason in (
            "last_owner",
            "not_first",
            "member_address",
            "not_member",
            "managed",
            "platform_role",
            "absent",
        )
    ),
    "platform/data/store/invites/<id>/<INVITE_KEY>",
    "workspace.pending.<role>",
    "workspace.invite.<key>",
    '{"user":"<id>","erased":true}',
    "then the organization",
    "a further run changes nothing",
    "`view-realm`",
    "client `export`",
    "exactly `view-users`, `view-organizations` and `view-events`",
    "secrets.credentials.export_client_secret",
    "`platform/export/keycloak`",
    "`export_recipient`",
    "only its user edits and admins only view",
)


def section(text: str) -> str:
    """
    Args:
        text: the README.

    Returns:
        The workspace section, up to the next second-level heading.
    """
    start = text.index(SECTION)
    following = re.search(r"^## ", text[start + len(SECTION) :], re.MULTILINE)
    end = start + len(SECTION) + following.start() if following else len(text)
    return text[start:end]


def missing(text: str) -> list[str]:
    """
    Args:
        text: the README.

    Returns:
        Every name of NAMES the workspace section lacks.
    """
    body = section(text)
    return [name for name in NAMES if name not in body]


class TestReadme(unittest.TestCase):
    def test_the_readme_names_the_workspace_identity(self) -> None:
        self.assertEqual(missing(read_text(str(README))), [])

    def test_the_check_catches_each_dropped_name(self) -> None:
        text = read_text(str(README))
        for name in NAMES:
            with self.subTest(name=name):
                self.assertIn(name, missing(text.replace(name, "")))

    def test_the_check_reads_only_the_workspace_section(self) -> None:
        text = read_text(str(README))
        body = section(text)
        moved = (
            text.replace(body, SECTION + "\n")
            + "\n"
            + body.replace(SECTION, "## Elsewhere")
        )
        self.assertEqual(sorted(missing(moved)), sorted(NAMES))


if __name__ == "__main__":
    unittest.main()
