from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT, read_text

README = PROJECT_ROOT / "roles" / "web-app-gitea" / "README.md"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def _missing(section: str, phrases: tuple[str, ...]) -> list[str]:
    return [phrase for phrase in phrases if phrase not in section]


ORGANIZATION_PHRASES = (
    "`services.gitea.workspaces.enabled: true`",
    "The organization `workspaces`",
    "private",
    "The store account `store`",
    "only owner",
    "repository limit to 0",
    "`write:organization`, `write:repository` and `read:user`",
    "`platform/data/store/gitea`",
    "`token` and `expires_at`",
    "only the rotation ends a token",
)

ACCESS_PHRASES = (
    "`permission` `read`",
    '`{"repo.code": "read"}`',
    "`includes_all_repositories` false",
    "`can_create_org_repo` false",
    "`Owner`, `Admin`, `Operator` and `Viewer`",
    "`Billing`",
    "Exactly two deploy keys and no collaborator",
    "Every deploy checks it",
    "a third deploy key, a second writing key or a collaborator",
)


class TestReadme(unittest.TestCase):
    def test_the_readme_names_the_workspace_organization(self):
        section = _section(read_text(str(README)), "## Workspace repositories")
        self.assertEqual(_missing(section, ORGANIZATION_PHRASES), [])

    def test_the_readme_names_the_workspace_access(self):
        section = _section(read_text(str(README)), "### Workspace access")
        self.assertEqual(_missing(section, ACCESS_PHRASES), [])


if __name__ == "__main__":
    unittest.main()
