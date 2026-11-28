from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_ENV_TEMPLATE = "templates/playwright.env.j2"
_SEMAPHORE_ENV = "roles/web-app-semaphore/" + _ENV_TEMPLATE
_PLANT_TARGET = "roles/web-app-keycloak/" + _ENV_TEMPLATE

_BROAD_CREDENTIAL = re.compile(
    r"secrets\.credentials\.approle_"
    r"|secrets\.credentials\.store_approle_"
    r"|['\"]web-app-semaphore-breakglass['\"]"
)
_SEMAPHORE_ADMIN = re.compile(r"\bSEMAPHORE_ADMIN_PASSWORD\b")
_PLANTS = (
    "X={{ lookup('config', 'web-app-openbao', 'secrets.credentials.approle_secret_id') }}",
    "X={{ lookup('config', 'web-app-openbao', 'secrets.credentials.store_approle_secret_id') }}",
    "X={{ lookup('users', 'web-app-semaphore-breakglass').password }}",
    "X={{ SEMAPHORE_ADMIN_PASSWORD }}",
)


def _playwright_envs() -> list[tuple[str, str]]:
    roles_prefix = str(PROJECT_ROOT / "roles") + "/"
    return [
        (Path(path).relative_to(PROJECT_ROOT).as_posix(), content)
        for path, content in iter_project_files_with_content(
            extensions=(".j2",), exclude_tests=True
        )
        if path.startswith(roles_prefix) and path.endswith(_ENV_TEMPLATE)
    ]


def _findings(rel: str, content: str) -> list[str]:
    """
    Args:
        rel: the template path relative to the project root.
        content: the template text.

    Returns:
        One entry per line that renders the Ansible AppRole, the store AppRole
        or a Semaphore break-glass password into a Playwright env file.
    """
    return [
        f"{rel}:{idx + 1}: {line.strip()}"
        for idx, line in enumerate(content.splitlines())
        if _BROAD_CREDENTIAL.search(line)
        or (rel != _SEMAPHORE_ENV and _SEMAPHORE_ADMIN.search(line))
    ]


class TestBroadCredentialNotInPlaywright(unittest.TestCase):
    def test_no_playwright_env_renders_a_broad_credential(self) -> None:  # nocheck: test.text-presence -- policy lint over every Playwright env template  # fmt: skip
        findings = sorted(
            finding
            for rel, content in _playwright_envs()
            for finding in _findings(rel, content)
        )
        self.assertEqual(
            [],
            findings,
            "a Playwright env file carries a deploy-wide credential; read it at "
            "run time through the Playwright AppRole instead:\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_scan_reads_playwright_env_templates(self) -> None:  # nocheck: test.text-presence -- reach guard of the Playwright env scan  # fmt: skip
        names = {rel for rel, _content in _playwright_envs()}
        self.assertIn(_SEMAPHORE_ENV, names)
        self.assertIn(_PLANT_TARGET, names)

    def test_control_a_planted_credential_fails(self) -> None:
        content = dict(_playwright_envs())[_PLANT_TARGET]
        for plant in _PLANTS:
            with self.subTest(plant=plant):
                self.assertNotEqual(
                    _findings(_PLANT_TARGET, content + "\n" + plant + "\n"), []
                )

    def test_control_semaphore_keeps_its_own_break_glass_only(self) -> None:
        content = dict(_playwright_envs())[_SEMAPHORE_ENV]
        self.assertEqual(
            _findings(_SEMAPHORE_ENV, content + "\n" + _PLANTS[3] + "\n"), []
        )
        self.assertNotEqual(
            _findings(_SEMAPHORE_ENV, content + "\n" + _PLANTS[2] + "\n"), []
        )


if __name__ == "__main__":
    unittest.main()
