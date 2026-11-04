"""Keep the test personas out of production code.

``biber`` and ``mapache`` exist to exercise the authorisation surface from a
non-administrator angle: the Playwright journeys and the CLI test fixtures sign
in as them to prove that a normal account is granted what it should be and
denied what it should not. They are fixtures, not deployment accounts, and
nothing in ``roles/*/meta/users.yml`` declares them.

Production code that reads one of them therefore provisions a login the
deployment never asked for, and the RBAC proof stops meaning anything: a
persona that real code depends on has to be granted real access, which is the
opposite of what the journeys assert.

Scope: every git-tracked code file, except the Playwright and CLI test surfaces
enumerated by ``tests.utils.personas.is_test_surface``.
"""

from __future__ import annotations

import re
import unittest

from tests.utils.personas import TEST_PERSONA_USERS, is_test_surface
from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT

_PERSONA_READ = re.compile(
    r"lookup\(\s*(['\"])users\1\s*,\s*(['\"])(" + "|".join(TEST_PERSONA_USERS) + r")\2"
)

_SUFFIXES = (".yml", ".yaml", ".j2", ".py", ".js", ".sh", ".sql")


class TestTestPersonaNotInProduction(unittest.TestCase):
    def test_test_personas_are_read_only_by_tests(self) -> None:
        findings: list[str] = []

        for path in iter_non_ignored_files(extensions=_SUFFIXES):
            rel = str(path).replace(f"{PROJECT_ROOT}/", "")
            if is_test_surface(rel):
                continue
            try:
                content = read_text(str(path))
            except OSError:
                continue
            for number, line in enumerate(content.splitlines(), start=1):
                if line.lstrip().startswith("#"):
                    continue
                findings.extend(
                    f"{rel}:{number}: reads test persona '{match.group(3)}'"
                    for match in _PERSONA_READ.finditer(line)
                )

        if findings:
            self.fail(
                "The test personas "
                + ", ".join(f"'{name}'" for name in TEST_PERSONA_USERS)
                + " may only be read from the Playwright and CLI test surfaces "
                "(templates/playwright.env.j2, templates/test.env.j2, "
                "roles/test-*/, files/playwright/, tests/). Production code must "
                "use a declared deployment account instead:\n  - "
                + "\n  - ".join(findings)
            )


if __name__ == "__main__":
    unittest.main()
